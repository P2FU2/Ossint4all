"""Criação de investigação a partir de sementes."""

from __future__ import annotations

from osint4all.connectors.base import FoundEntity
from osint4all.db.models import Investigation
from osint4all.db.repository import enqueue_expand
from osint4all.graph.resolve import upsert_found_entity
from osint4all.identifiers import ParsedSeed
from sqlalchemy.orm import Session


def create_investigation(
    session: Session,
    *,
    title: str,
    hypothesis: str | None,
    seeds: list[ParsedSeed],
    connectors: list[str],
    max_depth: int,
    monitor: bool,
    created_by: str | None,
    max_attempts: int = 3,
) -> Investigation:
    inv = Investigation(
        title=title.strip() or "Investigação sem título",
        hypothesis=(hypothesis or "").strip() or None,
        max_depth=max(0, min(max_depth, 4)),
        connectors=connectors,
        monitor=monitor,
        created_by=created_by,
    )
    session.add(inv)
    session.flush()
    for seed in seeds:
        found = FoundEntity(
            entity_type=seed.entity_type,
            kind=seed.kind,
            value=seed.value,
            display_name=seed.display_name,
            attrs={"seed": True},
            confidence=0.99 if seed.kind in {"CPF", "CNPJ", "CNJ"} else 0.7,
        )
        entity = upsert_found_entity(session, inv, found, depth=0, is_seed=True)
        enqueue_expand(session, investigation=inv, entity=entity, depth=0, max_attempts=max_attempts)
    return inv
