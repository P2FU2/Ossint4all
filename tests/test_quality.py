from osint4all.connectors.base import ConnectorResult, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.graph.identity import entity_status, should_enqueue_child
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed
from osint4all.quality.changes import case_digest, recent_changes
from osint4all.quality.provenance import content_hash, snapshot_abs, write_snapshot
from osint4all.quality.resolution import resolution_score
from osint4all.quality.timeline import list_events
from osint4all.quality.verification import apply_verdict, normalize_verdict, verdict_label
from osint4all.report.dossier import render_dossier_html


def test_verdicts_and_labels() -> None:
    assert normalize_verdict("rejected") == "false"
    assert verdict_label("probable") == "Provável"
    assert entity_status({"status": "rejected"}) == "false"
    assert entity_status({"status": "contested"}) == "contested"


def test_false_entity_is_not_enqueued() -> None:
    found = FoundEntity(entity_type="PERSON", kind="NAME", value="Ana Silva", display_name="Ana Silva", attrs={"status": "false"}, confidence=0.05)
    parent = Entity(entity_type="ORG", canonical_key="cnpj:33000167000101", display_name="Empresa", attrs={}, depth=1)
    assert should_enqueue_child(found, parent) is False


def test_evidence_writes_timeline_and_hash(db) -> None:
    seed = parse_seed("https://exemplo.com.br", forced_kind="URL")
    inv = create_investigation(db, title="Qualidade", hypothesis="checar", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t")
    origin = inv.entities[0]
    result = ConnectorResult()
    result.entities.append(
        FoundEntity(entity_type="PUBLICATION", kind="URL", value="https://exemplo.com.br/sobre", display_name="Sobre", confidence=0.4)
    )
    result.evidence.append(
        FoundEvidence(source_label="Portal", url="https://exemplo.com.br/", snippet="homepage", payload={"host": "exemplo.com.br", "method": "GET", "http_status": 200})
    )
    apply_result(db, inv, origin, result, connector="host_observe", depth=0, enqueue_children=False, max_attempts=1)
    db.flush()
    events = list_events(db, inv.id)
    assert any(ev.event_type == "evidence" for ev in events)
    digest = case_digest(db, inv.id)
    assert digest["evidence"] >= 1
    assert digest["entities"] >= 2
    assert recent_changes(db, inv.id)
    ev = origin.evidence[0] if origin.evidence else None
    if ev is None:
        from sqlalchemy import select
        from osint4all.db.models import Evidence

        ev = db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id)).first()
    assert ev is not None
    assert ev.content_sha256
    assert ev.method == "GET"
    assert ev.http_status == 200


def test_verdict_and_resolution(db) -> None:
    seed = parse_seed("Ana Silva Souza", forced_kind="NAME")
    inv = create_investigation(db, title="Veredito", hypothesis=None, seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="t")
    entity = inv.entities[0]
    apply_verdict(db, inv, entity, verdict="probable", reason="mesmo nome no QSA, sem CPF", created_by="ana")
    db.flush()
    assert entity_status(entity) == "probable"
    score = resolution_score(entity)
    assert score["status"] == "probable"
    assert score["score"] >= 0.6


def test_snapshot_stays_inside_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("osint4all.quality.provenance.project_root", lambda: tmp_path)
    rel = write_snapshot("inv1", "abc123", b"<html>ok</html>")
    assert rel.endswith(".html")
    assert snapshot_abs(rel) is not None
    assert snapshot_abs("../secret") is None
    assert content_hash({"a": 1}, "x", "https://x") != content_hash({"a": 2}, "x", "https://x")


def test_dossier_has_cover_and_citations(db) -> None:
    seed = parse_seed("Maria Silva Souza")
    inv = create_investigation(db, title="Caso capa", hypothesis="Verificar menções", seeds=[seed], connectors=[], max_depth=1, monitor=False, created_by="tester")
    inv.purpose = "reportagem"
    inv.assignee = "tester"
    origin = inv.entities[0]
    result = ConnectorResult()
    result.evidence.append(FoundEvidence(source_label="Wikidata", url="https://www.wikidata.org/wiki/Q1", snippet="ficha pública"))
    apply_result(db, inv, origin, result, connector="wikidata", depth=0, enqueue_children=False, max_attempts=1)
    db.flush()
    html = render_dossier_html(db, inv.id)
    assert "Caso capa" in html
    assert "reportagem" in html
    assert "tester" in html
    assert "[1]" in html
    assert "Veredito" in html
    assert "fontes públicas" in html.lower()
