"""Criação de investigação a partir de sementes."""

from __future__ import annotations

from osint4all.connectors.base import FoundEntity
from osint4all.connectors.plate_public import parse_plate_enrichment
from osint4all.db.models import Entity, Investigation
from osint4all.db.repository import add_identifier, create_manual_edge, enqueue_expand, find_entity_by_key
from osint4all.graph.identity import MAX_GRAPH_DEPTH
from osint4all.graph.resolve import apply_result, upsert_found_entity
from osint4all.identifiers import ParsedSeed, canonical_key, normalize_birth, parse_seed
from sqlalchemy import select
from sqlalchemy.orm import Session


def add_seed_entities(
    session: Session,
    inv: Investigation,
    seeds: list[ParsedSeed],
    *,
    max_attempts: int = 3,
    force: bool = False,
    enqueue: bool = True,
) -> list[Entity]:
    created: list[Entity] = []
    attach_kinds = {"CPF", "EMAIL", "PHONE", "USERNAME", "BIRTHDATE"}
    person: Entity | None = None
    ordered = sorted(seeds, key=lambda item: 0 if item.kind == "NAME" else 1 if item.kind == "CPF" else 2)
    for seed in ordered:
        if seed.kind == "BIRTHDATE" and person is None:
            continue
        if seed.kind in attach_kinds and person is not None:
            add_identifier(person, seed.kind, seed.value, seed.canonical_key)
            if seed.kind == "CPF" and not str(person.canonical_key or "").startswith("cpf:"):
                person.canonical_key = seed.canonical_key
            attrs = dict(person.attrs or {})
            if seed.kind == "USERNAME":
                attrs["username"] = seed.display_name
            if seed.kind == "BIRTHDATE":
                attrs["nascimento"] = seed.display_name
            person.attrs = attrs
            if enqueue:
                enqueue_expand(
                    session,
                    investigation=inv,
                    entity=person,
                    depth=0,
                    max_attempts=max_attempts,
                    force=True,
                )
            continue
        if seed.kind == "BIRTHDATE":
            continue
        found = FoundEntity(
            entity_type=seed.entity_type,
            kind=seed.kind,
            value=seed.value,
            display_name=seed.display_name,
            attrs={"seed": True},
            confidence=0.99 if seed.kind in {"CPF", "CNPJ", "CNJ"} else 0.7,
        )
        entity = upsert_found_entity(session, inv, found, depth=0, is_seed=True)
        if enqueue:
            enqueue_expand(
                session,
                investigation=inv,
                entity=entity,
                depth=0,
                max_attempts=max_attempts,
                force=force,
            )
        created.append(entity)
        if seed.kind in {"NAME", "CPF"} and entity.entity_type == "PERSON":
            person = entity
    from osint4all.db.repository import consolidate_identities

    consolidate_identities(session, inv.id)
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


def attach_person_profile(
    session: Session,
    inv: Investigation,
    *,
    birth: str = "",
    father: str = "",
    mother: str = "",
    name: str = "",
    cpf: str = "",
) -> Entity | None:
    """Grava nascimento e filiação no alvo e liga pai/mãe no grafo."""
    person = None
    for raw, kind in ((cpf, "CPF"), (name, "NAME")):
        seed = parse_seed(raw, forced_kind=kind)
        if seed:
            person = find_entity_by_key(session, inv.id, seed.canonical_key)
        if person:
            break
    if not person:
        person = session.scalar(
            select(Entity).where(
                Entity.investigation_id == inv.id,
                Entity.entity_type == "PERSON",
                Entity.is_seed.is_(True),
            )
        )
    if not person:
        return None
    attrs = dict(person.attrs or {})
    stamp = normalize_birth(birth)
    if stamp:
        attrs["nascimento"] = stamp
        add_identifier(person, "BIRTHDATE", stamp, canonical_key("BIRTHDATE", stamp))
    if father.strip():
        attrs["nome_pai"] = father.strip()
    if mother.strip():
        attrs["nome_mae"] = mother.strip()
    person.attrs = attrs
    for raw, kind, rel, note in (
        (father, "FATHER", "PAI", "nome do pai"),
        (mother, "MOTHER", "MAE", "nome da mãe"),
    ):
        parent = parse_seed(raw, forced_kind=kind)
        if not parent:
            continue
        other = find_entity_by_key(session, inv.id, parent.canonical_key)
        if not other:
            continue
        create_manual_edge(session, inv, from_id=person.id, to_id=other.id, rel_type=rel, note=note)
    return person


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
    enqueue: bool = True,
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
    add_seed_entities(session, inv, seeds, max_attempts=max_attempts, enqueue=enqueue)
    attach_person_profile(
        session,
        inv,
        birth=next((s.value for s in seeds if s.kind == "BIRTHDATE"), ""),
        father=next((s.value for s in seeds if s.kind == "FATHER"), ""),
        mother=next((s.value for s in seeds if s.kind == "MOTHER"), ""),
        name=next((s.value for s in seeds if s.kind == "NAME"), ""),
        cpf=next((s.value for s in seeds if s.kind == "CPF"), ""),
    )
    from osint4all.engines.investigation import ensure_primary_hypothesis
    from osint4all.engines.playbooks import attach_playbook

    kinds = {seed.kind for seed in seeds}
    if inv.playbook_key in {"COMPANY", "PERSON", "CASE", "DOMAIN"}:
        key = inv.playbook_key
    elif "CNJ" in kinds:
        key = "CASE"
    elif "CNPJ" in kinds:
        key = "COMPANY"
    elif "URL" in kinds and not ({"CPF", "NAME", "EMAIL", "PHONE"} & kinds):
        key = "DOMAIN"
    else:
        key = "PERSON"
    attach_playbook(session, inv, key)
    ensure_primary_hypothesis(session, inv)
    return inv
