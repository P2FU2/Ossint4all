"""Bootstrap histórico — baseline sem flood de novidades."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_monitoramentos
from monitor_jus.db.models import BootstrapState
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.models import NotifyStatus
from monitor_jus.pipeline.discovery import run_discovery
from monitor_jus.progress import report as report_progress
from monitor_jus.security import only_digits
from monitor_jus.validators import normalize_cnj, normalize_oab_numero, validate_cpf, validate_oab

logger = get_logger(__name__)


def ensure_bootstrap_row(session: Session) -> BootstrapState:
    row = session.get(BootstrapState, 1)
    if not row:
        row = BootstrapState(id=1, completed=False, baseline_at=None)
        session.add(row)
        session.flush()
    return row


def run_bootstrap(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    state = ensure_bootstrap_row(session)
    first_run = not (state.completed and state.baseline_at)

    report_progress(
        stage="bootstrap",
        done=0,
        total=2,
        message="Bootstrap · discovery baseline",
        force=True,
    )
    # Sempre redescobre/atualiza o acervo; só na 1ª execução move o cursor do digest
    result = run_discovery(session, settings=settings, bootstrap_mode=True)
    report_progress(stage="bootstrap_finalize", done=1.5, total=2, message="Finalizando baseline")
    # Marca eventos criados no bootstrap como IGNORED (não vão para digest)
    from monitor_jus.db.models import Event
    from sqlalchemy import update

    session.execute(
        update(Event)
        .where(Event.notify_status == NotifyStatus.PENDING_NOTIFY.value)
        .values(notify_status=NotifyStatus.IGNORED.value)
    )

    now = datetime.now(timezone.utc)
    if first_run:
        state.baseline_at = now
        state.completed = True
        cursor = repo.get_digest_cursor()
        cursor.last_successful_digest_at = now
    session.flush()
    report_progress(
        stage="bootstrap",
        done=2,
        total=2,
        message="Bootstrap concluído",
        force=True,
    )
    logger.info("bootstrap_completed", extra={"extra": result})
    return {
        "status": "completed" if first_run else "refreshed",
        "baseline_at": (state.baseline_at or now).isoformat(),
        "discovery": result,
    }


def sync_criteria_from_config(session: Session, settings: Settings | None = None) -> int:
    """Carrega critérios do YAML para a tabela criteria."""
    from monitor_jus.db.models import Criterion
    from sqlalchemy import select
    from uuid import uuid4

    settings = settings or get_settings()
    cfg = load_monitoramentos(settings)
    mon = cfg.get("monitoramentos") or {}
    created = 0

    def upsert(ctype: str, value: str, label: str | None = None, meta: dict | None = None) -> None:
        nonlocal created
        existing = session.scalar(
            select(Criterion).where(Criterion.criterion_type == ctype, Criterion.value == value)
        )
        if existing:
            return
        session.add(
            Criterion(
                id=str(uuid4()),
                criterion_type=ctype,
                value=value,
                label=label,
                meta=meta,
            )
        )
        created += 1

    for oab in mon.get("oabs") or []:
        numero = normalize_oab_numero(str(oab.get("numero", "")))
        sec = str(oab.get("seccional", "")).upper()
        if validate_oab(numero, sec):
            upsert(
                "OAB",
                f"{sec}:{numero}",
                oab.get("responsavel"),
                {"seccional": sec, "numero": numero},
            )

    for item in mon.get("cpfs") or []:
        cpf = only_digits(str(item.get("cpf", "")))
        if validate_cpf(cpf):
            upsert("CPF", cpf, item.get("nome"))

    for nome in mon.get("nomes") or []:
        upsert("NOME", str(nome).strip(), str(nome).strip())

    for proc in mon.get("processos") or []:
        parts = normalize_cnj(str(proc))
        if parts:
            upsert("PROCESSO", parts.numero_digits, parts.numero_formatado)

    for emp in mon.get("empresas") or []:
        cnpj = only_digits(str(emp.get("cnpj", "")))
        if cnpj:
            upsert("CNPJ", cnpj, emp.get("nome"), {"nome": emp.get("nome")})

    session.flush()
    return created
