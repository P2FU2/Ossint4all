from __future__ import annotations

from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.db.session import session_scope
from osint4all.graph.expand import ExpansionEngine, process_pending_jobs
from osint4all.graph.seed import create_investigation
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
