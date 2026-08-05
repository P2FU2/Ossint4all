"""PROCESS_REFRESH — enriquecimento DataJud (não detecta novidade)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_yaml
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.official_portal import resolve_official_link_result
from monitor_jus.pipeline.normalize import normalize_datajud_source
from monitor_jus.progress import report as report_progress
from monitor_jus.sources.datajud import DataJudClient
from monitor_jus.sources.datajud_router import resolve_process_source

logger = get_logger(__name__)


def _next_check(
    situacao: str | None,
    last_movement_at: datetime | None,
    cfg: dict,
    *,
    had_new_publication: bool = False,
    failure_streak: int = 0,
) -> datetime:
    now = datetime.now(timezone.utc)
    if failure_streak > 0:
        backoff = (cfg.get("backoff") or {}).get("on_5xx_hours") or [1, 2, 4, 8, 16]
        hours = backoff[min(failure_streak - 1, len(backoff) - 1)]
        return now + timedelta(hours=int(hours))

    if had_new_publication:
        return now + timedelta(hours=2)

    situ = (situacao or "").lower()
    if any(x in situ for x in ("arquiv", "baix")):
        return now + timedelta(days=21)

    if last_movement_at:
        idle = (now - last_movement_at).days
        if idle >= 30:
            return now + timedelta(days=5)

    default_hours = int(cfg.get("default_hours") or 24)
    return now + timedelta(hours=default_hours)


def run_tracking(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    datajud = DataJudClient(settings)
    freq_cfg = load_yaml(settings.config_path("check_frequency.yaml"))

    due = repo.processes_due()
    refreshed = 0
    skipped_stf = 0
    outcomes: list[dict[str, Any]] = []
    n_due = max(len(due), 1)
    report_progress(
        stage="tracking",
        done=0,
        total=n_due,
        message=f"PROCESS_REFRESH · {len(due)} processo(s)",
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
            dj = datajud.search_by_cnj(proc.numero_cnj, alias=route.datajud_alias)
            if dj:
                norm = normalize_datajud_source(dj)
                proc.classe = proc.classe or norm.get("classe")
                proc.assunto = proc.assunto or norm.get("assunto")
                proc.orgao_julgador = proc.orgao_julgador or norm.get("orgao_julgador")
                proc.grau = proc.grau or norm.get("grau")
                proc.tribunal = proc.tribunal or norm.get("tribunal")
                fingerprint = hashlib.sha256(
                    json.dumps(dj, sort_keys=True, default=str).encode()
                ).hexdigest()[:64]
                proc.datajud_fingerprint = fingerprint
                proc.datajud_last_success_at = now
                if norm.get("last_movement_at"):
                    proc.datajud_last_movement_at = norm["last_movement_at"]
                    proc.last_movement_at = proc.last_movement_at or norm["last_movement_at"]
                link = resolve_official_link_result(
                    proc.numero_cnj, tribunal=proc.tribunal, payload=dj
                )
                proc.official_link = link.url or proc.official_link
                proc.official_link_type = link.link_type
                refreshed += 1
            proc.last_checked_at = now
            proc.next_check_at = _next_check(proc.situacao, proc.last_movement_at, freq_cfg)
            outcomes.append({"cnj": proc.numero_cnj, "route": route.source, "ok": True})
        except SourceOutcomeError as exc:
            proc.next_check_at = _next_check(
                proc.situacao,
                proc.last_movement_at,
                freq_cfg,
                failure_streak=1,
            )
            outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "error": str(exc)})
            # falha de um processo não interrompe os demais
            continue

    session.flush()
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
        "outcomes": outcomes,
    }
