from osint4all.connectors.base import FoundEntity
from osint4all.connectors.cnpj_receita import parse_cnpj_payload
from osint4all.db.models import Entity
from osint4all.db.repository import detach_entity, enqueue_qsa_network
from osint4all.graph.identity import found_canonical_key, has_expandable_anchor, is_unconfirmed, names_match, should_enqueue_child
from osint4all.graph.layers import confirmed_seeds, run_alvo_layer
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed


def test_homonym_does_not_share_key() -> None:
    a = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="MARIA SILVA",
        display_name="MARIA SILVA",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:1"},
    )
    b = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="MARIA SILVA",
        display_name="MARIA SILVA",
        attrs={"status": "unconfirmed", "candidate_key": "qsa:2"},
    )
    assert found_canonical_key(a) != found_canonical_key(b)
    assert is_unconfirmed(a)


def test_name_only_does_not_seed_graph() -> None:
    seeds = confirmed_seeds({"NAME": "Maria Silva Souza"})
    assert seeds == []
    seeds = confirmed_seeds({"NAME": "Maria Silva Souza", "CNPJ": "33000167000101"}, qsa_match=True)
    assert {s.kind for s in seeds} >= {"NAME", "CNPJ"}
    cnpj_only = confirmed_seeds({"NAME": "Maria Silva Souza", "CNPJ": "33000167000101"}, qsa_match=False)
    assert {s.kind for s in cnpj_only} == {"CNPJ"}
    email_anchor = confirmed_seeds({"NAME": "Maria Silva Souza", "EMAIL": "ana@exemplo.com"})
    assert {s.kind for s in email_anchor} >= {"NAME", "EMAIL"}


def test_email_layer_derives_username() -> None:
    layer = run_alvo_layer({}, kind="EMAIL", value="pedromilani14@gmail.com", live=False)
    assert layer.ok
    assert layer.fields["EMAIL"] == "pedromilani14@gmail.com"
    assert layer.fields["USERNAME"] == "pedromilani14"
    assert any(hit.kind == "USERNAME" for hit in layer.confirmed)
    assert layer.consult and layer.consult.facts
    assert layer.consult.hits


def test_qsa_name_only_is_unconfirmed() -> None:
    result = parse_cnpj_payload(
        {
            "cnpj": "33000167000101",
            "razao_social": "EMPRESA X",
            "qsa": [{"nome_socio": "MARIA SILVA SOUZA", "qualificacao_socio": "Sócio"}],
        }
    )
    person = next(e for e in result.entities if e.kind == "NAME")
    assert is_unconfirmed(person)
    assert found_canonical_key(person).startswith("name:")


def test_names_match_is_exact() -> None:
    assert names_match("Maria Silva Souza", "MARIA  SILVA   SOUZA")
    assert not names_match("Maria Silva", "Maria Silva Souza")


def test_qsa_partner_with_full_name_is_enqueued() -> None:
    found = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="JOAO PEREIRA LIMA",
        display_name="JOAO PEREIRA LIMA",
        attrs={"status": "unconfirmed", "papel": "Sócio", "candidate_key": "qsa:1", "documento_ausente": True},
        confidence=0.45,
    )
    parent = Entity(
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={},
        depth=1,
    )
    assert should_enqueue_child(found, parent) is True


def test_profile_child_is_not_enqueued() -> None:
    found = FoundEntity(
        entity_type="PROFILE",
        kind="URL",
        value="https://vimeo.com/telegram",
        display_name="Vimeo",
        confidence=0.7,
    )
    parent = Entity(
        entity_type="PROFILE",
        canonical_key="url:https://t.me/telegram",
        display_name="Telegram",
        attrs={},
        depth=1,
    )
    assert should_enqueue_child(found, parent) is False


def test_alvo_layer_plate_offline() -> None:
    layer = run_alvo_layer({}, kind="PLATE", value="ABC1D23", live=False)
    assert layer.ok
    assert layer.confirmed


