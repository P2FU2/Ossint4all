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
# Fatia do lote normal dedicada a capas incompletas (além dos due)
INCOMPLETE_SLICE = 15


def _refresh_meta(proc: Any) -> dict[str, Any]:
    payload = proc.payload if isinstance(proc.payload, dict) else {}
    meta = payload.get("_refresh")
    return dict(meta) if isinstance(meta, dict) else {}


def _failure_streak(proc: Any) -> int:
    try:
        return max(0, int(_refresh_meta(proc).get("failure_streak") or 0))
    except (TypeError, ValueError):
        return 0


def _set_failure_streak(proc: Any, streak: int) -> None:
    payload = dict(proc.payload) if isinstance(proc.payload, dict) else {}
    meta = dict(payload.get("_refresh") or {}) if isinstance(payload.get("_refresh"), dict) else {}
    if streak <= 0:
        meta.pop("failure_streak", None)
    else:
        meta["failure_streak"] = int(streak)
    if meta:
        payload["_refresh"] = meta
    elif "_refresh" in payload:
        payload.pop("_refresh", None)
    proc.payload = payload or None


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
    """True só quando há mudança material real (não baseline da 1ª leitura DataJud)."""
    if current == ("", "", "", "", ""):
        return False
    # Primeira observação: grava capa/estado, não vira novidade no digest
    if previous == ("", "", "", "", ""):
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


