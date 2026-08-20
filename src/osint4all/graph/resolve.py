"""Upsert de entidades, arestas e evidências + merge por identificador forte."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.connectors.base import ConnectorResult, FoundEntity
from osint4all.db.models import Edge, Entity, Evidence, Identifier, Investigation
from osint4all.db.repository import (
    add_identifier,
    blocked_key_set,
    case_target_profile,
    consolidate_identities,
    enqueue_expand,
    find_entity_by_key,
    find_person_by_name,
    utcnow,
)
from osint4all.graph.identity import bind_found_to_profile, found_canonical_key, is_unconfirmed, should_enqueue_child
from osint4all.identifiers import STRONG_ID_KINDS, canonical_key


def upsert_found_entity(
    session: Session,
    investigation: Investigation,
    found: FoundEntity,
    *,
    depth: int,
    is_seed: bool = False,
    fill_only: bool = False,
) -> Entity:
    key = found_canonical_key(found)
    existing = find_entity_by_key(session, investigation.id, key)
    if existing is None and found.entity_type == "PERSON" and found.kind == "NAME" and not is_unconfirmed(found):
        existing = find_person_by_name(session, investigation.id, found.display_name or found.value)
    if existing is None and found.kind in {"CPF", "EMAIL", "PHONE", "USERNAME", "BIRTHDATE"}:
        host = find_person_by_name(session, investigation.id, found.display_name or "")
        if host is None:
            host = session.scalar(
                select(Entity).where(
                    Entity.investigation_id == investigation.id,
                    Entity.entity_type == "PERSON",
                    Entity.is_seed.is_(True),
                )
            )
        if host is not None:
            ident_key = canonical_key(found.kind, found.value)
            add_identifier(host, found.kind, found.value, ident_key)
            if found.kind == "CPF" and not str(host.canonical_key or "").startswith("cpf:"):
                host.canonical_key = ident_key
            attrs = dict(host.attrs or {})
            if found.kind == "USERNAME":
                attrs["username"] = found.display_name or found.value
            host.attrs = attrs
            return host
    if existing:
        old_name = existing.display_name
        existing.last_seen_at = utcnow()
        existing.confidence = max(existing.confidence, found.confidence)
        if depth < (existing.depth or 0):
            existing.depth = depth
        if found.display_name and not fill_only and (
            existing.display_name == existing.canonical_key or len(found.display_name) > len(existing.display_name)
        ):
            existing.display_name = found.display_name
        prev_attrs = dict(existing.attrs or {})
        attrs = dict(prev_attrs)
        incoming = {k: v for k, v in found.attrs.items() if v not in (None, "")}
        if fill_only:
            attrs.update({k: v for k, v in incoming.items() if not prev_attrs.get(k)})
        else:
            attrs.update(incoming)
        attrs["grau"] = existing.depth
        existing.attrs = attrs
        add_identifier(existing, found.kind, found.value, key)
        _merge_same_as(session, investigation, existing, found)
        if old_name != existing.display_name:
            from osint4all.engines.knowledge import record_version
            from osint4all.quality.changes import record_change

            record_change(
                session,
                investigation,
                field="display_name",
                old_value=old_name,
                new_value=existing.display_name,
                entity_id=existing.id,
            )
            record_version(session, investigation, existing, "display_name", old_name, existing.display_name)
        for field in ("papel", "endereco", "cargo", "situacao"):
            old = str(prev_attrs.get(field) or "")
            new = str(attrs.get(field) or "")
            if old and new and old != new:
                from osint4all.engines.knowledge import record_version

                record_version(session, investigation, existing, field, old, new)
        return existing

    attrs = dict(found.attrs or {})
    attrs["grau"] = depth
    entity = Entity(
        investigation_id=investigation.id,
        entity_type=found.entity_type,
        canonical_key=key,
        display_name=found.display_name or found.value,
        attrs=attrs,
        confidence=found.confidence,
        is_seed=is_seed,
        depth=depth,
    )
    session.add(entity)
    session.flush()
    add_identifier(entity, found.kind, found.value, key)
    _merge_same_as(session, investigation, entity, found)
    from osint4all.quality.changes import record_change

    record_change(
        session,
        investigation,
        field="entity",
        old_value="",
        new_value=entity.display_name,
        entity_id=entity.id,
    )
    return entity


def _merge_same_as(
    session: Session,
    investigation: Investigation,
    entity: Entity,
    found: FoundEntity,
) -> None:
    """Se um identificador forte já existe em outro nó, liga SAME_AS."""
    if found.kind not in STRONG_ID_KINDS:
        return
    key = canonical_key(found.kind, found.value)
    others = session.scalars(
        select(Identifier).where(
            Identifier.canonical_key == key,
            Identifier.entity_id != entity.id,
        )
    ).all()
    for ident in others:
        other = session.get(Entity, ident.entity_id)
        if not other or other.investigation_id != investigation.id:
            continue
        _ensure_edge(
            session,
            investigation,
            entity.id,
            other.id,
            "SAME_AS",
            0.99,
            {"reason": found.kind},
            "resolve",
        )


def apply_result(
    session: Session,
    investigation: Investigation,
    origin: Entity,
    result: ConnectorResult,
    *,
    connector: str,
    depth: int,
    enqueue_children: bool,
    max_attempts: int,
    fill_only: bool = False,
    consolidate: bool = True,
) -> list[Entity]:
    created: list[Entity] = []
    ref_map: dict[str, Entity] = {origin.canonical_key: origin}
    blocked = blocked_key_set(session, investigation.id)
    profile = case_target_profile(session, investigation.id)
    target = None
    if profile.cpf:
        target = find_entity_by_key(session, investigation.id, canonical_key("CPF", profile.cpf))
    if target is None and profile.name:
        target = find_person_by_name(session, investigation.id, profile.name)

    for found in result.entities:
        key = found_canonical_key(found)
        if key in blocked or canonical_key(found.kind, found.value) in blocked:
            continue
        action = bind_found_to_profile(found, profile)
        if action == "skip":
            continue
        if action == "remap" and target is not None:
            ref_map[key] = target
            ref_map[canonical_key(found.kind, found.value)] = target
            if found.kind in {"CPF", "EMAIL", "PHONE", "USERNAME", "BIRTHDATE"}:
                add_identifier(target, found.kind, found.value, canonical_key(found.kind, found.value))
            continue
        entity = upsert_found_entity(session, investigation, found, depth=depth + 1, fill_only=fill_only)
        ref_map[found_canonical_key(found)] = entity
        ref_map[canonical_key(found.kind, found.value)] = entity
        created.append(entity)
        if (
            enqueue_children
            and depth + 1 < investigation.max_depth
            and entity.id != origin.id
            and should_enqueue_child(found, entity, profile)
        ):
            enqueue_expand(
                session,
                investigation=investigation,
                entity=entity,
                depth=depth + 1,
                max_attempts=max_attempts,
            )

    for edge in result.edges:
        src = ref_map.get(edge.from_ref)
        dst = ref_map.get(edge.to_ref)
        if src is None:
            src = find_entity_by_key(session, investigation.id, edge.from_ref)
        if dst is None:
            dst = find_entity_by_key(session, investigation.id, edge.to_ref)
        if not src or not dst:
            continue
        if (
            edge.rel_type == "MENCAO"
            and src.entity_type == "PERSON"
            and dst.entity_type == "ORG"
        ):
            continue
        attrs = dict(edge.attrs or {})
        hop = max(int(src.depth or 0), int(dst.depth or 0))
        if src.is_seed or dst.is_seed:
            hop = 1
        attrs["grau"] = hop
        _ensure_edge(
            session,
            investigation,
            src.id,
            dst.id,
            edge.rel_type,
            edge.confidence,
            attrs,
            connector,
        )

    for ev in result.evidence:
        ev_target = origin
        if ev.entity_ref:
            ev_target = ref_map.get(ev.entity_ref) or find_entity_by_key(
                session, investigation.id, ev.entity_ref
            ) or origin
        _add_evidence(
            session,
            investigation,
            ev_target,
            connector,
            ev.source_label,
            ev.url,
            ev.snippet,
            ev.payload,
            method=getattr(ev, "method", None) or "GET",
            http_status=getattr(ev, "http_status", None),
            raw_path=getattr(ev, "raw_path", None),
        )
        _index_host_payload(session, investigation, ev_target, connector, ev.payload)

    _annotate_identity(session, investigation, created)

    if consolidate:
        consolidate_identities(session, investigation.id)
    return created


def _ensure_edge(
    session: Session,
    investigation: Investigation,
    from_id: str,
    to_id: str,
    rel_type: str,
    confidence: float,
    attrs: dict[str, Any],
    connector: str,
) -> Edge:
    existing = session.scalar(
        select(Edge).where(
            Edge.investigation_id == investigation.id,
            Edge.from_entity_id == from_id,
            Edge.to_entity_id == to_id,
            Edge.rel_type == rel_type,
        )
    )
    if existing:
        existing.confidence = max(existing.confidence, confidence)
        merged = dict(existing.attrs or {})
        merged.update(attrs or {})
        from osint4all.engines.knowledge import strength_label

        merged.setdefault("strength", strength_label(existing.confidence))
        existing.attrs = merged
        return existing
    from osint4all.engines.knowledge import strength_label

    payload = dict(attrs or {})
    payload.setdefault("strength", strength_label(confidence))
    edge = Edge(
        investigation_id=investigation.id,
        from_entity_id=from_id,
        to_entity_id=to_id,
        rel_type=rel_type,
        confidence=confidence,
        attrs=payload,
        source_connector=connector,
    )
    session.add(edge)
    session.flush()
    return edge


def _add_evidence(
    session: Session,
    investigation: Investigation,
    entity: Entity,
    connector: str,
    source_label: str,
    url: str | None,
    snippet: str | None,
    payload: dict[str, Any] | None,
    *,
    method: str = "GET",
    http_status: int | None = None,
    raw_path: str | None = None,
    edge_id: str | None = None,
) -> Evidence | None:
    from osint4all.quality.provenance import content_hash
    from osint4all.quality.timeline import add_event

    extra = payload if isinstance(payload, dict) else {}
    method = str(extra.get("method") or method or "GET")[:16]
    if http_status is None and extra.get("http_status") is not None:
        try:
            http_status = int(extra.get("http_status"))
        except (TypeError, ValueError):
            http_status = None
    raw_path = str(extra.get("raw_path") or raw_path or "") or None
    raw = json.dumps(
        {"c": connector, "u": url or "", "s": (snippet or "")[:200], "e": entity.id},
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    existing = session.scalar(
        select(Evidence).where(
            Evidence.investigation_id == investigation.id,
            Evidence.dedup_hash == digest,
        )
    )
    if existing:
        return existing
    ev = Evidence(
        investigation_id=investigation.id,
        entity_id=entity.id,
        edge_id=edge_id,
        connector=connector,
        source_label=source_label,
        url=url,
        snippet=snippet,
        payload=payload,
        dedup_hash=digest,
        method=method,
        http_status=http_status,
        content_sha256=content_hash(payload, snippet, url),
        raw_path=raw_path,
    )
    session.add(ev)
    session.flush()
    add_event(
        session,
        investigation,
        event_type="evidence",
        title=source_label,
        meta=(snippet or connector)[:400],
        url=url,
        entity_id=entity.id,
        evidence_id=ev.id,
    )
    return ev


def _index_host_payload(
    session: Session,
    investigation: Investigation,
    entity: Entity,
    connector: str,
    payload: dict[str, Any] | None,
) -> None:
    if not payload:
        return
    from osint4all.intel.hosts import observation_from_payload, upsert_host_intel

    obs = observation_from_payload(payload, source=connector)
    if obs:
        upsert_host_intel(session, investigation, entity.id, obs)


def _person_snap(session: Session, investigation_id: str, entity: Entity):
    from osint4all.graph.identity import collapse_name
    from osint4all.graph.match import PersonSnap, infer_place, places_from_attrs
    from osint4all.security import only_digits

    attrs = dict(entity.attrs or {})
    emails: set[str] = set()
    phones: set[str] = set()
    users: set[str] = set()
    for ident in entity.identifiers or []:
        kind = str(ident.kind or "").upper()
        value = str(ident.value or "").strip()
        if kind == "EMAIL" and value:
            emails.add(value.lower())
        elif kind == "PHONE":
            digits = only_digits(value)
            if len(digits) >= 8:
                phones.add(digits)
        elif kind == "USERNAME" and value:
            users.add(value.lstrip("@").casefold())
    places = places_from_attrs(attrs)
    relatives = {collapse_name(attrs[k]) for k in ("nome_pai", "nome_mae") if attrs.get(k)}
    companies: set[str] = set()
    edges = session.scalars(
        select(Edge).where(
            Edge.investigation_id == investigation_id,
            (Edge.from_entity_id == entity.id) | (Edge.to_entity_id == entity.id),
        )
    ).all()
    other_ids = {e.from_entity_id if e.to_entity_id == entity.id else e.to_entity_id for e in edges}
    others = {
        row.id: row
        for row in session.scalars(select(Entity).where(Entity.id.in_(other_ids or {"_"}))).all()
    }
    for edge in edges:
        other = others.get(edge.to_entity_id if edge.from_entity_id == entity.id else edge.from_entity_id)
        if other is None:
            continue
        if other.entity_type == "ORG":
            companies.add(collapse_name(other.display_name))
            role = "processo" if edge.rel_type == "PARTE" else "empresa"
            place = infer_place(
                municipio=str((other.attrs or {}).get("municipio") or ""),
                uf=str((other.attrs or {}).get("uf") or ""),
                role=role,
                source=other.display_name,
                kind="associated",
            )
            if place is not None:
                places.append(place)
        elif other.entity_type == "PERSON" and edge.rel_type in {"PAI", "MAE"}:
            relatives.add(collapse_name(other.display_name))
    labels = [str(ev.source_label or "") for ev in (entity.evidence or []) if ev.source_label]
    return PersonSnap(
        name=entity.display_name or "",
        emails=emails,
        phones=phones,
        usernames=users,
        birth=str(attrs.get("nascimento") or attrs.get("birth") or ""),
        companies=companies,
        cargo=str(attrs.get("cargo") or attrs.get("papel") or ""),
        places=places,
        relatives=relatives,
        sources=labels,
        independent_origins=len({item for item in labels if item}),
    )


def _annotate_identity(session: Session, investigation: Investigation, created: list[Entity]) -> None:
    from osint4all.graph.match import apply_match_attrs, score_identity

    people = [row for row in created if row.entity_type == "PERSON"]
    if not people:
        return
    target = next((row for row in people if row.is_seed), None)
    if target is None:
        target = session.scalar(
            select(Entity).where(Entity.investigation_id == investigation.id, Entity.is_seed.is_(True), Entity.entity_type == "PERSON")
        )
    if target is None:
        return
    target_snap = _person_snap(session, investigation.id, target)
    apply_match_attrs(target, score_identity(target_snap, target_snap), target_snap.places)
    for person in people:
        if person.id == target.id:
            continue
        cand = _person_snap(session, investigation.id, person)
        apply_match_attrs(person, score_identity(target_snap, cand), cand.places)
