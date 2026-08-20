from sqlalchemy import select

from osint4all.connectors.base import ConnectorResult, FoundEntity
from osint4all.db.models import Entity
from osint4all.graph.identity import collapse_name
from osint4all.graph.match import (
    DOSSIER_MATCH_MIN,
    Place,
    PersonSnap,
    apply_match_attrs,
    can_absorb_by_name,
    infer_place,
    score_identity,
    suggested_status,
)
from osint4all.graph.resolve import apply_result
from osint4all.graph.seed import create_investigation
from osint4all.identifiers import parse_seed
from osint4all.quality.resolution import resolution_score
from osint4all.quality.verification import dossier_include


def test_process_in_other_state_is_neutral() -> None:
    target = PersonSnap(
        name="João Silva Souza",
        places=[Place(kind="residence", municipio="São Paulo", uf="SP")],
    )
    candidate = PersonSnap(
        name="João Silva Souza",
        places=[
            Place(kind="residence", municipio="São Paulo", uf="SP"),
            infer_place(municipio="Rio de Janeiro", uf="RJ", role="processo") or Place(kind="associated", uf="RJ", role="processo"),
        ],
    )
    result = score_identity(target, candidate)
    assert result.contradictions == []
    assert any("processo" in why for why in result.neutrals)
    assert result.identity_match < 75


def test_incompatible_birth_penalizes() -> None:
    target = PersonSnap(name="João Silva Souza", birth="1984")
    candidate = PersonSnap(name="João Silva Souza", birth="1997")
    result = score_identity(target, candidate)
    assert result.contradictions
    assert result.identity_match < 20
    assert suggested_status(result.identity_match, contradictions=len(result.contradictions)) == "false"


def test_email_lifts_score_city_alone_does_not() -> None:
    weak = score_identity(
        PersonSnap(name="João Silva", places=[Place(kind="residence", municipio="São Paulo", uf="SP")]),
        PersonSnap(name="João Silva", places=[Place(kind="residence", municipio="São Paulo", uf="SP")]),
    )
    strong = score_identity(
        PersonSnap(name="João Silva Souza", emails={"joao.silva@gmail.com"}, companies={"xpto comercio ltda"}),
        PersonSnap(name="João Silva Souza", emails={"joao.silva@gmail.com"}, companies={"xpto comercio ltda"}),
    )
    assert weak.identity_match < 40
    assert strong.identity_match >= 75
    assert strong.identity_match >= DOSSIER_MATCH_MIN


def test_resolution_exposes_three_scores() -> None:
    entity = Entity(
        entity_type="PERSON",
        canonical_key="name:ana",
        display_name="Ana Silva Souza",
        attrs={
            "identity_match": 82,
            "source_reliability": 0.9,
            "claim_confidence": 0.75,
            "match_reasons": ["Mesmo e-mail."],
            "match_contradictions": [],
            "status": "probable",
        },
        confidence=0.65,
    )
    entity.identifiers = []
    score = resolution_score(entity)
    assert score["identity_match"] == 82
    assert score["source_reliability"] == 0.9
    assert score["claim_confidence"] == 0.75
    assert score["reasons"]


def test_low_match_stays_out_of_dossier() -> None:
    weak = Entity(
        entity_type="PERSON",
        canonical_key="name:joao#cand:1",
        display_name="João Silva Souza",
        attrs={"status": "unconfirmed", "identity_match": 35},
    )
    assert dossier_include(weak) is False
    seed = Entity(
        entity_type="PERSON",
        canonical_key="name:joao",
        display_name="João Silva Souza",
        attrs={"status": "confirmed", "identity_match": 25},
        is_seed=True,
    )
    assert dossier_include(seed) is True


def test_low_match_does_not_absorb(db) -> None:
    seed = parse_seed("Joao Silva Souza", forced_kind="NAME")
    inv = create_investigation(
        db,
        title="Match",
        hypothesis="limiar",
        seeds=[seed],
        connectors=[],
        max_depth=1,
        monitor=False,
        created_by="t",
    )
    origin = next(e for e in inv.entities if e.is_seed)
    result = ConnectorResult()
    result.entities.append(
        FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value="Joao Silva Souza",
            display_name="Joao Silva Souza",
            attrs={"status": "unconfirmed", "candidate_key": "qsa:outro", "documento_ausente": True},
            confidence=0.4,
        )
    )
    created = apply_result(db, inv, origin, result, connector="cnpj_receita", depth=0, enqueue_children=False, max_attempts=1)
    db.flush()
    people = list(
        db.scalars(select(Entity).where(Entity.investigation_id == inv.id, Entity.entity_type == "PERSON"))
    )
    extras = [e for e in people if e.id != origin.id]
    assert created or extras
    assert extras
    extra = extras[0]
    assert extra.id != origin.id
    assert int((extra.attrs or {}).get("identity_match") or 0) < DOSSIER_MATCH_MIN
    assert not can_absorb_by_name(extra)


def test_collapse_name_drops_accent() -> None:
    assert collapse_name("João Antônio") == collapse_name("Joao Antonio")


def test_apply_match_does_not_confirm() -> None:
    entity = Entity(
        entity_type="PERSON",
        canonical_key="name:x",
        display_name="Ana",
        attrs={},
        confidence=0.4,
    )
    result = score_identity(
        PersonSnap(name="Ana Silva Souza", emails={"a@x.com"}),
        PersonSnap(name="Ana Silva Souza", emails={"a@x.com"}),
    )
    apply_match_attrs(entity, result)
    assert entity.attrs["status"] == "probable"
    assert entity.attrs["status"] != "confirmed"
