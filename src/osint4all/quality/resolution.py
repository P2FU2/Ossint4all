"""Score de resolução: identidade, fonte e afirmação — com breakdown."""

from __future__ import annotations

from osint4all.db.models import Entity
from osint4all.graph.identity import entity_status
from osint4all.graph.match import band_for_score, geo_profile, place_from_dict
from osint4all.identifiers import STRONG_ID_KINDS


def resolution_score(entity: Entity) -> dict[str, object]:
    kinds = {ident.kind for ident in (entity.identifiers or [])}
    strong = sorted(kinds & STRONG_ID_KINDS)
    status = entity_status(entity)
    attrs = dict(entity.attrs or {})
    score = float(entity.confidence or 0)
    if strong:
        score = max(score, 0.8)
    if entity.is_seed:
        score = max(score, 0.7)
    if status == "confirmed":
        score = max(score, 0.85)
    elif status == "probable":
        score = max(score, 0.6)
    elif status in {"false", "rejected"}:
        score = min(score, 0.1)
    identity = attrs.get("identity_match")
    if identity is None:
        identity = int(round(min(score, 0.99) * 100))
    else:
        identity = int(identity)
    places = []
    for raw in attrs.get("places") or []:
        if isinstance(raw, dict):
            place = place_from_dict(raw)
            if place:
                places.append(place)
    return {
        "score": round(min(score, 0.99), 2),
        "status": status,
        "strong": strong,
        "kinds": sorted(kinds),
        "rule": "âncora forte" if strong else ("semente" if entity.is_seed else "menção / nome"),
        "identity_match": identity,
        "source_reliability": float(attrs.get("source_reliability") or 0),
        "claim_confidence": float(attrs.get("claim_confidence") or 0),
        "reasons": list(attrs.get("match_reasons") or []),
        "contradictions": list(attrs.get("match_contradictions") or []),
        "neutrals": list(attrs.get("match_neutrals") or []),
        "band": attrs.get("match_band") or band_for_score(identity),
        "places": places,
        "geo": geo_profile(places),
    }
