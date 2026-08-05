"""Bootstrap histórico — baseline sem flood de novidades."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_monitoramentos
from monitor_jus.db.models import BootstrapState, Criterion, CriterionLink
from monitor_jus.db.repository import Repository
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


def _upsert_simple(
    session: Session,
    *,
    ctype: str,
    value: str,
    label: str | None = None,
    meta: dict | None = None,
) -> bool:
    existing = session.scalar(
        select(Criterion).where(Criterion.criterion_type == ctype, Criterion.value == value)
    )
    if existing:
        existing.active = True
        if label:
            existing.label = label
        if meta is not None:
            existing.meta = meta
        return False
    session.add(
        Criterion(
            id=str(uuid4()),
            criterion_type=ctype,
            value=value,
            label=label,
            meta=meta,
            active=True,
        )
    )
    return True


def _sync_oab_criterion(
    session: Session,
    *,
    numero: str,
    sec: str,
    label: str | None,
    meta: dict[str, Any],
) -> dict[str, str]:
    """
    Garante critério OAB exato UF:numero[+sufixo].
    Não converte RJ-2556A em RJ-2556 — sufixos distintos são identidades distintas.
    """
    value = f"{sec}:{numero}"
    existing = session.scalar(
        select(Criterion).where(Criterion.criterion_type == "OAB", Criterion.value == value)
    )
    if existing:
        existing.active = True
        if label:
            existing.label = label
        existing.meta = meta
        return {"action": "unchanged", "value": value, "deactivated": "0"}

    session.add(
        Criterion(
            id=str(uuid4()),
            criterion_type="OAB",
            value=value,
            label=label,
            meta=meta,
            active=True,
        )
    )
    session.flush()
    return {"action": "created", "value": value, "deactivated": "0"}


def sync_criteria_from_config(session: Session, settings: Settings | None = None) -> int:
    """Compat: retorna só contagem de alterações (int)."""
    return int(sync_criteria_detailed(session, settings)["changes"])


def sync_criteria_detailed(
    session: Session, settings: Settings | None = None
) -> dict[str, Any]:
    """Carrega critérios do YAML (OAB com sufixo tipado; nomes com meta)."""
    settings = settings or get_settings()
    cfg = load_monitoramentos(settings)
    mon = cfg.get("monitoramentos") or {}
    yaml_path = str(settings.monitoramentos_path)
    changes = 0
    oab_actions: list[dict[str, str]] = []
    yaml_oabs: list[str] = []

    for oab in mon.get("oabs") or []:
        if oab.get("ativo") is False:
            continue
        numero = normalize_oab_numero(str(oab.get("numero", "")))
        sec = str(oab.get("seccional", "")).upper()
        sufixo = oab.get("sufixo")
        if sufixo:
            numero = normalize_oab_numero(f"{numero}{sufixo}")
        # sufixo: null explícito — não acrescentar letra
        if not validate_oab(numero, sec):
            continue
        yaml_oabs.append(f"{sec}:{numero}")
        result = _sync_oab_criterion(
            session,
            numero=numero,
            sec=sec,
            label=oab.get("responsavel"),
            meta={
                "seccional": sec,
                "numero": numero,
                "sufixo": sufixo,
                "canonical": f"{sec}-{only_digits(numero)}",
            },
        )
        oab_actions.append(result)
        if result.get("action") in {"created", "updated", "merged"}:
            changes += 1

    for item in mon.get("cpfs") or []:
        cpf = only_digits(str(item.get("cpf", "")))
        if validate_cpf(cpf) and _upsert_simple(
            session, ctype="CPF", value=cpf, label=item.get("nome")
        ):
            changes += 1

    for nome in mon.get("nomes") or []:
        if isinstance(nome, dict):
            if nome.get("ativo") is False:
                continue
            text = str(nome.get("nome", "")).strip()
            meta = {
                "requires_secondary_evidence": bool(
                    nome.get("requires_secondary_evidence", True)
                )
            }
        else:
            text = str(nome).strip()
            meta = {"requires_secondary_evidence": True}
        if text and _upsert_simple(
            session, ctype="NOME", value=text, label=text, meta=meta
        ):
            changes += 1

    for proc in mon.get("processos") or []:
        parts = normalize_cnj(str(proc))
        if parts and _upsert_simple(
            session,
            ctype="PROCESSO",
            value=parts.numero_digits,
            label=parts.numero_formatado,
        ):
            changes += 1

    for emp in mon.get("empresas") or []:
        cnpj = only_digits(str(emp.get("cnpj", "")))
        if cnpj and _upsert_simple(
            session,
            ctype="CNPJ",
            value=cnpj,
            label=emp.get("nome"),
            meta={"nome": emp.get("nome"), "aliases": emp.get("aliases") or []},
        ):
            changes += 1

    session.flush()
    logger.info(
        "criteria_synced",
        extra={
            "extra": {
                "yaml_path": yaml_path,
                "yaml_oabs": yaml_oabs,
                "changes": changes,
                "oab_actions": oab_actions,
            }
        },
    )
    return {
        "changes": changes,
        "yaml_path": yaml_path,
        "yaml_oabs": yaml_oabs,
        "oab_actions": oab_actions,
    }
