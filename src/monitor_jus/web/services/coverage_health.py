"""Saúde de cobertura DJEN por critério (agrega source_runs)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.db.models import Criterion, SourceCheckpoint, SourceRun

# ~3× intervalo do DJEN_POLL (60 min)
STALE_HOURS = 3
SATURATION_LOOKBACK_HOURS = 48


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)[:16]


def criterion_poll_health(
    session: Session,
    *,
    stale_hours: int = STALE_HOURS,
    saturation_hours: int = SATURATION_LOOKBACK_HOURS,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Mapa criteria_id → saúde do último DJEN_POLL."""
    now = now or datetime.now(timezone.utc)
    stale_before = now - timedelta(hours=stale_hours)
    sat_cutoff = now - timedelta(hours=saturation_hours)

    runs = list(
        session.scalars(
            select(SourceRun)
            .where(
                SourceRun.job_type == "DJEN_POLL",
                SourceRun.criteria_id.is_not(None),
            )
            .order_by(SourceRun.finished_at.desc().nulls_last(), SourceRun.started_at.desc())
        ).all()
    )

    by_id: dict[str, dict[str, Any]] = {}
    for run in runs:
        cid = run.criteria_id
        if not cid:
            continue
        bucket = by_id.setdefault(
            cid,
            {
                "last_success_at": None,
                "last_failure_at": None,
                "last_status": "NEVER",
                "last_error": None,
                "hit_max_pages_recent": False,
                "_seen_latest": False,
            },
        )
        finished = _aware(run.finished_at) or _aware(run.started_at)
        cursor = run.cursor_json if isinstance(run.cursor_json, dict) else {}
        if (
            run.status == "SUCCESS"
            and cursor.get("hit_max_pages")
            and finished
            and finished >= sat_cutoff
        ):
            bucket["hit_max_pages_recent"] = True

        if not bucket["_seen_latest"] and run.status in {"SUCCESS", "FAILED"}:
            bucket["_seen_latest"] = True
            bucket["last_status"] = run.status
            if run.status == "FAILED":
                bucket["last_error"] = (run.error_message or run.error_code or "falha")[:200]

        if run.status == "SUCCESS" and bucket["last_success_at"] is None:
            bucket["last_success_at"] = finished
        elif run.status == "FAILED" and bucket["last_failure_at"] is None:
            bucket["last_failure_at"] = finished

    for bucket in by_id.values():
        bucket.pop("_seen_latest", None)
        success_at = bucket["last_success_at"]
        status = bucket["last_status"]
        if status == "NEVER":
            badge = "nunca"
            stale = True
        elif status == "FAILED":
            badge = "falhou"
            stale = True
        elif success_at is None or success_at < stale_before:
            badge = "atrasado"
            stale = True
        else:
            badge = "ok"
            stale = False
        bucket["badge"] = badge
        bucket["stale"] = stale
        bucket["last_success_at_fmt"] = _fmt(success_at)
        bucket["last_failure_at_fmt"] = _fmt(bucket["last_failure_at"])

    return by_id


