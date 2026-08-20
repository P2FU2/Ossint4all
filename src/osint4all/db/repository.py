"""Helpers de persistência do grafo."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from osint4all.db.models import BlockedKey, CaseNote, Edge, Entity, Evidence, ExpansionJob, Identifier, Investigation
from osint4all.graph.identity import entity_status, has_expandable_anchor
from osint4all.identifiers import STRONG_ID_KINDS

EDGE_REL_TYPES = (
    "SOCIO",
    "ADMIN",
    "MENCAO",
    "ANOTACAO",
    "RELACIONADO",
    "PROPRIETARIO",
    "CANDIDATO",
    "SAME_AS",
    "PARTE",
)


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
    force: bool = False,
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
    if done and not force:
        return None
    job = ExpansionJob(
        investigation_id=investigation.id,
        entity_id=entity.id,
        depth=depth,
        max_attempts=max_attempts,
    )
    session.add(job)
    return job


def enqueue_qsa_network(session: Session, investigation: Investigation, *, max_attempts: int = 3) -> int:
    """Enfileira CNPJ/CPF do caso para puxar o QSA oficial até o último nível."""
    investigation.max_depth = max(investigation.max_depth or 0, 4)
    queued = 0
    entities = session.scalars(select(Entity).where(Entity.investigation_id == investigation.id)).all()
    for entity in entities:
        if not has_expandable_anchor(entity):
            continue
        force = entity.entity_type == "ORG" or entity.canonical_key.startswith(("cnpj:", "cpf:"))
        job = enqueue_expand(
            session,
            investigation=investigation,
            entity=entity,
            depth=entity.depth,
            max_attempts=max_attempts,
            force=force,
        )
        if job:
            queued += 1
    return queued


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
                    "nota",
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
            "note": (edge.attrs or {}).get("nota") or "",
            "source_connector": edge.source_connector or "",
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
    block_key(session, investigation_id, entity.canonical_key)
    session.execute(delete(ExpansionJob).where(ExpansionJob.entity_id == entity_id))
    session.execute(
        delete(Edge).where(
            Edge.investigation_id == investigation_id,
            or_(Edge.from_entity_id == entity_id, Edge.to_entity_id == entity_id),
        )
    )
    session.execute(delete(Evidence).where(Evidence.entity_id == entity_id))
    session.execute(delete(CaseNote).where(CaseNote.entity_id == entity_id))
    session.delete(entity)
    session.flush()
    return True


def blocked_key_set(session: Session, investigation_id: str) -> set[str]:
    rows = session.scalars(select(BlockedKey.canonical_key).where(BlockedKey.investigation_id == investigation_id)).all()
    return {str(key) for key in rows}


def block_key(session: Session, investigation_id: str, canonical_key: str) -> BlockedKey | None:
    key = (canonical_key or "").strip()
    if not key:
        return None
    existing = session.scalar(
        select(BlockedKey).where(BlockedKey.investigation_id == investigation_id, BlockedKey.canonical_key == key)
    )
    if existing:
        return existing
    row = BlockedKey(investigation_id=investigation_id, canonical_key=key)
    session.add(row)
    return row


def delete_edge(session: Session, investigation_id: str, edge_id: str) -> bool:
    edge = session.scalar(select(Edge).where(Edge.id == edge_id, Edge.investigation_id == investigation_id))
    if not edge:
        return False
    session.execute(delete(Evidence).where(Evidence.edge_id == edge_id))
    session.delete(edge)
    session.flush()
    return True


def update_edge(
    session: Session,
    investigation_id: str,
    edge_id: str,
    *,
    rel_type: str,
    note: str = "",
) -> Edge | None:
    edge = session.scalar(select(Edge).where(Edge.id == edge_id, Edge.investigation_id == investigation_id))
    if not edge:
        return None
    kind = (rel_type or edge.rel_type or "RELACIONADO").strip().upper()[:32]
    clash = session.scalar(
        select(Edge).where(
            Edge.investigation_id == investigation_id,
            Edge.from_entity_id == edge.from_entity_id,
            Edge.to_entity_id == edge.to_entity_id,
            Edge.rel_type == kind,
            Edge.id != edge.id,
        )
    )
    if clash:
        return clash
    edge.rel_type = kind
    attrs = dict(edge.attrs or {})
    if note.strip():
        attrs["nota"] = note.strip()[:2000]
    else:
        attrs.pop("nota", None)
    edge.attrs = attrs
    session.flush()
    return edge


def create_manual_edge(
    session: Session,
    investigation: Investigation,
    *,
    from_id: str,
    to_id: str,
    rel_type: str,
    note: str = "",
) -> Edge | None:
    if from_id == to_id:
        return None
    src = session.scalar(select(Entity).where(Entity.id == from_id, Entity.investigation_id == investigation.id))
    dst = session.scalar(select(Entity).where(Entity.id == to_id, Entity.investigation_id == investigation.id))
    if not src or not dst:
        return None
    kind = (rel_type or "RELACIONADO").strip().upper()[:32]
    existing = session.scalar(
        select(Edge).where(
            Edge.investigation_id == investigation.id,
            Edge.from_entity_id == from_id,
            Edge.to_entity_id == to_id,
            Edge.rel_type == kind,
        )
    )
    if existing:
        if note.strip():
            attrs = dict(existing.attrs or {})
            attrs["nota"] = note.strip()[:2000]
            existing.attrs = attrs
        return existing
    edge = Edge(
        investigation_id=investigation.id,
        from_entity_id=from_id,
        to_entity_id=to_id,
        rel_type=kind,
        confidence=0.99,
        attrs={"nota": note.strip()[:2000]} if note.strip() else {},
        source_connector="manual",
    )
    session.add(edge)
    session.flush()
    return edge


def list_notes(session: Session, investigation_id: str) -> list[CaseNote]:
    return list(
        session.scalars(
            select(CaseNote).where(CaseNote.investigation_id == investigation_id).order_by(CaseNote.created_at)
        ).all()
    )


def add_case_note(
    session: Session,
    investigation: Investigation,
    *,
    title: str,
    body: str,
    entity_id: str | None = None,
    parent_id: str | None = None,
    created_by: str | None = None,
    on_graph: bool = False,
) -> CaseNote:
    note = CaseNote(
        investigation_id=investigation.id,
        entity_id=entity_id or None,
        parent_id=parent_id or None,
        title=(title or "Anotação").strip()[:255] or "Anotação",
        body=(body or "").strip()[:8000],
        created_by=created_by,
    )
    session.add(note)
    session.flush()
    if on_graph:
        key = f"note:{note.id}"
        node = Entity(
            investigation_id=investigation.id,
            entity_type="NOTE",
            canonical_key=key,
            display_name=note.title,
            attrs={"nota": note.body, "status": "confirmed"},
            confidence=0.99,
            is_seed=False,
            depth=0,
        )
        session.add(node)
        session.flush()
        note.entity_id = node.id
        if entity_id:
            create_manual_edge(
                session,
                investigation,
                from_id=node.id,
                to_id=entity_id,
                rel_type="ANOTACAO",
                note=note.body,
            )
    return note


def delete_case_note(session: Session, investigation_id: str, note_id: str) -> bool:
    note = session.scalar(select(CaseNote).where(CaseNote.id == note_id, CaseNote.investigation_id == investigation_id))
    if not note:
        return False
    children = session.scalars(select(CaseNote).where(CaseNote.parent_id == note.id)).all()
    for child in children:
        child.parent_id = note.parent_id
    session.delete(note)
    session.flush()
    return True


def note_tree(notes: list[CaseNote]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[CaseNote]] = {}
    for note in notes:
        by_parent.setdefault(note.parent_id, []).append(note)

    def walk(parent: str | None) -> list[dict[str, Any]]:
        rows = []
        for note in by_parent.get(parent, []):
            rows.append({"note": note, "children": walk(note.id)})
        return rows

    return walk(None)


def confirm_entity(session: Session, entity: Entity, *, reason: str) -> Entity:
    attrs = dict(entity.attrs or {})
    attrs["status"] = "confirmed"
    attrs["motivo"] = reason
    entity.attrs = attrs
    entity.confidence = max(entity.confidence, 0.85)
    return entity
