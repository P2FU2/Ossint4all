from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity
from osint4all.db.models import BlockedKey, CaseNote, Edge, Entity, Evidence, ExpansionJob, Identifier, Investigation
from osint4all.db.repository import (
    add_case_note,
    case_identifiers,
    blocked_key_set,
    create_manual_edge,
    delete_case_note,
    delete_edge,
    detach_entity,
    graph_payload,
    purge_investigation,
    save_graph_layout,
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


def test_update_edge_rejects_type_clash(settings, db) -> None:
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
    first = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="SOCIO")
    second = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="ADMIN")
    assert first and second
    assert update_edge(db, inv.id, second.id, rel_type="SOCIO") is None
    db.refresh(second)
    assert second.rel_type == "ADMIN"


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
    note_id = pinned.id
    node_id = pinned.entity_id
    assert delete_case_note(db, inv.id, note_id)
    assert db.get(CaseNote, note_id) is None
    assert db.get(Entity, node_id) is None
    assert db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.rel_type == "ANOTACAO")).all() == []


def test_case_identifiers_lists_seeds(settings, db) -> None:
    inv = _case(db)
    rows = case_identifiers(db, inv.id)
    kinds = {item["kind"] for item in rows}
    assert "CPF" in kinds


def test_diagram_note_lands_on_graph(settings, db) -> None:
    inv = _case(db)
    note = add_case_note(
        db,
        inv,
        title="Fluxo QSA",
        body="alvo --> empresa",
        on_graph=True,
        kind="diagram",
        created_by="tester",
    )
    node = db.get(Entity, note.entity_id)
    assert node is not None
    assert node.entity_type == "NOTE"
    assert node.attrs.get("kind") == "diagram"
    assert node.display_name.startswith("Diagrama")


def test_purge_investigation_removes_children(settings, db) -> None:
    inv = _case(db)
    person = inv.entities[0]
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
    edge = create_manual_edge(db, inv, from_id=person.id, to_id=other.id, rel_type="SOCIO", note="QSA")
    db.add(
        Identifier(
            entity_id=person.id,
            kind="EMAIL",
            value="eduardo@exemplo.com",
            canonical_key="email:eduardo@exemplo.com",
            strong=True,
        )
    )
    db.add(
        Evidence(
            investigation_id=inv.id,
            entity_id=person.id,
            edge_id=edge.id,
            connector="cnpj_receita",
            source_label="Receita",
            snippet="sócio",
            dedup_hash="purge-test-hash",
        )
    )
    db.add(ExpansionJob(investigation_id=inv.id, entity_id=person.id, depth=0))
    add_case_note(db, inv, title="nota", body="apagar junto", created_by="tester")
    db.flush()
    case_id = inv.id
    assert purge_investigation(db, case_id)
    db.commit()
    assert db.get(Investigation, case_id) is None
    assert db.scalars(select(Entity).where(Entity.investigation_id == case_id)).all() == []
    assert db.scalars(select(Edge).where(Edge.investigation_id == case_id)).all() == []
    assert db.scalars(select(Evidence).where(Evidence.investigation_id == case_id)).all() == []
    assert db.scalars(select(ExpansionJob).where(ExpansionJob.investigation_id == case_id)).all() == []
    assert db.scalars(select(CaseNote).where(CaseNote.investigation_id == case_id)).all() == []
    assert db.scalars(select(BlockedKey).where(BlockedKey.investigation_id == case_id)).all() == []
    assert db.scalars(select(Identifier).where(Identifier.entity_id == person.id)).all() == []


def test_graph_layout_persists_on_case(settings, db) -> None:
    inv = _case(db)
    entity = inv.entities[0]
    saved = save_graph_layout(
        db,
        inv.id,
        {
            "view": "rede",
            "zoom": 1.35,
            "pan": {"x": 40, "y": -12},
            "nodes": {entity.id: {"x": 111.4, "y": 222.8}, "ghost": {"x": 1, "y": 2}},
        },
    )
    assert saved is not None
    assert saved["zoom"] == 1.35
    assert saved["nodes"][entity.id] == {"x": 111.4, "y": 222.8}
    assert "ghost" not in saved["nodes"]
    payload = graph_payload(db, inv.id)
    assert payload["layout"]["pan"]["x"] == 40
    assert payload["layout"]["nodes"][entity.id]["y"] == 222.8
