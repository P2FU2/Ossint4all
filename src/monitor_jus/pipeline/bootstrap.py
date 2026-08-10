"""Bootstrap histórico — baseline sem flood de novidades + completa capas faltantes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings, load_monitoramentos
from monitor_jus.db.models import BootstrapState, Criterion
from monitor_jus.db.repository import Repository
from monitor_jus.logging_setup import get_logger
from monitor_jus.ops_config import load_ops
from monitor_jus.pipeline.discovery import run_discovery
from monitor_jus.pipeline.tracking import run_tracking
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


def _discovery_quality(result: dict[str, Any] | None) -> tuple[bool, str]:
    """Retorna (ok, aviso_amigável). ok só com 100% dos critérios ativos."""
    result = result or {}
    if result.get("status") == "skipped":
        reason = str(result.get("reason") or "desabilitado")
        if "djen" in reason.lower():
            return False, (
                "Diário da Justiça (DJEN) desabilitado — a leitura histórica não rodou."
            )
        return False, f"Discovery ignorada ({reason})."
    total = int(result.get("total_active_criteria") or 0)
    ok = int(result.get("successful_criteria") or 0)
    errors = result.get("errors") or []
    if total == 0:
        return False, "Nenhum critério ativo para buscar (sincronize o YAML)."
    if ok == 0:
        # típico: 403/auth em todos os critérios → Bootstrap “em segundos”
        return False, (
            "Não foi possível buscar no Diário da Justiça (DJEN). "
            "Acesso bloqueado ou fonte indisponível — tente mais tarde. "
            "Um Bootstrap bem-sucedido costuma levar vários minutos."
        )
    if ok < total:
        return False, (
            f"Varredura incompleta: só {ok} de {total} critérios ok"
            + (f" ({len(errors)} falha(s))." if errors else ".")
            + " Corrija a fonte e rode o Bootstrap de novo."
        )
    saturated = result.get("saturated_criteria") or []
    if saturated:
        return False, (
            f"Varredura truncada: {len(saturated)} critério(s) bateram no limite de páginas. "
            "Aumente max_pages no ops.yaml ou rode de novo — baseline não foi fechada."
        )
    return True, ""


def run_bootstrap(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    state = ensure_bootstrap_row(session)
    first_run = not (state.completed and state.baseline_at)
    ops = load_ops(settings)
    boot_cfg = ops.get("bootstrap") if isinstance(ops.get("bootstrap"), dict) else {}
    complete_capa = bool(boot_cfg.get("complete_missing_capa", True))
    ignore_events = bool(boot_cfg.get("ignore_events_for_digest", True))

    total_steps = 3 if complete_capa else 2
    report_progress(
        stage="bootstrap",
        done=0,
        total=total_steps,
        message="Bootstrap · busca histórica no Diário da Justiça (pode demorar)",
        force=True,
    )
    # Discovery longa (ops.yaml → bootstrap.lookback_days).
    # Eventos DJEN já nascem IGNORED quando bootstrap_mode=True (não limpar PENDING global).
    result = run_discovery(
        session,
        settings=settings,
        bootstrap_mode=ignore_events,
        mode="historical",
        purpose="bootstrap",
    )
    discovery_ok, discovery_note = _discovery_quality(result)
    report_progress(
        stage="bootstrap_finalize",
        done=1,
        total=total_steps,
        message=(
            discovery_note
            if not discovery_ok
            else "Etapa DJEN ok — preparando capas"
        ),
        force=True,
    )

    capa_result: dict[str, Any] | None = None
    # Capas só após DJEN ok — evita side-effects com bootstrap incompleto
    if complete_capa and discovery_ok:
        report_progress(
            stage="bootstrap_capa",
            done=2,
            total=total_steps,
            message="Completando capas faltantes (DataJud)",
            force=True,
        )
        capa_result = run_tracking(
            session,
            settings=settings,
            only_incomplete=True,
            force_all_incomplete=True,
            suppress_notify=ignore_events,
            update_progress_totals=False,
        )
    elif complete_capa and not discovery_ok:
        report_progress(
            stage="bootstrap_capa",
            done=2,
            total=total_steps,
            message="Capas ignoradas — DJEN não concluiu",
            force=True,
        )

    now = datetime.now(timezone.utc)
    # Só fecha a “leitura inicial” se o DJEN respondeu 100%
    if first_run and discovery_ok:
        state.baseline_at = now
        state.completed = True
        cursor = repo.get_digest_cursor()
        cursor.last_successful_digest_at = now
    session.flush()

    if discovery_ok:
        user_message = "Bootstrap concluído"
        status = "completed" if first_run else "refreshed"
        if capa_result is not None:
            user_message += (
                f" · capas: {int(capa_result.get('refreshed') or 0)} atualizada(s)"
            )
    else:
        user_message = f"Bootstrap incompleto — {discovery_note}"
        status = "incomplete"

    report_progress(
        stage="bootstrap",
        done=total_steps,
        total=total_steps,
        message=user_message[:512],
        force=True,
    )
    logger.info(
        "bootstrap_completed",
        extra={
            "extra": {
                "discovery": result,
                "capa": capa_result,
                "discovery_ok": discovery_ok,
                "status": status,
            }
        },
    )
    return {
        "status": status,
        "discovery_ok": discovery_ok,
        "user_message": user_message,
        "baseline_at": (state.baseline_at.isoformat() if state.baseline_at else None),
        "discovery": result,
        "capa_completion": capa_result,
        "ops": {
            "lookback_days": boot_cfg.get("lookback_days"),
            "complete_missing_capa": complete_capa,
        },
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
