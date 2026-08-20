"""Criação de investigação a partir de sementes."""

from __future__ import annotations

from osint4all.connectors.base import FoundEntity
from osint4all.connectors.plate_public import parse_plate_enrichment
from osint4all.db.models import Entity, Investigation
from osint4all.db.repository import enqueue_expand, find_entity_by_key
from osint4all.graph.identity import MAX_GRAPH_DEPTH
from osint4all.graph.resolve import apply_result, upsert_found_entity
from osint4all.identifiers import ParsedSeed, parse_seed
from sqlalchemy.orm import Session


def add_seed_entities(
    session: Session,
    inv: Investigation,
    seeds: list[ParsedSeed],
    *,
    max_attempts: int = 3,
    force: bool = False,
) -> list[Entity]:
    created: list[Entity] = []
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
        enqueue_expand(
            session,
            investigation=inv,
            entity=entity,
            depth=0,
            max_attempts=max_attempts,
            force=force,
        )
        created.append(entity)
    return created


def attach_plate_owner(
    session: Session,
    inv: Investigation,
    *,
    plate: str,
    owner_name: str = "",
    owner_cpf: str = "",
    max_attempts: int = 3,
) -> Entity | None:
    plate_seed = parse_seed(plate, forced_kind="PLATE")
    if not plate_seed:
        return None
    extras: list[ParsedSeed] = []
    if owner_cpf:
        cpf_seed = parse_seed(owner_cpf, forced_kind="CPF")
        if cpf_seed:
            extras.append(cpf_seed)
    if owner_name:
        name_seed = parse_seed(owner_name, forced_kind="NAME")
        if name_seed:
            extras.append(name_seed)
    if extras:
        add_seed_entities(session, inv, extras, max_attempts=max_attempts)
    plate_entity = find_entity_by_key(session, inv.id, plate_seed.canonical_key)
    if not plate_entity:
        created = add_seed_entities(session, inv, [plate_seed], max_attempts=max_attempts)
        plate_entity = created[0] if created else None
    if not plate_entity:
        return None
    attrs = dict(plate_entity.attrs or {})
    if owner_name:
        attrs["owner_name"] = owner_name.strip()
    if owner_cpf:
        attrs["owner_cpf"] = owner_cpf.strip()
    plate_entity.attrs = attrs
    result = parse_plate_enrichment(
        plate_seed.value,
        origin_key=plate_seed.canonical_key,
        owner_name=owner_name,
        owner_cpf=owner_cpf,
    )
    apply_result(
        session,
        inv,
        plate_entity,
        result,
        connector="plate_public",
        depth=0,
        enqueue_children=True,
        max_attempts=max_attempts,
    )
    return plate_entity


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
        max_depth=max(0, min(max_depth, MAX_GRAPH_DEPTH)),
        connectors=connectors,
        monitor=monitor,
        created_by=created_by,
    )
    session.add(inv)
    session.flush()
    add_seed_entities(session, inv, seeds, max_attempts=max_attempts)
    from osint4all.engines.investigation import ensure_primary_hypothesis
    from osint4all.engines.playbooks import attach_playbook

    kinds = {seed.kind for seed in seeds}
    if inv.playbook_key in {"COMPANY", "PERSON"}:
        key = inv.playbook_key
    elif "CNPJ" in kinds:
        key = "COMPANY"
    else:
        key = "PERSON"
    attach_playbook(session, inv, key)
    ensure_primary_hypothesis(session, inv)
    return inv
