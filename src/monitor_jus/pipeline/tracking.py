"""PROCESS_REFRESH — enriquecimento DataJud + evento só em delta material."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_yaml
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import FailedRateLimit, SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.models import EventType, JobType, NotifyStatus, RunMode, RunType
from monitor_jus.official_portal import resolve_official_link_result
from monitor_jus.pipeline.identity import (
    material_movement_from_mapping,
    material_movement_tuple,
    movement_identity_hash,
)
from monitor_jus.pipeline.normalize import normalize_datajud_hits
from monitor_jus.progress import report as report_progress
from monitor_jus.sources.datajud import DataJudClient
from monitor_jus.sources.datajud_router import resolve_process_source
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)

BATCH_SIZE = 75


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _next_check(
    situacao: str | None,
    last_movement_at: datetime | None,
    cfg: dict,
    *,
    had_new_publication: bool = False,
    failure_streak: int = 0,
    rate_limited: bool = False,
) -> datetime:
    now = datetime.now(timezone.utc)
    backoff = cfg.get("backoff") or {}
    if rate_limited:
        hours_list = backoff.get("on_429_hours") or [1, 3, 6, 12, 24]
        hours = hours_list[min(max(failure_streak, 1) - 1, len(hours_list) - 1)]
        return now + timedelta(hours=int(hours))
    if failure_streak > 0:
        hours_list = backoff.get("on_5xx_hours") or [1, 2, 4, 8, 16]
        hours = hours_list[min(failure_streak - 1, len(hours_list) - 1)]
        return now + timedelta(hours=int(hours))

    if had_new_publication:
        return now + timedelta(hours=2)

    situ = (situacao or "").lower()
    if any(x in situ for x in ("arquiv", "baix", "julgad", "cancel", "encerr")):
        return now + timedelta(days=21)

    last_mov = _aware(last_movement_at)
    if last_mov:
        idle = (now - last_mov).days
        if idle >= 30:
            return now + timedelta(days=5)

    default_hours = int(cfg.get("default_hours") or 24)
    return now + timedelta(hours=default_hours)


def _material_state_from_process(proc: Any) -> tuple[str, str, str, str, str]:
    payload = proc.payload if isinstance(proc.payload, dict) else {}
    dj = payload.get("datajud") if isinstance(payload.get("datajud"), dict) else {}
    return material_movement_from_mapping(
        {
            "movement_code": dj.get("last_movement_code"),
            "datetime": dj.get("last_movement_date") or proc.last_movement_at,
            "description": dj.get("last_movement_name"),
            "orgao": dj.get("orgao_julgador") or proc.orgao_julgador,
            "complemento": dj.get("last_movement_complemento"),
        }
    )


def _material_state_from_norm(norm: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return material_movement_tuple(
        movement_code=str(norm.get("last_movement_code") or "") or None,
        data_hora=norm.get("last_movement_date") or norm.get("last_movement_at"),
        description=str(norm.get("last_movement_name") or "") or None,
        orgao=str(norm.get("orgao_julgador") or "") or None,
        complemento=str(norm.get("last_movement_complemento") or "") or None,
    )


def material_movement_changed(
    previous: tuple[str, str, str, str, str],
    current: tuple[str, str, str, str, str],
) -> bool:
    if current == ("", "", "", "", ""):
        return False
    return previous != current


def _apply_datajud_enrichment(proc: Any, norm: dict[str, Any]) -> None:
    """Atualiza capa a partir do DataJud (instância mais alta conhecida)."""
    if norm.get("classe"):
        proc.classe = norm["classe"]
    if norm.get("assunto"):
        proc.assunto = norm["assunto"]
    if norm.get("orgao_julgador"):
        proc.orgao_julgador = norm["orgao_julgador"]
    if norm.get("grau"):
        proc.grau = norm["grau"]
    if norm.get("tribunal"):
        proc.tribunal = norm["tribunal"]
    if norm.get("situacao"):
        proc.situacao = norm["situacao"]
    if norm.get("last_movement_at"):
        mov_at = norm["last_movement_at"]
        proc.datajud_last_movement_at = mov_at
        prev_mov = proc.last_movement_at
        if prev_mov is not None and prev_mov.tzinfo is None and getattr(mov_at, "tzinfo", None):
            prev_mov = prev_mov.replace(tzinfo=timezone.utc)
        if prev_mov is None or (mov_at and mov_at > prev_mov):
            proc.last_movement_at = mov_at

    cnj = normalize_cnj(proc.numero_cnj)
    link = resolve_official_link_result(
        proc.numero_cnj,
        tribunal=proc.tribunal,
        payload={
            "datajud": norm.get("raw"),
            "instances": norm.get("instances"),
            "has_second_degree": norm.get("has_second_degree"),
            "instance_summary": norm.get("instance_summary"),
        },
        classe=proc.classe,
        grau=proc.grau if not norm.get("has_second_degree") else "G2",
    )
    if link.url:
        proc.official_link = link.url
        proc.official_link_type = link.link_type

    prev = proc.payload if isinstance(proc.payload, dict) else {}
    proc.payload = {
        **prev,
        "datajud": {
            "grau": norm.get("grau"),
            "classe": norm.get("classe"),
            "assunto": norm.get("assunto"),
            "orgao_julgador": norm.get("orgao_julgador"),
            "situacao": norm.get("situacao"),
            "instances": norm.get("instances"),
            "instance_summary": norm.get("instance_summary"),
            "instance_label": norm.get("instance_label"),
            "has_second_degree": norm.get("has_second_degree"),
            "reached_superior": norm.get("reached_superior"),
            "last_movement_name": norm.get("last_movement_name"),
            "last_movement_date": norm.get("last_movement_date"),
            "last_movement_code": norm.get("last_movement_code"),
            "last_movement_complemento": norm.get("last_movement_complemento"),
        },
        "official_link": link.url,
        "official_link_type": link.link_type,
        "cnj_digits": cnj.numero_digits if cnj else proc.numero_cnj_digits,
    }


def _maybe_create_movement_event(
    session: Session,
    repo: Repository,
    proc: Any,
    norm: dict[str, Any],
) -> bool:
    identity = movement_identity_hash(
        numero_cnj=proc.numero_cnj,
        movement_code=str(norm.get("last_movement_code") or "") or None,
        data_hora=norm.get("last_movement_date") or norm.get("last_movement_at"),
        description=str(norm.get("last_movement_name") or "") or None,
        orgao=str(norm.get("orgao_julgador") or "") or None,
        complemento=str(norm.get("last_movement_complemento") or "") or None,
    )
    payload_hash = identity[:64]
    title = f"{proc.tribunal or 'Tribunal'} · {norm.get('last_movement_name') or 'Movimentação'}"
    description = str(norm.get("last_movement_name") or "")[:2000]
    link = proc.official_link
    _event, created = repo.create_event_if_absent(
        event_identity_key=identity,
        payload_hash=payload_hash,
        event_type=EventType.MOVIMENTACAO_PROCESSUAL.value,
        notify_status=NotifyStatus.PENDING_NOTIFY.value,
        source_name="datajud",
        source_event_id=None,
        numero_cnj=proc.numero_cnj,
        tribunal=proc.tribunal,
        title=title,
        description=description,
        priority="media",
        tipo_movimentacao=str(norm.get("last_movement_name") or "")[:64] or None,
        official_link=link,
    )
    return created


def run_tracking(
    session: Session,
    settings: Settings | None = None,
    *,
    only_incomplete: bool = False,
    force_all_incomplete: bool = False,
    parent_job_id: str | None = None,
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    datajud = DataJudClient(settings)
    freq_cfg = load_yaml(settings.config_path("check_frequency.yaml"))

    if only_incomplete:
        due = repo.processes_incomplete_capa(limit=batch_size)
        label = "CAPA_INCOMPLETA"
    else:
        due = repo.processes_due(limit=batch_size)
        label = "PROCESS_REFRESH"
    _ = force_all_incomplete

    refreshed = 0
    skipped_stf = 0
    events_created = 0
    errors = 0
    outcomes: list[dict[str, Any]] = []
    n_due = max(len(due), 1)
    report_progress(
        stage="tracking",
        done=0,
        total=n_due,
        message=f"{label} · {len(due)} processo(s)",
        force=True,
    )

    for idx, proc in enumerate(due):
        report_progress(
            stage="tracking",
            done=idx,
            total=n_due,
            message=f"Atualizando {proc.numero_cnj}",
        )
        route = resolve_process_source(proc.numero_cnj, proc.tribunal, settings=settings)
        now = datetime.now(timezone.utc)
        proc.datajud_last_checked_at = now
        previous = _material_state_from_process(proc)

        if route.source == "STF_DJEN_PORTAL":
            skipped_stf += 1
            link = resolve_official_link_result(proc.numero_cnj, tribunal="STF")
            proc.official_link = link.url or proc.official_link
            proc.official_link_type = link.link_type
            proc.next_check_at = _next_check(proc.situacao, proc.last_movement_at, freq_cfg)
            outcomes.append({"cnj": proc.numero_cnj, "route": route.source, "skipped": True})
            continue

        if route.source != "DATAJUD" or not route.datajud_alias:
            proc.requires_reconciliation = True
            proc.next_check_at = _next_check(proc.situacao, proc.last_movement_at, freq_cfg)
            outcomes.append({"cnj": proc.numero_cnj, "route": route.source, "skipped": True})
            continue

        try:
            hits = datajud.search_all_by_cnj(proc.numero_cnj, alias=route.datajud_alias)
            had_material = False
            if hits:
                norm = normalize_datajud_hits(hits)
                current = _material_state_from_norm(norm)
                _apply_datajud_enrichment(proc, norm)
                fingerprint = hashlib.sha256(
                    json.dumps(
                        [{"grau": h.get("grau"), "id": h.get("id")} for h in hits],
                        sort_keys=True,
                        default=str,
                    ).encode()
                ).hexdigest()[:64]
                proc.datajud_fingerprint = fingerprint
                proc.datajud_last_success_at = now
                refreshed += 1
                if material_movement_changed(previous, current):
                    if _maybe_create_movement_event(session, repo, proc, norm):
                        events_created += 1
                        had_material = True
            proc.last_checked_at = now
            proc.next_check_at = _next_check(
                proc.situacao,
                proc.last_movement_at,
                freq_cfg,
                had_new_publication=had_material,
            )
            outcomes.append(
                {
                    "cnj": proc.numero_cnj,
                    "route": route.source,
                    "ok": True,
                    "hits": len(hits),
                    "material_event": had_material,
                    "grau": getattr(proc, "grau", None),
                    "situacao": proc.situacao,
                }
            )
        except FailedRateLimit as exc:
            errors += 1
            proc.next_check_at = _next_check(
                proc.situacao,
                proc.last_movement_at,
                freq_cfg,
                failure_streak=1,
                rate_limited=True,
            )
            outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "error": str(exc)})
            continue
        except SourceOutcomeError as exc:
            errors += 1
            proc.next_check_at = _next_check(
                proc.situacao,
                proc.last_movement_at,
                freq_cfg,
                failure_streak=1,
            )
            outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "error": str(exc)})
            continue

    session.flush()
    remaining = 0 if only_incomplete else repo.count_due_processes()
    requeued = False
    if remaining > 0 and not only_incomplete:
        # Continuidade: key única por job pai (não usa has_active — o pai ainda está RUNNING)
        cont_key = f"refresh-cont:{parent_job_id or uuid4().hex[:12]}"
        run = repo.create_run(
            RunType.PROCESS_REFRESH.value,
            trigger_type="schedule",
            run_mode=RunMode.LIVE.value,
            idempotency_key=f"run:{cont_key}",
        )
        job = repo.enqueue_job(
            run.id,
            JobType.PROCESS_REFRESH.value,
            payload={"continuation": True},
            max_attempts=settings.job_max_attempts,
            idempotency_key=cont_key,
        )
        requeued = job is not None

    report_progress(
        stage="tracking",
        done=n_due,
        total=n_due,
        message="PROCESS_REFRESH concluído",
        force=True,
    )
    return {
        "due": len(due),
        "refreshed": refreshed,
        "skipped_stf": skipped_stf,
        "events_created": events_created,
        "errors": errors,
        "remaining_due": remaining,
        "requeued": requeued,
        "outcomes": outcomes,
    }
