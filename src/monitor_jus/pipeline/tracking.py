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
from monitor_jus.pipeline.normalize import normalize_datajud_hits
from monitor_jus.progress import report as report_progress
from monitor_jus.sources.datajud import DataJudClient
from monitor_jus.sources.datajud_router import resolve_process_source
from monitor_jus.validators import normalize_cnj

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
    if any(x in situ for x in ("arquiv", "baix", "julgad")):
        return now + timedelta(days=21)

    if last_movement_at:
        idle = (now - last_movement_at).days
        if idle >= 30:
            return now + timedelta(days=5)

    default_hours = int(cfg.get("default_hours") or 24)
    return now + timedelta(hours=default_hours)


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
        proc.datajud_last_movement_at = norm["last_movement_at"]
        if not proc.last_movement_at or norm["last_movement_at"] > proc.last_movement_at:
            proc.last_movement_at = norm["last_movement_at"]

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
        },
        "official_link": link.url,
        "official_link_type": link.link_type,
        "cnj_digits": cnj.numero_digits if cnj else proc.numero_cnj_digits,
    }


def run_tracking(
    session: Session,
    settings: Settings | None = None,
    *,
    only_incomplete: bool = False,
    force_all_incomplete: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    datajud = DataJudClient(settings)
    freq_cfg = load_yaml(settings.config_path("check_frequency.yaml"))

    if only_incomplete:
        due = repo.processes_incomplete_capa(limit=800)
        label = "CAPA_INCOMPLETA"
    else:
        due = repo.processes_due()
        label = "PROCESS_REFRESH"
    # force_all_incomplete: ignore next_check_at (já filtrado por incompletos)
    _ = force_all_incomplete
    refreshed = 0
    skipped_stf = 0
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
            if hits:
                norm = normalize_datajud_hits(hits)
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
            proc.last_checked_at = now
            proc.next_check_at = _next_check(proc.situacao, proc.last_movement_at, freq_cfg)
            outcomes.append(
                {
                    "cnj": proc.numero_cnj,
                    "route": route.source,
                    "ok": True,
                    "hits": len(hits),
                    "grau": getattr(proc, "grau", None),
                    "situacao": proc.situacao,
                }
            )
        except SourceOutcomeError as exc:
            proc.next_check_at = _next_check(
                proc.situacao,
                proc.last_movement_at,
                freq_cfg,
                failure_streak=1,
            )
            outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "error": str(exc)})
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
