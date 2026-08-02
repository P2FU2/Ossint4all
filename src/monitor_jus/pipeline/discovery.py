"""Descoberta de processos via Judit (OAB/CPF/CNPJ/nome)."""

from __future__ import annotations

from datetime import datetime
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


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _lawsuit_fields(full: dict[str, Any], page_item: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extrai capa/status de resposta Judit (lawsuit ou response_data)."""
    data = full or {}
    if page_item and isinstance(page_item.get("response_data"), dict):
        data = {**page_item["response_data"], **data}
    elif page_item and not data:
        data = page_item

    tribunal = (
        data.get("tribunal_acronym")
        or data.get("tribunal")
        or data.get("court")
    )
    if isinstance(tribunal, dict):
        tribunal = tribunal.get("name") or tribunal.get("acronym")

    last_step = data.get("last_step") if isinstance(data.get("last_step"), dict) else {}
    situacao = (
        data.get("status")
        or data.get("phase")
        or data.get("situacao")
        or last_step.get("content")
    )
    return {
        "tribunal": str(tribunal) if tribunal else None,
        "classe": _first_name(data.get("classifications") or data.get("classe")),
        "assunto": _first_name(data.get("subjects") or data.get("assunto")),
        "orgao_julgador": data.get("county") or data.get("orgao_julgador"),
        "grau": (str(data.get("instance") or data.get("grau") or "")[:64] or None),
        "situacao": str(situacao) if situacao else None,
        "data_distribuicao": _parse_dt(data.get("distribution_date") or data.get("data_distribuicao")),
        "last_movement_at": _parse_dt(last_step.get("step_date") or last_step.get("date")),
        "payload": data if data else None,
    }


def _first_name(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            name = first.get("name") or first.get("nome")
            return str(name) if name else None
        return str(first)
    return None


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
            page_items: list[dict[str, Any]] = []
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
                resp = {"page_data": [{"response_data": {"code": parts.numero_formatado}}]}
            else:
                continue

            if isinstance(resp, dict):
                raw_pages = resp.get("page_data") or []
                if isinstance(raw_pages, list):
                    page_items = [p for p in raw_pages if isinstance(p, dict)]

            cnjs = _extract_cnjs_from_judit_response(resp if isinstance(resp, dict) else {})
            # mapa cnj -> item de página para enriquecer capa
            cnj_item: dict[str, dict[str, Any]] = {}
            for item in page_items:
                for cnj in _extract_cnjs_from_judit_response(item):
                    cnj_item[cnj] = item

            for cnj in cnjs:
                parts = normalize_cnj(cnj)
                if not parts:
                    continue
                full: dict[str, Any] = {}
                try:
                    full = lawsuits.get_full_process(parts.numero_digits) or {}
                except SourceOutcomeError as exc:
                    outcomes.append({"criterion": crit.value, "code": exc.code, "msg": exc.message})

                proc_kwargs: dict[str, Any] = {
                    **_lawsuit_fields(full if isinstance(full, dict) else {}, cnj_item.get(cnj)),
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
                                    "classe": norm.get("classe") or proc_kwargs.get("classe"),
                                    "assunto": norm.get("assunto") or proc_kwargs.get("assunto"),
                                    "orgao_julgador": norm.get("orgao_julgador")
                                    or proc_kwargs.get("orgao_julgador"),
                                    "grau": norm.get("grau") or proc_kwargs.get("grau"),
                                }
                            )
                    except SourceOutcomeError as exc:
                        outcomes.append({"source": "datajud", "code": exc.code, "msg": exc.message})

                proc = repo.upsert_process(parts.numero_formatado, parts.numero_digits, **proc_kwargs)
                repo.link_criterion_process(crit.id, proc.id)
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