def test_unconfirmed_name_child_not_enqueued(settings, db) -> None:
    seed = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["socio_search"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    found = FoundEntity(
        entity_type="PERSON",
        kind="NAME",
        value="JOAO PEREIRA LIMA",
        display_name="JOAO PEREIRA LIMA",
        attrs={"status": "unconfirmed", "candidate_key": "homonym:1"},
        confidence=0.4,
    )
    from osint4all.connectors.base import ConnectorResult, FoundEdge

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=origin.canonical_key, to_ref=found_canonical_key(found), rel_type="CANDIDATO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=True,
        max_attempts=3,
    )
    jobs = [j for j in inv.jobs if j.entity_id != origin.id]
    assert jobs == []


def test_qsa_edge_records_degree_to_target(settings, db) -> None:
    seed = parse_seed("33000167000101", forced_kind="CNPJ")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita", "socio_search"],
        max_depth=3,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    found = FoundEntity(
        entity_type="PERSON",
        kind="CPF",
        value="52998224725",
        display_name="JOAO PEREIRA LIMA",
        attrs={"papel": "Sócio"},
        confidence=0.9,
    )
    from osint4all.connectors.base import ConnectorResult, FoundEdge
    from osint4all.db.models import Edge
    from sqlalchemy import select

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=found_canonical_key(found), to_ref=origin.canonical_key, rel_type="SOCIO")],
        ),
        connector="cnpj_receita",
        depth=0,
        enqueue_children=True,
        max_attempts=3,
    )
    person = db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")).first()
    assert person is not None
    assert person.depth == 1
    assert person.attrs.get("grau") == 1
    edge = db.scalars(select(Edge).where(Edge.investigation_id == inv.id, Edge.rel_type == "SOCIO")).first()
    assert edge is not None
    assert edge.attrs.get("grau") == 1
    assert any(j.entity_id == person.id for j in inv.jobs)


def test_unconfirmed_cnpj_child_is_enqueued(settings, db) -> None:
    seed = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    found = FoundEntity(
        entity_type="ORG",
        kind="CNPJ",
        value="33000167000101",
        display_name="Empresa",
        attrs={"status": "unconfirmed"},
        confidence=0.4,
    )
    from osint4all.connectors.base import ConnectorResult, FoundEdge

    apply_result(
        db,
        inv,
        origin,
        ConnectorResult(
            entities=[found],
            edges=[FoundEdge(from_ref=origin.canonical_key, to_ref="cnpj:33000167000101", rel_type="CANDIDATO")],
        ),
        connector="socio_search",
        depth=0,
        enqueue_children=True,
        max_attempts=3,
    )
    jobs = [j for j in inv.jobs if j.entity_id != origin.id]
    assert len(jobs) == 1
    assert has_expandable_anchor(found)


def test_detach_removes_edges(settings, db) -> None:
    seed = parse_seed("529.982.247-25", forced_kind="CPF")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=[],
        max_depth=1,
        monitor=False,
        created_by="tester",
    )
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
    from osint4all.db.models import Edge

    db.add(
        Edge(
            investigation_id=inv.id,
            from_entity_id=person.id,
            to_entity_id=other.id,
            rel_type="SOCIO",
        )
    )
    db.flush()
    assert detach_entity(db, inv.id, other.id)
    from sqlalchemy import select

    left = db.scalars(select(Edge).where(Edge.investigation_id == inv.id)).all()
    assert left == []
    assert db.get(Entity, other.id) is None


def test_enqueue_qsa_network_raises_depth_and_queues_cnpj(settings, db) -> None:
    seed = parse_seed("Maria Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Alvo",
        hypothesis="teste",
        seeds=[seed],
        connectors=["cnpj_receita"],
        max_depth=2,
        monitor=False,
        created_by="tester",
    )
    company = Entity(
        investigation_id=inv.id,
        entity_type="ORG",
        canonical_key="cnpj:33000167000101",
        display_name="Empresa",
        attrs={"status": "unconfirmed"},
        depth=1,
    )
    db.add(company)
    db.flush()
    queued = enqueue_qsa_network(db, inv, max_attempts=3)
    db.flush()
    assert inv.max_depth == 6
    assert queued >= 1
    from osint4all.db.models import ExpansionJob
    from sqlalchemy import select

    jobs = db.scalars(select(ExpansionJob).where(ExpansionJob.entity_id == company.id)).all()
    assert jobs
