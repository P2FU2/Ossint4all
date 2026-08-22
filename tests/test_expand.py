from __future__ import annotations

from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.db.session import session_scope
from osint4all.graph.expand import ExpansionEngine, connectors_for_kinds, process_pending_jobs
from osint4all.graph.seed import attach_plate_owner, create_investigation
from osint4all.identifiers import parse_seed


class FakeCnpj:
    name = "cnpj_receita"

    def accepts(self, entity: Entity) -> bool:
        return entity.canonical_key.startswith("cnpj:")

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        org_key = entity.canonical_key
        person = FoundEntity(
            entity_type="PERSON",
            kind="CPF",
            value="52998224725",
            display_name="JOAO DA SILVA",
            confidence=0.9,
        )
        return ConnectorResult(
            entities=[person],
            edges=[
                FoundEdge(
                    from_ref="cpf:52998224725",
                    to_ref=org_key,
                    rel_type="SOCIO",
                    confidence=0.9,
                )
            ],
            evidence=[
                FoundEvidence(
                    source_label="teste",
                    url="https://example.com",
                    snippet="QSA",
                    entity_ref=org_key,
                )
            ],
        )

    def health(self) -> dict:
        return {"source": self.name, "enabled": True}


def test_connectors_for_kinds_scopes_sources() -> None:
    assert connectors_for_kinds(None) is None
    assert connectors_for_kinds([]) is None
    email = connectors_for_kinds(["EMAIL"])
    assert email is not None
    assert "email_public" in email
    assert "cnpj_receita" not in email
    companies = connectors_for_kinds(["COMPANIES"])
    assert companies is not None
    assert "socio_search" in companies
    processos = connectors_for_kinds(["PROCESSOS"])
    assert processos is not None
    assert "djen" in processos
    assert "datajud" in processos
    info = connectors_for_kinds(["INFO"])
    assert info is not None
    assert "djen" in info
    assert "transparencia" in info
    assert "socio_search" in info
    assert "aleph_public" in info
    name = connectors_for_kinds(["NAME"])
    assert name is not None
    assert "aleph_public" in name
    assert "pncp_public" in name
    mixed = connectors_for_kinds(["EMAIL", "QSA"])
    assert mixed is not None
    assert "email_public" in mixed
    assert "cnpj_receita" in mixed
    assert connectors_for_kinds(["BIRTHDATE"]) == set()
    url = connectors_for_kinds(["URL"])
    assert url is not None
    assert "host_public" in url
    assert "transparencia" in (connectors_for_kinds(["SANCTIONS"]) or set())
    from osint4all.graph.expand import kind_for_connector

    assert kind_for_connector("cnpj_receita") == "CNPJ"
    assert kind_for_connector("email_public") == "EMAIL"


class _CountConnector:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def accepts(self, entity: Entity) -> bool:
        return True

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        self.calls += 1
        return ConnectorResult()

    def health(self) -> dict:
        return {"source": self.name, "enabled": True}


def test_probe_kinds_runs_only_selected_connectors(settings) -> None:
    email = _CountConnector("email_public")
    receita = _CountConnector("cnpj_receita")
    seed = parse_seed("ana@example.com", forced_kind="EMAIL")
    assert seed
    with session_scope() as session:
        inv = create_investigation(
            session,
            title="Alvo",
            hypothesis="email",
            seeds=[seed],
            connectors=["email_public", "cnpj_receita"],
            max_depth=2,
            monitor=False,
            created_by="tester",
        )
        entity = inv.entities[0]
        attrs = dict(entity.attrs or {})
        attrs["probe_kinds"] = ["EMAIL"]
        entity.attrs = attrs
        inv_id = inv.id
        entity_id = entity.id

    engine = ExpansionEngine(settings=settings, connectors=[email, receita])
    with session_scope() as session:
        from osint4all.db.models import Investigation

        inv = session.get(Investigation, inv_id)
        entity = session.get(Entity, entity_id)
        assert inv and entity
        engine.expand_entity(inv, entity, depth=0)
        assert "probe_kinds" not in (entity.attrs or {})
    assert email.calls == 1
    assert receita.calls == 0


def test_engine_expands_and_enqueues_child(settings) -> None:
    seed = parse_seed("33.000.167/0001-01")
    assert seed
    with session_scope() as session:
        inv = create_investigation(
            session,
            title="Petro",
            hypothesis="QSA",
            seeds=[seed],
            connectors=["cnpj_receita"],
            max_depth=2,
            monitor=False,
            created_by="tester",
        )
        inv_id = inv.id

    engine = ExpansionEngine(settings=settings, connectors=[FakeCnpj()])
    n = process_pending_jobs(investigation_id=inv_id, limit=10, settings=settings, engine=engine)
    assert n >= 1

    from sqlalchemy import select

    from osint4all.db.models import Edge, Entity as Ent

    with session_scope() as session:
        entities = session.scalars(select(Ent).where(Ent.investigation_id == inv_id)).all()
        names = {e.display_name for e in entities}
        assert "JOAO DA SILVA" in names
        edges = session.scalars(select(Edge).where(Edge.investigation_id == inv_id)).all()
        assert any(e.rel_type == "SOCIO" for e in edges)


def test_attach_plate_owner_links_person(settings) -> None:
    from sqlalchemy import select

    from osint4all.db.models import Edge, Entity as Ent

    seed = parse_seed("ABC1D23")
    assert seed
    with session_scope() as session:
        inv = create_investigation(
            session,
            title="Placa",
            hypothesis="dono",
            seeds=[seed],
            connectors=["plate_public"],
            max_depth=2,
            monitor=False,
            created_by="tester",
        )
        attach_plate_owner(
            session,
            inv,
            plate="ABC1D23",
            owner_name="Maria Silva Souza",
            owner_cpf="529.982.247-25",
        )
        inv_id = inv.id

    with session_scope() as session:
        types = {e.entity_type for e in session.scalars(select(Ent).where(Ent.investigation_id == inv_id))}
        assert "VEHICLE" in types
        assert "PERSON" in types
        edges = session.scalars(select(Edge).where(Edge.investigation_id == inv_id)).all()
        assert any(e.rel_type == "PROPRIETARIO" for e in edges)
