from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity
from osint4all.db.models import BlockedKey, CaseNote, Edge, Entity
from osint4all.db.repository import (
    add_case_note,
    blocked_key_set,
    create_manual_edge,
    delete_edge,
    detach_entity,
    update_edge,
)
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed
from sqlalchemy import select


def _case(db):
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    return create_investigation(
        db,
        title="Quadro",
        hypothesis="teste",
        seeds=[seed],
        connectors=[],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )


def test_detach_blocks_reexpansion(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
    found = FoundEntity(entity_type="ORG", kind="CNPJ", value="33000167000101", display_name="Empresa", confidence=0.8)
    created = apply_result(
        db,
        inv,
        person,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=person.canonical_key, to_ref="cnpj:33000167000101", rel_type="SOCIO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    db.flush()
    company = next((e for e in created if e.entity_type == "ORG"), None) or db.scalar(
        select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "ORG")
    )
    assert company is not None
    assert detach_entity(db, inv.id, company.id)
    assert "cnpj:33000167000101" in blocked_key_set(db, inv.id)
    apply_result(
        db,
        inv,
        person,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=person.canonical_key, to_ref="cnpj:33000167000101", rel_type="SOCIO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=False,
        max_attempts=3,
    )
    left = [e for e in db.scalars(select(Entity).where(Entity.investigation_id == inv.id)) if e.entity_type == "ORG"]
    assert left == []


def test_edge_edit_and_delete_keep_nodes(settings, db) -> None:
    inv = _case(db)
    other = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    db.add(other)
    db.flush()
    person = db.scalar(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON"))
    assert person is not None
    edge = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="SOCIO", note="QSA")
    assert edge
    updated = update_edge(db, inv.id, edge.id, rel_type="ADMIN", note="admin no QSA")
    assert updated and updated.rel_type == "ADMIN"
    assert updated.attrs.get("nota") == "admin no QSA"
    assert delete_edge(db, inv.id, edge.id)
    assert db.get(Entity, other.id) is not None
    assert db.scalars(select(Edge).where(Edge.investigation_id == inv.id)).all() == []


def test_case_note_tree_and_graph_node(settings, db) -> None:
    inv = _case(db)
    root = add_case_note(db, inv, title="Hipótese", body="mesmo grupo", created_by="tester")
    child = add_case_note(db, inv, title="Fonte", body="DOU", parent_id=root.id, created_by="tester")
    pinned = add_case_note(
        db,
        inv,
        title="Alerta",
        body="checar QSA",
        entity_id=inv.entities[0].id,
        on_graph=True,
        created_by="tester",
    )
    assert child.parent_id == root.id
    notes = db.scalars(select(CaseNote).where(CaseNote.investigation_id == inv.id)).all()
    assert len(notes) == 3
    note_nodes = [e for e in db.scalars(select(Entity).where(Entity.investigation_id == inv.id)) if e.entity_type == "NOTE"]
    assert len(note_nodes) == 1
    assert pinned.entity_id == note_nodes[0].id
    assert any(e.rel_type == "ANOTACAO" for e in db.scalars(select(Edge).where(Edge.investigation_id == inv.id)))
