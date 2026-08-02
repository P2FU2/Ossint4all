"""Atualização de processos conhecidos (Judit + DataJud seletivo)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_yaml
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.pipeline.normalize import normalize_datajud_source
from monitor_jus.progress import report as report_progress
from monitor_jus.sources.datajud import DataJudClient
from monitor_jus.sources.judit.lawsuits import JuditLawsuitsService

logger = get_logger(__name__)


def _next_check(situacao: str | None, last_movement_at: datetime | None, cfg: dict) -> datetime:
    now = datetime.now(timezone.utc)
    days = int((cfg or {}).get("default_days") or 1)
    situ = (situacao or "").lower()
    if any(x in situ for x in ("arquiv", "baix")):
        days = 7
    elif last_movement_at:
        idle = (now - last_movement_at).days
        if idle >= 90:
            days = 7
    return now + timedelta(days=days)


def run_tracking(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    lawsuits = JuditLawsuitsService()
    datajud = DataJudClient(settings)
    freq_cfg = load_yaml(settings.config_path("check_frequency.yaml"))

    due = repo.processes_due()
    refreshed = 0
    outcomes: list[dict[str, Any]] = []
    n_due = max(len(due), 1)
    report_progress(
        stage="tracking",
        done=0,
        total=n_due,
        message=f"Tracking · {len(due)} processo(s) devido(s)",
        force=True,
    )

    for idx, proc in enumerate(due):
        report_progress(
            stage="tracking",
            done=idx,
            total=n_due,
            message=f"Atualizando {proc.numero_cnj} ({idx + 1}/{len(due)})",
        )
        try:
            full = lawsuits.get_full_process(proc.numero_cnj_digits)
            if full:
                proc.payload = full
                refreshed += 1
            if datajud.should_confirm("dados_incompletos_judit") and (
                not proc.classe or not proc.assunto
            ):
                try:
                    dj = datajud.search_by_cnj(proc.numero_cnj)
                    if dj:
                        norm = normalize_datajud_source(dj)
                        proc.classe = proc.classe or norm.get("classe")
                        proc.assunto = proc.assunto or norm.get("assunto")
                        proc.orgao_julgador = proc.orgao_julgador or norm.get("orgao_julgador")
                        proc.grau = proc.grau or norm.get("grau")
                        proc.tribunal = proc.tribunal or norm.get("tribunal")
                except SourceOutcomeError as exc:
                    outcomes.append({"cnj": proc.numero_cnj, "code": exc.code})
            now = datetime.now(timezone.utc)
            proc.last_checked_at = now
            proc.next_check_at = _next_check(proc.situacao, proc.last_movement_at, freq_cfg)
        except SourceOutcomeError as exc:
            outcomes.append({"cnj": proc.numero_cnj, "code": exc.code, "msg": exc.message})
            # em falha Judit, tenta DataJud se política permitir
            if datajud.should_confirm("falha_judit"):
                try:
                    dj = datajud.search_by_cnj(proc.numero_cnj)
                    if dj:
                        norm = normalize_datajud_source(dj)
                        proc.classe = norm.get("classe") or proc.classe
                        proc.assunto = norm.get("assunto") or proc.assunto
                        refreshed += 1
                except SourceOutcomeError:
                    pass
            proc.last_checked_at = datetime.now(timezone.utc)
            proc.next_check_at = datetime.now(timezone.utc) + timedelta(days=1)
        report_progress(
            stage="tracking",
            done=idx + 1,
            total=n_due,
            message=f"OK {proc.numero_cnj} · refreshed {refreshed}",
        )

    session.flush()
    report_progress(
        stage="tracking",
        done=n_due,
        total=n_due,
        message=f"Tracking concluído · {refreshed}/{len(due)}",
        force=True,
    )
    return {"due": len(due), "refreshed": refreshed, "outcomes": outcomes}
