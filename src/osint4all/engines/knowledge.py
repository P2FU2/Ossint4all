"""Knowledge engine: versões de identidade, decay, força da aresta, eventos."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import Edge, Entity, EntityVersion, Evidence, Investigation
from osint4all.db.repository import utcnow

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_STALE_FIELDS = ("papel", "cargo", "endereco", "municipio", "situacao")


def strength_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "HIGH"
    if confidence >= 0.5:
        return "MEDIUM"
    return "LOW"


def annotate_edge(edge: Edge) -> dict[str, Any]:
    attrs = dict(edge.attrs or {})
    strength = attrs.get("strength") or strength_label(edge.confidence or 0)
    period = attrs.get("periodo") or attrs.get("period") or ""
    start = attrs.get("valid_from") or attrs.get("de") or ""
    end = attrs.get("valid_to") or attrs.get("ate") or ""
    year = _year_from(attrs) or _year_from({"t": period})
    return {
        "type": edge.rel_type,
        "strength": strength,
        "period": period or (" — ".join(x for x in (str(start), str(end)) if x) or "—"),
        "year": year,
        "confidence": edge.confidence,
        "note": attrs.get("nota") or "",
        "source": edge.source_connector or "",
    }


def _year_from(attrs: dict[str, Any]) -> int | None:
    for value in attrs.values():
        match = _YEAR.search(str(value))
        if match:
            return int(match.group(0))
    return None


def decay_weight(collected_at: datetime | None, *, field: str = "", year: int | None = None) -> float:
    now = datetime.now(timezone.utc)
    age_days = 0
    if year:
        age_days = max(0, (now.year - year) * 365)
    elif collected_at:
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - collected_at).days)
    if field in _STALE_FIELDS:
        age_days = max(age_days, 400 if year and year < now.year else age_days)
    if age_days <= 180:
        return 1.0
    return round(max(0.15, 0.5 ** (age_days / 730)), 2)


def is_stale(entity: Entity) -> bool:
    attrs = entity.attrs or {}
    year = _year_from(attrs)
    if year and year <= datetime.now(timezone.utc).year - 3 and any(attrs.get(k) for k in _STALE_FIELDS):
        return True
    return decay_weight(entity.last_seen_at, field="papel", year=year) < 0.4


def evidence_decay(ev: Evidence) -> dict[str, Any]:
    year = _year_from(ev.payload or {})
    weight = decay_weight(ev.collected_at, year=year)
    return {"weight": weight, "stale": weight < 0.45, "year": year}


def record_version(
    session: Session,
    investigation: Investigation,
    entity: Entity,
    field: str,
    old_value: str,
    new_value: str,
) -> EntityVersion | None:
    if (old_value or "") == (new_value or ""):
        return None
    row = EntityVersion(
        investigation_id=investigation.id,
        entity_id=entity.id,
        field=field[:64],
        old_value=(old_value or "")[:400],
        new_value=(new_value or "")[:400],
        created_at=utcnow(),
    )
    session.add(row)
    return row


def versions_for(session: Session, entity_id: str) -> list[EntityVersion]:
    return list(
        session.scalars(
            select(EntityVersion).where(EntityVersion.entity_id == entity_id).order_by(EntityVersion.created_at.desc())
        ).all()
    )


def extract_events(entities: list[Entity], evidence: list[Evidence]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for ev in evidence:
        year = _year_from(ev.payload or {}) or _year_from({"s": ev.snippet or ""})
        if not year and not ev.collected_at:
            continue
        when = f"{year}-01-01" if year else ev.collected_at.strftime("%Y-%m-%d")
        events.append(
            {
                "when": when,
                "title": ev.source_label,
                "body": (ev.snippet or "")[:180],
                "kind": "EVIDENCE",
            }
        )
    for entity in entities:
        year = _year_from(entity.attrs or {})
        papel = (entity.attrs or {}).get("papel") or (entity.attrs or {}).get("cargo")
        if year and papel:
            events.append(
                {
                    "when": f"{year}-01-01",
                    "title": f"{entity.display_name} · {papel}",
                    "body": "Cargo/papel com ano na ficha. Reconfirme antes de tratar como atual.",
                    "kind": "EVENT",
                }
            )
    events.sort(key=lambda row: row["when"])
    return events[:80]


def edge_in_year(edge: Edge, year: int | None) -> bool:
    if not year:
        return True
    info = annotate_edge(edge)
    if info["year"] is None:
        return True
    return int(info["year"]) <= year
