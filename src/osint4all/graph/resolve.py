"""Upsert de entidades, arestas e evidências + merge por identificador forte."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.connectors.base import ConnectorResult, FoundEntity
from osint4all.db.models import Edge, Entity, Evidence, Identifier, Investigation
from osint4all.db.repository import add_identifier, blocked_key_set, enqueue_expand, find_entity_by_key, utcnow
from osint4all.graph.identity import found_canonical_key, should_enqueue_child
from osint4all.identifiers import STRONG_ID_KINDS, canonical_key


def upsert_found_entity(
    session: Session,
    investigation: Investigation,
    found: FoundEntity,
    *,
    depth: int,
    is_seed: bool = False,
) -> Entity:
    key = found_canonical_key(found)
    existing = find_entity_by_key(session, investigation.id, key)
    if existing:
        existing.last_seen_at = utcnow()
        existing.confidence = max(existing.confidence, found.confidence)
        if depth < (existing.depth or 0):
            existing.depth = depth
        if found.display_name and (
            existing.display_name == existing.canonical_key or len(found.display_name) > len(existing.display_name)
        ):
            existing.display_name = found.display_name
        attrs = dict(existing.attrs or {})
        attrs.update({k: v for k, v in found.attrs.items() if v not in (None, "")})
        attrs["grau"] = existing.depth
        existing.attrs = attrs
        add_identifier(existing, found.kind, found.value, key)
        _merge_same_as(session, investigation, existing, found)
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
) -> list[Entity]:
    created: list[Entity] = []
    ref_map: dict[str, Entity] = {origin.canonical_key: origin}
    blocked = blocked_key_set(session, investigation.id)

    for found in result.entities:
        key = found_canonical_key(found)
        if key in blocked or canonical_key(found.kind, found.value) in blocked:
            continue
        entity = upsert_found_entity(session, investigation, found, depth=depth + 1)
        ref_map[found_canonical_key(found)] = entity
        ref_map[canonical_key(found.kind, found.value)] = entity
        created.append(entity)
        if (
            enqueue_children
            and depth + 1 < investigation.max_depth
            and entity.id != origin.id
            and should_enqueue_child(found, entity)
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
        target = origin
        if ev.entity_ref:
            target = ref_map.get(ev.entity_ref) or find_entity_by_key(
                session, investigation.id, ev.entity_ref
            ) or origin
        _add_evidence(session, investigation, target, connector, ev.source_label, ev.url, ev.snippet, ev.payload)

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
        existing.attrs = merged
        return existing
    edge = Edge(
        investigation_id=investigation.id,
        from_entity_id=from_id,
        to_entity_id=to_id,
        rel_type=rel_type,
        confidence=confidence,
        attrs=attrs or {},
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
) -> Evidence | None:
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
        connector=connector,
        source_label=source_label,
        url=url,
        snippet=snippet,
        payload=payload,
        dedup_hash=digest,
    )
    session.add(ev)
    return ev
