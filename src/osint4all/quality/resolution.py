"""Score de resolução de entidade a partir dos identificadores."""

from __future__ import annotations

from osint4all.db.models import Entity
from osint4all.graph.identity import entity_status
from osint4all.identifiers import STRONG_ID_KINDS


def resolution_score(entity: Entity) -> dict[str, object]:
    kinds = {ident.kind for ident in (entity.identifiers or [])}
    strong = sorted(kinds & STRONG_ID_KINDS)
    status = entity_status(entity)
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
    return {
        "score": round(min(score, 0.99), 2),
        "status": status,
        "strong": strong,
        "kinds": sorted(kinds),
        "rule": "âncora forte" if strong else ("semente" if entity.is_seed else "menção / nome"),
    }
