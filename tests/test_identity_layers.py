from osint4all.connectors.base import FoundEntity
from osint4all.connectors.cnpj_receita import parse_cnpj_payload
from osint4all.db.models import Entity
from osint4all.db.repository import detach_entity
from osint4all.graph.identity import found_canonical_key, is_unconfirmed, names_match
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


def test_alvo_layer_plate_offline() -> None:
    layer = run_alvo_layer({}, kind="PLATE", value="ABC1D23", live=False)
    assert layer.ok
    assert layer.confirmed


def test_unconfirmed_child_not_enqueued(settings, db) -> None:
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
    assert jobs == []


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
