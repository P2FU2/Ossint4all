"""Verification engine: independência de fonte, qualidade, RAG, PII, negativos."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import Entity, Evidence, Identifier, Investigation, NegativeFinding
from osint4all.engines.knowledge import evidence_decay
from osint4all.graph.identity import entity_status, has_expandable_anchor
from osint4all.identifiers import STRONG_ID_KINDS

_PII = {
    "CPF": "SENSITIVE",
    "PHONE": "PERSONAL",
    "EMAIL": "PERSONAL",
    "NAME": "PERSONAL",
    "CNPJ": "PUBLIC",
    "CNJ": "PUBLIC",
    "URL": "PUBLIC",
    "USERNAME": "PUBLIC",
    "PLATE": "INTERNAL",
}


def origin_key(ev: Evidence) -> str:
    host = ""
    if ev.url:
        host = (urlparse(ev.url).hostname or "").lower().removeprefix("www.")
    snippet = re.sub(r"\s+", " ", (ev.snippet or "")[:160].lower())
    digest = hashlib.sha256(snippet.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{host or ev.connector}:{digest}"


def cluster_sources(evidence: list[Evidence]) -> list[dict[str, Any]]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        groups[origin_key(ev)].append(ev)
    clusters = []
    for key, rows in groups.items():
        clusters.append(
            {
                "origin": key,
                "count": len(rows),
                "independent": len(rows) == 1,
                "labels": sorted({r.source_label for r in rows}),
                "ids": [r.id for r in rows],
            }
        )
    clusters.sort(key=lambda row: (-row["count"], row["origin"]))
    return clusters


def independent_count(evidence: list[Evidence]) -> int:
    return len({origin_key(ev) for ev in evidence})


def citation_edges(evidence: list[Evidence]) -> list[dict[str, str]]:
    """Quem cita quem: mesmo host ou menção ao rótulo de outra fonte."""
    by_host: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        host = (urlparse(ev.url).hostname or ev.connector).lower() if ev.url else ev.connector
        by_host[host].append(ev)
    links = []
    labels = [(ev.id, ev.source_label.lower()) for ev in evidence if ev.source_label]
    for ev in evidence:
        snippet = (ev.snippet or "").lower()
        for other_id, label in labels:
            if other_id == ev.id or len(label) < 5:
                continue
            if label in snippet:
                links.append({"from": ev.id, "to": other_id, "why": "menciona a fonte"})
    return links[:40]


def classify_pii(kind: str) -> str:
    return _PII.get((kind or "").upper(), "INTERNAL")


def entity_pii(entity: Entity) -> str:
    ranks = {"PUBLIC": 0, "INTERNAL": 1, "PERSONAL": 2, "SENSITIVE": 3, "RESTRICTED": 4}
    level = "PUBLIC" if entity.entity_type == "ORG" else "INTERNAL"
    for ident in entity.identifiers or []:
        klass = classify_pii(ident.kind)
        if ranks[klass] > ranks[level]:
            level = klass
    return level


def add_negative(
    session: Session,
    investigation: Investigation,
    *,
    connector: str,
    query: str,
    entity_id: str | None = None,
) -> NegativeFinding:
    row = NegativeFinding(
        investigation_id=investigation.id,
        entity_id=entity_id,
        connector=connector,
        query=(query or "")[:512],
        note="Não encontrado nesta fonte. Isso não prova que não existe.",
    )
    session.add(row)
    return row


def retrieve_for_question(session: Session, investigation_id: str, question: str, *, limit: int = 12) -> list[Evidence]:
    tokens = [t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", (question or "").lower()) if t not in {"para", "com", "uma", "que", "dos", "das", "entre"}]
    rows = list(session.scalars(select(Evidence).where(Evidence.investigation_id == investigation_id)).all())
    scored: list[tuple[int, Evidence]] = []
    for ev in rows:
        blob = f"{ev.source_label} {ev.snippet or ''} {ev.url or ''} {ev.connector}".lower()
        score = sum(1 for tok in tokens if tok in blob)
        if score:
            scored.append((score, ev))
    scored.sort(key=lambda item: -item[0])
    return [ev for _, ev in scored[:limit]]


def answer_with_citations(session: Session, investigation_id: str, question: str) -> dict[str, Any]:
    evidence = retrieve_for_question(session, investigation_id, question)
    cites = [f"[{i}] {ev.source_label}: {(ev.snippet or ev.url or ev.connector)[:160]}" for i, ev in enumerate(evidence, start=1)]
    if not evidence:
        return {"answer": "Nenhuma evidência do caso cobre essa pergunta. Isso não é uma resposta negativa sobre o mundo.", "citations": []}
    return {
        "answer": "Com base só nas evidências do caso:\n" + "\n".join(cites),
        "citations": cites,
        "ids": [ev.id for ev in evidence],
    }


def quality_score(session: Session, investigation: Investigation) -> dict[str, Any]:
    entities = list(session.scalars(select(Entity).where(Entity.investigation_id == investigation.id)).all())
    evidence = list(session.scalars(select(Evidence).where(Evidence.investigation_id == investigation.id)).all())
    idents = list(
        session.scalars(select(Identifier).join(Entity).where(Entity.investigation_id == investigation.id)).all()
    )
    connectors = {ev.connector for ev in evidence}
    stale = sum(1 for ev in evidence if evidence_decay(ev)["stale"])
    strong = sum(1 for ident in idents if ident.kind in STRONG_ID_KINDS)
    confirmed = sum(1 for e in entities if entity_status(e) == "confirmed")
    contested = sum(1 for e in entities if entity_status(e) in {"contested", "false"})
    independent = independent_count(evidence)
    coverage = min(100, int(100 * len(connectors) / 8)) if connectors else 0
    primary = min(100, int(100 * strong / max(len(entities), 1)))
    verified = min(100, int(100 * confirmed / max(len(entities), 1))) if entities else 0
    stale_pct = int(100 * stale / max(len(evidence), 1)) if evidence else 0
    confidence = int(100 * (sum(e.confidence or 0 for e in entities) / max(len(entities), 1))) if entities else 0
    overall = int(
        0.2 * coverage
        + 0.2 * primary
        + 0.25 * verified
        + 0.15 * min(100, 100 * independent / max(len(evidence), 1))
        + 0.1 * max(0, 100 - stale_pct)
        + 0.1 * confidence
    )
    return {
        "source_coverage": coverage,
        "primary_sources": primary,
        "claims_verified": verified,
        "contradictions_open": contested,
        "stale_evidence": stale_pct,
        "entity_confidence": confidence,
        "independent_origins": independent,
        "overall": overall,
        "ready": overall >= 70 and contested == 0,
        "connectors": sorted(connectors),
        "has_anchor": any(has_expandable_anchor(e) for e in entities),
    }