def coverage_attention(
    session: Session,
    *,
    djen_enabled: bool,
    stale_hours: int = STALE_HOURS,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Alertas para o bloco Atenção do dashboard."""
    if not djen_enabled:
        return []

    now = now or datetime.now(timezone.utc)
    alerts: list[dict[str, str]] = []
    health = criterion_poll_health(session, stale_hours=stale_hours, now=now)
    criteria = list(
        session.scalars(select(Criterion).where(Criterion.active.is_(True))).all()
    )

    stale_labels: list[str] = []
    failed_labels: list[str] = []
    saturated_labels: list[str] = []
    never_labels: list[str] = []

    for crit in criteria:
        h = health.get(crit.id) or {
            "badge": "nunca",
            "stale": True,
            "hit_max_pages_recent": False,
        }
        label = f"{crit.criterion_type}:{crit.value}"
        badge = h.get("badge")
        if badge == "nunca":
            never_labels.append(label)
        elif badge == "falhou":
            failed_labels.append(label)
        elif badge == "atrasado":
            stale_labels.append(label)
        if h.get("hit_max_pages_recent"):
            saturated_labels.append(label)

    if never_labels:
        sample = ", ".join(never_labels[:3])
        extra = f" (+{len(never_labels) - 3})" if len(never_labels) > 3 else ""
        alerts.append(
            {
                "level": "warn",
                "text": f"Critério(s) sem poll DJEN registrado: {sample}{extra}",
            }
        )
    if failed_labels:
        sample = ", ".join(failed_labels[:3])
        extra = f" (+{len(failed_labels) - 3})" if len(failed_labels) > 3 else ""
        alerts.append(
            {
                "level": "error",
                "text": f"Poll DJEN falhou recentemente: {sample}{extra}",
            }
        )
    if stale_labels:
        sample = ", ".join(stale_labels[:3])
        extra = f" (+{len(stale_labels) - 3})" if len(stale_labels) > 3 else ""
        alerts.append(
            {
                "level": "warn",
                "text": (
                    f"Critério(s) sem sucesso DJEN há mais de {stale_hours}h: "
                    f"{sample}{extra}"
                ),
            }
        )
    if saturated_labels:
        sample = ", ".join(saturated_labels[:3])
        extra = f" (+{len(saturated_labels) - 3})" if len(saturated_labels) > 3 else ""
        alerts.append(
            {
                "level": "warn",
                "text": (
                    f"Possível buraco de cobertura (max_pages atingido): "
                    f"{sample}{extra}"
                ),
            }
        )

    cp = session.scalar(
        select(SourceCheckpoint).where(
            SourceCheckpoint.source == "djen",
            SourceCheckpoint.checkpoint_key == "last_poll_success",
        )
    )
    if cp is None:
        alerts.append(
            {
                "level": "warn",
                "text": "Checkpoint DJEN (last_poll_success) ainda não existe",
            }
        )
    else:
        updated = _aware(cp.updated_at)
        cursor = cp.cursor if isinstance(cp.cursor, dict) else {}
        at_raw = cursor.get("at")
        if updated is None and at_raw:
            try:
                updated = datetime.fromisoformat(str(at_raw).replace("Z", "+00:00"))
            except ValueError:
                updated = None
        if updated is None or updated < now - timedelta(hours=stale_hours):
            alerts.append(
                {
                    "level": "warn",
                    "text": (
                        f"Checkpoint DJEN sem avanço há mais de {stale_hours}h "
                        "(poll parcial ou parado)"
                    ),
                }
            )

    return alerts


def digest_source_health(
    session: Session,
    *,
    stale_hours: int = STALE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resumo curto para o e-mail diário."""
    now = now or datetime.now(timezone.utc)
    health = criterion_poll_health(session, stale_hours=stale_hours, now=now)
    criteria = list(
        session.scalars(select(Criterion).where(Criterion.active.is_(True))).all()
    )
    rows: list[dict[str, Any]] = []
    ok = stale = failed = never = 0
    for crit in criteria:
        h = health.get(crit.id) or {
            "badge": "nunca",
            "stale": True,
            "last_success_at_fmt": "—",
            "last_failure_at_fmt": "—",
            "hit_max_pages_recent": False,
        }
        badge = h.get("badge") or "nunca"
        if badge == "ok":
            ok += 1
        elif badge == "atrasado":
            stale += 1
        elif badge == "falhou":
            failed += 1
        else:
            never += 1
        rows.append(
            {
                "type": crit.criterion_type,
                "value": crit.value,
                "badge": badge,
                "last_success_at": h.get("last_success_at_fmt") or "—",
                "hit_max_pages": bool(h.get("hit_max_pages_recent")),
            }
        )
    return {
        "ok": ok,
        "stale": stale,
        "failed": failed,
        "never": never,
        "total": len(criteria),
        "rows": rows,
        "has_issues": bool(stale or failed or never),
    }
