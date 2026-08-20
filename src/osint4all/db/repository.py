"""Helpers de persistência do grafo."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from osint4all.db.models import Edge, Entity, Evidence, ExpansionJob, Identifier, Investigation
from osint4all.graph.identity import entity_status
from osint4all.identifiers import STRONG_ID_KINDS


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_investigation(session: Session, investigation_id: str) -> Investigation | None:
    return session.get(Investigation, investigation_id)


def find_entity_by_key(session: Session, investigation_id: str, canonical_key: str) -> Entity | None:
    return session.scalar(
        select(Entity).where(
            Entity.investigation_id == investigation_id,
            Entity.canonical_key == canonical_key,
        )
    )


def enqueue_expand(
    session: Session,
    *,
    investigation: Investigation,
    entity: Entity,
    depth: int,
    max_attempts: int = 3,
) -> ExpansionJob | None:
    existing = session.scalar(
        select(ExpansionJob).where(
            ExpansionJob.investigation_id == investigation.id,
            ExpansionJob.entity_id == entity.id,
            ExpansionJob.job_type == "EXPAND",
            ExpansionJob.status.in_(("PENDING", "RUNNING")),
        )
    )
    if existing:
        return existing
    done = session.scalar(
        select(ExpansionJob).where(
            ExpansionJob.investigation_id == investigation.id,
            ExpansionJob.entity_id == entity.id,
            ExpansionJob.job_type == "EXPAND",
            ExpansionJob.status == "DONE",
        )
    )
    if done:
        return None
    job = ExpansionJob(
        investigation_id=investigation.id,
        entity_id=entity.id,
        depth=depth,
        max_attempts=max_attempts,
    )
    session.add(job)
    return job


def claim_next_job(session: Session, *, investigation_id: str | None = None) -> ExpansionJob | None:
    stmt = select(ExpansionJob).where(ExpansionJob.status == "PENDING").order_by(ExpansionJob.created_at)
    if investigation_id:
        stmt = stmt.where(ExpansionJob.investigation_id == investigation_id)
    job = session.scalars(stmt.limit(1)).first()
    if not job:
        return None
    job.status = "RUNNING"
    job.started_at = utcnow()
    job.attempt_count = (job.attempt_count or 0) + 1
    session.flush()
    return job


def job_counts(session: Session, investigation_id: str) -> dict[str, int]:
    rows = session.execute(
        select(ExpansionJob.status, ExpansionJob.id).where(
            ExpansionJob.investigation_id == investigation_id
        )
    ).all()
    counts = {"PENDING": 0, "RUNNING": 0, "DONE": 0, "FAILED": 0, "TOTAL": len(rows)}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts


def add_identifier(entity: Entity, kind: str, value: str, canonical_key: str) -> Identifier:
    for existing in entity.identifiers:
        if existing.canonical_key == canonical_key:
            return existing
    ident = Identifier(
        entity_id=entity.id,
        kind=kind,
        value=value,
        canonical_key=canonical_key,
        strong=kind in STRONG_ID_KINDS,
    )
    entity.identifiers.append(ident)
    return ident


def graph_payload(session: Session, investigation_id: str) -> dict[str, Any]:
    entities = session.scalars(
        select(Entity).where(Entity.investigation_id == investigation_id)
    ).all()
    edges = session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)).all()
    nodes = [
        {
            "id": e.id,
            "label": e.display_name,
            "type": e.entity_type,
            "seed": e.is_seed,
            "depth": e.depth,
            "confidence": e.confidence,
            "key": e.canonical_key,
            "status": entity_status(e),
            "attrs": {
                k: e.attrs.get(k)
                for k in (
                    "razao_social",
                    "situacao",
                    "municipio",
                    "uf",
                    "cnae",
                    "simples",
                    "mei",
                    "lat",
                    "lng",
                    "cep",
                    "endereco",
                    "capital_social",
                    "porte",
                )
                if e.attrs and e.attrs.get(k) not in (None, "", [])
            },
        }
        for e in entities
    ]
    links = [
        {
            "id": edge.id,
            "source": edge.from_entity_id,
            "target": edge.to_entity_id,
            "type": edge.rel_type,
            "confidence": edge.confidence,
        }
        for edge in edges
    ]
    return {"nodes": nodes, "edges": links, "entity_count": len(nodes), "edge_count": len(links)}


def detach_entity(session: Session, investigation_id: str, entity_id: str) -> bool:
    entity = session.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not entity:
        return False
    session.execute(delete(ExpansionJob).where(ExpansionJob.entity_id == entity_id))
    session.execute(
        delete(Edge).where(or_(Edge.from_entity_id == entity_id, Edge.to_entity_id == entity_id))
    )
    session.execute(delete(Evidence).where(Evidence.entity_id == entity_id))
    session.execute(delete(Identifier).where(Identifier.entity_id == entity_id))
    session.delete(entity)
    session.flush()
    return True


def confirm_entity(session: Session, entity: Entity, *, reason: str) -> Entity:
    attrs = dict(entity.attrs or {})
    attrs["status"] = "confirmed"
    attrs["motivo"] = reason
    entity.attrs = attrs
    entity.confidence = max(entity.confidence, 0.85)
    return entity
