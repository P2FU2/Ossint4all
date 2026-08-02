"""Descoberta de processos via Judit (OAB/CPF/CNPJ/nome)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import Criterion
from monitor_jus.db.repository import Repository
from monitor_jus.exceptions import SourceOutcomeError
from monitor_jus.logging_setup import get_logger
from monitor_jus.pipeline.normalize import normalize_datajud_source
from monitor_jus.sources.datajud import DataJudClient
from monitor_jus.sources.judit.lawsuits import JuditLawsuitsService
from monitor_jus.sources.judit.requests import JuditRequestsService
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)


def _extract_cnjs_from_judit_response(data: dict[str, Any]) -> list[str]:
    found: list[str] = []
    stack: list[Any] = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in ("code", "cnj", "numero_cnj", "numeroProcesso", "lawsuit_cnj") and v:
                    parts = normalize_cnj(str(v))
                    if parts:
                        found.append(parts.numero_formatado)
                else:
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return list(dict.fromkeys(found))


def run_discovery(
    session: Session,
    *,
    settings: Settings | None = None,
    bootstrap_mode: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    requests_svc = JuditRequestsService(settings=settings)
    lawsuits = JuditLawsuitsService()
    datajud = DataJudClient(settings)

    outcomes: list[dict[str, Any]] = []
    discovered = 0
    criteria = list(session.scalars(select(Criterion).where(Criterion.active.is_(True))).all())

    for crit in criteria:
        try:
            if crit.criterion_type == "OAB":
                sec, numero = crit.value.split(":", 1)
                resp = requests_svc.search_by_oab(numero, sec)
            elif crit.criterion_type == "CPF":
                resp = requests_svc.search_by_document(crit.value, "cpf")
            elif crit.criterion_type == "CNPJ":
                resp = requests_svc.search_by_document(crit.value, "cnpj")
            elif crit.criterion_type == "NOME":
                resp = requests_svc.search_by_name(crit.value)
            elif crit.criterion_type == "PROCESSO":
                parts = normalize_cnj(crit.value)
                if not parts:
                    continue
                resp = {"data": {"code": parts.numero_formatado}}
            else:
                continue

            cnjs = _extract_cnjs_from_judit_response(resp if isinstance(resp, dict) else {})
            for cnj in cnjs:
                parts = normalize_cnj(cnj)
                if not parts:
                    continue
                full = {}
                try:
                    full = lawsuits.get_full_process(parts.numero_digits)
                except SourceOutcomeError as exc:
                    outcomes.append({"criterion": crit.value, "code": exc.code, "msg": exc.message})

                proc_kwargs: dict[str, Any] = {
                    "tribunal": (full or {}).get("tribunal") or (full or {}).get("court"),
                    "baseline": bootstrap_mode,
                }
                # confirmação DataJud seletiva
                if datajud.should_confirm("processo_descoberto"):
                    try:
                        dj = datajud.search_by_cnj(parts.numero_formatado)
                        if dj:
                            norm = normalize_datajud_source(dj)
                            proc_kwargs.update(
                                {
                                    "tribunal": norm.get("tribunal") or proc_kwargs.get("tribunal"),
                                    "classe": norm.get("classe"),
                                    "assunto": norm.get("assunto"),
                                    "orgao_julgador": norm.get("orgao_julgador"),
                                    "grau": norm.get("grau"),
                                }
                            )
                    except SourceOutcomeError as exc:
                        outcomes.append({"source": "datajud", "code": exc.code, "msg": exc.message})

                repo.upsert_process(parts.numero_formatado, parts.numero_digits, **proc_kwargs)
                discovered += 1
            outcomes.append({"criterion": crit.value, "status": "ok", "cnjs": len(cnjs)})
        except SourceOutcomeError as exc:
            outcomes.append(
                {
                    "criterion": crit.value,
                    "code": exc.code,
                    "msg": exc.message,
                    "kind": "skip" if exc.code.startswith("SKIPPED") else "fail",
                }
            )
            logger.warning("discovery_outcome", extra={"extra": {"code": exc.code, "c": crit.value}})

    return {"discovered": discovered, "outcomes": outcomes, "bootstrap": bootstrap_mode}
