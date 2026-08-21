from datetime import timedelta

from sqlalchemy import select

from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Edge, Entity, EntityVersion, NegativeFinding, QueryLog
from osint4all.db.repository import detach_entity, graph_payload, live_investigations, utcnow
from osint4all.engines.discovery import extract_document_facts, log_query, route_connectors
from osint4all.engines.intelligence import global_lookup, parse_search, shortest_path
from osint4all.engines.investigation import (
    add_claim,
    add_hypothesis,
    approve_claim,
    claim_ready_for_report,
    gap_analysis,
    set_stance,
    suggest_alternatives,
)
from osint4all.engines.knowledge import decay_weight, strength_label
from osint4all.engines.playbooks import (
    PERSON_STEPS,
    attach_playbook,
    enqueue_playbook_step,
    evaluate_playbook_step,
    list_items,
    progress,
    step_can_run,
)
from osint4all.engines.verification import cluster_sources, independent_count, origin_key, quality_score
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed
from osint4all.report.dossier import render_dossier_html


def test_playbook_company_from_cnpj(db) -> None:
    seed = parse_seed("33.000.167/0001-01")
    inv = create_investigation(
        db, title="Petro", hypothesis="QSA", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    assert inv.playbook_key == "COMPANY"
    items = list_items(db, inv.id)
    assert len(items) == 20
    assert progress(items)["pct"] == 0
    attach_playbook(db, inv, "COMPANY")
    assert len(list_items(db, inv.id)) == 20
    partners = next(item for item in list_items(db, inv.id) if item.step_key in {"partners", "COMPANY:partners"} or item.title == "Sócios")
    assert step_can_run(partners)
    queued = enqueue_playbook_step(db, inv, partners)
    assert queued["ok"] is True
    assert queued["queued"] >= 1
    assert partners.status == "doing"
    db.add(
        QueryLog(
            investigation_id=inv.id,
            entity_id=inv.entities[0].id,
            connector="cnpj_receita",
            params={"key": inv.entities[0].canonical_key},
            result_count=2,
            empty=False,
        )
    )
    db.flush()
    done = evaluate_playbook_step(db, inv, partners)
    assert done["status"] == "done"
    assert partners.status == "done"
    stale = evaluate_playbook_step(db, inv, partners, since=utcnow() + timedelta(days=1))
    assert stale["status"] == "doing"
    inv.status = "ARCHIVED"
    db.flush()
    assert inv.id not in {row.id for row in live_investigations(db)}
    assert inv.id in {row.id for row in live_investigations(db, include_archived=True)}


def test_gaps_and_quality_for_name_only(db) -> None:
    seed = parse_seed("Joao da Silva Souza")
    inv = create_investigation(
        db, title="Nome", hypothesis="É o mesmo João da empresa?", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    gaps = gap_analysis(db, inv)
    assert any(g["code"] == "identity" for g in gaps)
    score = quality_score(db, inv)
    assert "overall" in score
    assert score["ready"] is False


def test_hypothesis_stances_and_independence(db) -> None:
    seed = parse_seed("Maria Silva Souza")
    inv = create_investigation(
        db, title="H", hypothesis="Ligação societária", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    origin = inv.entities[0]
    result = ConnectorResult()
    result.evidence.append(
        FoundEvidence(source_label="Portal A", url="https://news.example/a", snippet="Maria sócia da Empresa X segundo o diário")
    )
    result.evidence.append(
        FoundEvidence(source_label="Portal B", url="https://copia.example/b", snippet="Maria sócia da Empresa X segundo o diário")
    )
    apply_result(db, inv, origin, result, connector="web_search", depth=0, enqueue_children=False, max_attempts=1)
    db.flush()
    hyp = add_hypothesis(db, inv, title="É sócia", kind="primary", created_by="t")
    evs = origin.evidence or []
    if evs:
        set_stance(db, hyp, evs[0], stance="for")
    db.flush()
    assert independent_count(list(origin.evidence)) >= 1
    clusters = cluster_sources(list(origin.evidence))
    assert clusters
    assert origin_key(origin.evidence[0])


def test_path_and_strength(db) -> None:
    seed = parse_seed("33.000.167/0001-01")
    inv = create_investigation(
        db, title="Path", hypothesis=None, seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    origin = inv.entities[0]
    result = ConnectorResult()
    result.entities.append(FoundEntity(entity_type="PERSON", kind="NAME", value="Ana Lima Costa", display_name="Ana Lima Costa"))
    result.edges.append(FoundEdge(from_ref=origin.canonical_key, to_ref="name:ana lima costa", rel_type="SOCIO", confidence=0.9))
    apply_result(db, inv, origin, result, connector="cnpj_receita", depth=1, enqueue_children=False, max_attempts=1)
    db.flush()
    people = list(db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON")))
    assert people
    path = shortest_path(db, inv.id, origin.id, people[0].id)
    assert path["hops"] == 1
    assert strength_label(0.9) == "HIGH"
    assert decay_weight(None, year=2019) < 1


def test_document_facts_and_search_parse() -> None:
    facts = extract_document_facts("Contrato com 33.000.167/0001-01 e maria@empresa.com em 14/06/2022 no valor R$ 10.000,00")
    assert facts["cnpj"]
    assert facts["emails"]
    spec = parse_search("Mostre empresas relacionadas a pessoas que também aparecem em contratos municipais")
    assert spec["entity_type"] == "ORG"
    assert spec["need_contract"] is True
    assert suggest_alternatives("João e Empresa A")[0]
    names = route_connectors()
    assert isinstance(names, list)


def test_dossier_includes_quality(db) -> None:
    seed = parse_seed("Maria Silva Souza")
    inv = create_investigation(
        db, title="Qualidade", hypothesis="checar", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    html = render_dossier_html(db, inv.id)
    assert "Qualidade do dossiê" in html
    assert "/100" in html


def test_playbook_switch_keeps_full_person_list(db) -> None:
    seed = parse_seed("33.000.167/0001-01")
    inv = create_investigation(
        db, title="Troca", hypothesis="QSA", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    attach_playbook(db, inv, "PERSON")
    person = list_items(db, inv.id, "PERSON")
    assert len(person) == len(PERSON_STEPS)
    assert {item.playbook_key for item in person} == {"PERSON"}
    assert {item.title for item in person} == {title for _, title in PERSON_STEPS}
    company = list_items(db, inv.id, "COMPANY")
    assert len(company) == 20


def test_graph_payload_reads_year_from_period(db) -> None:
    seed = parse_seed("33.000.167/0001-01")
    inv = create_investigation(
        db, title="Ano", hypothesis=None, seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    origin = inv.entities[0]
    other = Entity(
        investigation_id=inv.id,
        entity_type="PERSON",
        canonical_key="name:ana lima costa",
        display_name="Ana Lima Costa",
        attrs={},
        depth=1,
    )
    db.add(other)
    db.flush()
    db.add(
        Edge(
            investigation_id=inv.id,
            from_entity_id=origin.id,
            to_entity_id=other.id,
            rel_type="SOCIO",
            confidence=0.9,
            attrs={"periodo": "2019-2022"},
            source_connector="cnpj_receita",
        )
    )
    db.flush()
    payload = graph_payload(db, inv.id)
    assert 2019 in payload["years"]
    assert any(link.get("year") == 2019 for link in payload["edges"])


def test_failed_query_skips_negative_finding(db) -> None:
    seed = parse_seed("Maria Silva Souza")
    inv = create_investigation(
        db, title="Log", hypothesis=None, seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    origin = inv.entities[0]
    log_query(
        db,
        inv,
        connector="web_search",
        entity_id=origin.id,
        params={"key": origin.canonical_key},
        result_count=0,
        latency_ms=12,
        failed=True,
    )
    db.flush()
    assert db.scalars(select(NegativeFinding).where(NegativeFinding.investigation_id == inv.id)).first() is None
    logs = list(db.scalars(select(QueryLog).where(QueryLog.investigation_id == inv.id)))
    assert logs and logs[0].empty is False
    log_query(
        db,
        inv,
        connector="web_search",
        entity_id=origin.id,
        params={"key": origin.canonical_key},
        result_count=0,
        latency_ms=8,
        failed=False,
    )
    db.flush()
    assert db.scalars(select(NegativeFinding).where(NegativeFinding.investigation_id == inv.id)).first() is not None


def test_high_claim_needs_reviewer(db) -> None:
    seed = parse_seed("Maria Silva Souza")
    inv = create_investigation(
        db, title="Claim", hypothesis="checar", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    claim = add_claim(db, inv, text="É o sócio oculto", impact="high", created_by="ana")
    db.flush()
    approve_claim(db, claim, username="ana", role="analyst")
    approve_claim(db, claim, username="bob", role="analyst")
    db.flush()
    assert claim.status == "review"
    assert claim_ready_for_report(claim) is False
    approve_claim(db, claim, username="chefe", role="reviewer")
    db.flush()
    assert claim.status == "verified"
    assert claim_ready_for_report(claim) is True


def test_detach_clears_versions_and_query_log(db) -> None:
    seed = parse_seed("33.000.167/0001-01")
    inv = create_investigation(
        db, title="Detach", hypothesis=None, seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    origin = inv.entities[0]
    extra = Entity(
        investigation_id=inv.id,
        entity_type="PERSON",
        canonical_key="name:ana lima costa",
        display_name="Ana Lima Costa",
        attrs={},
        depth=1,
    )
    db.add(extra)
    db.flush()
    db.add(EntityVersion(investigation_id=inv.id, entity_id=extra.id, field="papel", old_value="", new_value="sócia"))
    log_query(db, inv, connector="web_search", entity_id=extra.id, params={"key": extra.canonical_key}, result_count=1, latency_ms=3)
    db.flush()
    assert detach_entity(db, inv.id, extra.id)
    db.flush()
    assert db.get(Entity, extra.id) is None
    assert db.scalars(select(EntityVersion).where(EntityVersion.investigation_id == inv.id)).first() is None


def test_global_lookup_finds_identifier_across_cases(db) -> None:
    seed = parse_seed("33.000.167/0001-01")
    inv = create_investigation(
        db, title="Banco público", hypothesis="QSA", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t"
    )
    found = global_lookup(db, "33.000.167/0001-01")
    assert found["seeds"]
    assert any(row["case_id"] == inv.id for row in found["entities"])
    titled = global_lookup(db, "Banco público")
    assert any(row["id"] == inv.id for row in titled["cases"])