def _parse_occurred_at(norm: dict[str, Any]) -> datetime | None:
    raw = norm.get("last_movement_at") or norm.get("last_movement_date")
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _maybe_create_movement_event(
    session: Session,
    repo: Repository,
    proc: Any,
    norm: dict[str, Any],
    *,
    suppress_notify: bool = False,
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
    link_res = resolve_official_link_result(
        proc.numero_cnj,
        tribunal=proc.tribunal,
        payload={
            "datajud": norm.get("raw"),
            "instances": norm.get("instances"),
            "has_second_degree": norm.get("has_second_degree"),
        },
        existing=proc.official_link,
        classe=proc.classe or norm.get("classe"),
        grau=proc.grau if not norm.get("has_second_degree") else "G2",
    )
    link = link_res.url or proc.official_link
    if link_res.url and link_res.link_type not in {"UNAVAILABLE", "COURT_HOMEPAGE"}:
        proc.official_link = link_res.url
        proc.official_link_type = link_res.link_type
    notify = (
        NotifyStatus.IGNORED.value
        if suppress_notify
        else NotifyStatus.PENDING_NOTIFY.value
    )
    _event, created = repo.create_event_if_absent(
        event_identity_key=identity,
        payload_hash=payload_hash,
        event_type=EventType.MOVIMENTACAO_PROCESSUAL.value,
        notify_status=notify,
        source_name="datajud",
        source_event_id=None,
        numero_cnj=proc.numero_cnj,
        tribunal=proc.tribunal,
        title=title,
        description=description,
        priority="media",
        tipo_movimentacao=str(norm.get("last_movement_name") or "")[:64] or None,
        official_link=link,
        occurred_at=_parse_occurred_at(norm),
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
    suppress_notify: bool = False,
    update_progress_totals: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    datajud = DataJudClient(settings)
    freq_cfg = load_yaml(settings.config_path("check_frequency.yaml"))

    label = "CAPA_INCOMPLETA" if only_incomplete else "PROCESS_REFRESH"
    drain_incomplete = bool(only_incomplete and force_all_incomplete)
    max_batches = 40 if drain_incomplete else 1

    refreshed = 0
    skipped_stf = 0
    events_created = 0
    errors = 0
    outcomes: list[dict[str, Any]] = []
    due_total = 0
    batches_done = 0
    processed_global = 0

    def _prog(*, done: float | None, total: float | None, message: str, force: bool = False) -> None:
        if update_progress_totals:
            report_progress(
                stage="tracking",
                done=done,
                total=total,
                message=message,
                force=force,
            )
        else:
            # Nested sob Bootstrap: só mensagem (não sobrescreve done/total do pai)
            report_progress(stage="tracking", message=message, force=force)

    for _batch in range(max_batches):
        if only_incomplete:
            # due_only: erros/backoff não reprocessam o mesmo CNJ no mesmo drain
            due = repo.processes_incomplete_capa(limit=batch_size, due_only=True)
        else:
            # Mistura capas incompletas due no refresh normal (não só no Bootstrap)
            capa_n = min(INCOMPLETE_SLICE, max(0, batch_size // 3))
            incomplete = (
                repo.processes_incomplete_capa(limit=capa_n, due_only=True)
                if capa_n
                else []
            )
            due_main = repo.processes_due(limit=max(1, batch_size - len(incomplete)))
            seen: set[str] = set()
            due = []
            for proc in [*incomplete, *due_main]:
                if proc.id in seen:
                    continue
                seen.add(proc.id)
                due.append(proc)
        if not due:
            break
        due_total += len(due)
        batches_done += 1
        n_due = max(len(due), 1)
        if batches_done == 1:
            _prog(
                done=0,
                total=n_due,
                message=(
                    f"{label} · drenando capas ({len(due)}+)"
                    if drain_incomplete
                    else f"{label} · {len(due)} processo(s)"
                ),
                force=True,
            )

        for idx, proc in enumerate(due):
            done_n = processed_global + idx
            total_n = max(due_total, done_n + 1) if drain_incomplete else n_due
            _prog(
                done=done_n,
                total=total_n,
                message=f"Atualizando {proc.numero_cnj}",
                force=True,
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
                _prog(
                    done=done_n + 1,
                    total=total_n,
                    message=f"Atualizando {proc.numero_cnj}",
                )
                continue

            if route.source != "DATAJUD" or not route.datajud_alias:
                proc.requires_reconciliation = True
                proc.next_check_at = _next_check(proc.situacao, proc.last_movement_at, freq_cfg)
                outcomes.append({"cnj": proc.numero_cnj, "route": route.source, "skipped": True})
                _prog(
                    done=done_n + 1,
                    total=total_n,
                    message=f"Atualizando {proc.numero_cnj}",
                )
                continue

            try:
                hits = datajud.search_all_by_cnj(proc.numero_cnj, alias=route.datajud_alias)
                had_material = False
                if hits:
                    # 1ª leitura DataJud = baseline (mesmo com orgao/data vindos do DJEN).
                    # Só conta observação DataJud prévia — não capa DJEN sozinha.
                    payload = proc.payload if isinstance(proc.payload, dict) else {}
                    dj_prev = (
                        payload.get("datajud")
                        if isinstance(payload.get("datajud"), dict)
                        else {}
                    )
                    had_prior_datajud = bool(
                        proc.datajud_fingerprint
                        or proc.datajud_last_success_at
                        or dj_prev.get("last_movement_code")
                        or dj_prev.get("last_movement_name")
                    )
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
                    _set_failure_streak(proc, 0)
                    if had_prior_datajud and material_movement_changed(previous, current):
                        if _maybe_create_movement_event(
                            session,
                            repo,
                            proc,
                            norm,
                            suppress_notify=suppress_notify,
                        ):
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
                streak = _failure_streak(proc) + 1
                _set_failure_streak(proc, streak)
                proc.next_check_at = _next_check(
                    proc.situacao,
                    proc.last_movement_at,
                    freq_cfg,
                    failure_streak=streak,
                    rate_limited=True,
                )
                outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "error": str(exc)})
            except SourceOutcomeError as exc:
                errors += 1
                streak = _failure_streak(proc) + 1
                _set_failure_streak(proc, streak)
                proc.next_check_at = _next_check(
                    proc.situacao,
                    proc.last_movement_at,
                    freq_cfg,
                    failure_streak=streak,
                )
                outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "error": str(exc)})
            _prog(
                done=done_n + 1,
                total=total_n,
                message=f"Atualizando {proc.numero_cnj}",
            )

        processed_global += len(due)
        session.flush()
        if not drain_incomplete:
            break
        # Evita loop infinito se capas não saem de incomplete (erro persistente)
        if len(due) < batch_size:
            more = repo.processes_incomplete_capa(limit=1, due_only=True)
            if not more:
                break

    remaining = 0 if only_incomplete else repo.count_due_processes()
    requeued = False
    if remaining > 0 and not only_incomplete:
        # Continuidade: key por job pai; se a anterior já terminou, gera chave nova
        from monitor_jus.models import JobStatus

        cont_key = f"refresh-cont:{parent_job_id or uuid4().hex[:12]}"
        run = repo.create_run(
            RunType.PROCESS_REFRESH.value,
            trigger_type="schedule",
            run_mode=RunMode.LIVE.value,
            idempotency_key=f"run:{cont_key}:{uuid4().hex[:8]}",
        )
        job = repo.enqueue_job(
            run.id,
            JobType.PROCESS_REFRESH.value,
            payload={"continuation": True, "parent_job_id": parent_job_id},
            max_attempts=settings.job_max_attempts,
            idempotency_key=cont_key,
        )
        terminal = {
            JobStatus.SUCCESS.value,
            JobStatus.DEAD.value,
            JobStatus.CANCELLED.value,
        }
        if job and job.status in terminal:
            cont_key = f"refresh-cont:{parent_job_id or 'x'}:{uuid4().hex[:8]}"
            job = repo.enqueue_job(
                run.id,
                JobType.PROCESS_REFRESH.value,
                payload={"continuation": True, "parent_job_id": parent_job_id},
                max_attempts=settings.job_max_attempts,
                idempotency_key=cont_key,
            )
        active = {
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
            JobStatus.RETRY.value,
        }
        requeued = bool(job and job.status in active)

    _prog(
        done=float(processed_global or 1),
        total=float(processed_global or 1),
        message=f"{label} concluído",
        force=True,
    )
    return {
        "due": due_total,
        "batches": batches_done,
        "refreshed": refreshed,
        "skipped_stf": skipped_stf,
        "events_created": events_created,
        "errors": errors,
        "remaining_due": remaining,
        "requeued": requeued,
        "outcomes": outcomes,
    }
