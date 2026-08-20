"""Discovery engine: query log, plugins, custo, extração de documento."""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.catalog.sources import SOURCE_CATALOG
from osint4all.config import get_settings
from osint4all.connectors.registry import build_connectors, enabled_connector_names
from osint4all.db.models import Investigation, QueryLog
from osint4all.db.repository import utcnow
from osint4all.engines.verification import add_negative

_CNPJ = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\b")
_MONEY = re.compile(r"R\$\s?[\d\.]+,\d{2}")
_PAID = {"datajud", "transparencia", "shodan_public", "censys_public", "aleph_public"}


def connector_version(connector: Any) -> str:
    return str(getattr(connector, "version", None) or getattr(connector, "name", "1"))


def log_query(
    session: Session,
    investigation: Investigation,
    *,
    connector: str,
    entity_id: str | None,
    params: dict[str, Any],
    result_count: int,
    latency_ms: int,
    version: str = "1",
    failed: bool = False,
) -> QueryLog:
    empty = result_count == 0 and not failed
    row = QueryLog(
        investigation_id=investigation.id,
        entity_id=entity_id,
        connector=connector,
        params=params or {},
        connector_version=version[:32],
        result_count=max(result_count, 0),
        empty=empty,
        latency_ms=latency_ms,
        created_at=utcnow(),
    )
    session.add(row)
    if empty and not failed:
        add_negative(
            session,
            investigation,
            connector=connector,
            query=str((params or {}).get("key") or connector),
            entity_id=entity_id,
        )
    return row


def record_connector_run(session: Session, investigation: Investigation, connector: Any, entity: Any, result: Any) -> QueryLog:
    started = time.perf_counter()
    count = len(getattr(result, "entities", []) or []) + len(getattr(result, "evidence", []) or [])
    latency = int((time.perf_counter() - started) * 1000)
    return log_query(
        session,
        investigation,
        connector=getattr(connector, "name", "unknown"),
        entity_id=getattr(entity, "id", None),
        params={"key": getattr(entity, "canonical_key", ""), "type": getattr(entity, "entity_type", "")},
        result_count=count,
        latency_ms=max(latency, 1),
        version=connector_version(connector),
    )


def capability_registry(settings=None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    enabled = set(enabled_connector_names(settings))
    rows = []
    for connector in build_connectors(settings):
        meta = SOURCE_CATALOG.get(connector.name, {})
        paid = connector.name in _PAID
        rows.append(
            {
                "id": connector.name,
                "label": meta.get("label") or connector.name,
                "accepts": meta.get("accepts") or "",
                "supports": ["SEARCH"],
                "requires": meta.get("key") or None,
                "cost": "PAID" if paid else "FREE",
                "mode": "PASSIVE",
                "enabled": connector.name in enabled,
            }
        )
    return rows


def route_connectors(needed: set[str] | None = None) -> list[str]:
    """Prefere fonte gratuita; só sobe para paga se a gratuita não cobre o tipo."""
    free, paid = [], []
    for row in capability_registry():
        if not row["enabled"]:
            continue
        if needed and not any(token.lower() in (row["accepts"] or "").lower() for token in needed):
            continue
        (paid if row["cost"] == "PAID" else free).append(row["id"])
    return free + paid


def extract_document_facts(text: str) -> dict[str, list[str]]:
    blob = text or ""
    return {
        "cnpj": list(dict.fromkeys(_CNPJ.findall(blob)))[:12],
        "emails": list(dict.fromkeys(m.group(0) for m in _EMAIL.finditer(blob)))[:12],
        "dates": list(dict.fromkeys(_DATE.findall(blob)))[:16],
        "values": list(dict.fromkeys(_MONEY.findall(blob)))[:12],
    }


def extract_pdf_text(data: bytes) -> str:
    """Texto embutido no PDF, sem OCR e sem varrer a web."""
    if not data.startswith(b"%PDF"):
        try:
            return data.decode("utf-8", errors="ignore")[:80_000]
        except Exception:
            return ""
    chunks: list[str] = []
    for match in re.finditer(rb"\((?:\\.|[^\\)]){4,200}\)", data[: 400 * 1024]):
        raw = match.group(0)[1:-1].decode("latin-1", errors="ignore")
        text = raw.replace("\\n", " ").replace("\\r", " ").strip()
        if any(c.isalpha() for c in text):
            chunks.append(text)
    return " ".join(chunks)[:80_000]


def recent_queries(session: Session, investigation_id: str, *, limit: int = 20) -> list[QueryLog]:
    return list(
        session.scalars(
            select(QueryLog)
            .where(QueryLog.investigation_id == investigation_id)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        ).all()
    )
