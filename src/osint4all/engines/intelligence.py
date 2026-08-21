"""Intelligence engine: caminho, comunidades, anomalia, cross-case, busca, alertas."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from osint4all.db.models import Edge, Entity, Identifier, Investigation, SearchHistory
from osint4all.identifiers import extract_seeds, parse_seed, seed_cards, seed_label
from osint4all.engines.knowledge import annotate_edge

_STOP = {"mostre", "empresas", "relacionadas", "pessoas", "que", "também", "aparecem", "em", "e", "a", "o", "de", "da", "do", "com", "para", "uma", "antes", "depois"}


def _adj(edges: list[Edge]) -> dict[str, list[tuple[str, Edge]]]:
    graph: dict[str, list[tuple[str, Edge]]] = defaultdict(list)
    for edge in edges:
        graph[edge.from_entity_id].append((edge.to_entity_id, edge))
        graph[edge.to_entity_id].append((edge.from_entity_id, edge))
    return graph


def shortest_path(session: Session, investigation_id: str, src_id: str, dst_id: str) -> dict[str, Any]:
    edges = list(session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)).all())
    graph = _adj(edges)
    if src_id == dst_id:
        return {"nodes": [src_id], "edges": [], "hops": 0}
    prev: dict[str, tuple[str, Edge] | None] = {src_id: None}
    queue = deque([src_id])
    while queue:
        node = queue.popleft()
        if node == dst_id:
            break
        for nxt, edge in graph.get(node, []):
            if nxt in prev:
                continue
            prev[nxt] = (node, edge)
            queue.append(nxt)
    if dst_id not in prev:
        return {"nodes": [], "edges": [], "hops": None, "message": "Sem caminho no grafo deste caso."}
    nodes = [dst_id]
    path_edges: list[Edge] = []
    cur = dst_id
    while prev[cur] is not None:
        parent, edge = prev[cur]
        path_edges.append(edge)
        nodes.append(parent)
        cur = parent
    nodes.reverse()
    path_edges.reverse()
    by_id = {
        e.id: e
        for e in session.scalars(select(Entity).where(Entity.id.in_(nodes))).all()
    }
    return {
        "nodes": [{"id": n, "name": by_id[n].display_name if n in by_id else n} for n in nodes],
        "edges": [{"id": e.id, **annotate_edge(e)} for e in path_edges],
        "hops": len(path_edges),
        "message": f"Conectados por {len(path_edges)} relação(ões)." if path_edges else "",
    }


def connected_components(edges: list[Edge], node_ids: list[str]) -> list[list[str]]:
    parent = {n: n for n in node_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for edge in edges:
        if edge.from_entity_id in parent and edge.to_entity_id in parent:
            union(edge.from_entity_id, edge.to_entity_id)
    groups: dict[str, list[str]] = defaultdict(list)
    for node in node_ids:
        groups[find(node)].append(node)
    return sorted(groups.values(), key=len, reverse=True)


def degree_centrality(edges: list[Edge], node_ids: list[str]) -> dict[str, float]:
    deg: dict[str, int] = {n: 0 for n in node_ids}
    for edge in edges:
        if edge.from_entity_id in deg:
            deg[edge.from_entity_id] += 1
        if edge.to_entity_id in deg:
            deg[edge.to_entity_id] += 1
    n = max(len(node_ids) - 1, 1)
    return {k: round(v / n, 3) for k, v in deg.items()}


def pagerank(edges: list[Edge], node_ids: list[str], *, steps: int = 12) -> dict[str, float]:
    if not node_ids:
        return {}
    graph = _adj(edges)
    score = {n: 1 / len(node_ids) for n in node_ids}
    damp = 0.85
    for _ in range(steps):
        nxt = {n: (1 - damp) / len(node_ids) for n in node_ids}
        for node in node_ids:
            neigh = graph.get(node) or []
            if not neigh:
                share = score[node] / len(node_ids)
                for other in node_ids:
                    nxt[other] += damp * share
                continue
            share = score[node] / len(neigh)
            for dest, _edge in neigh:
                if dest in nxt:
                    nxt[dest] += damp * share
        score = nxt
    return {k: round(v, 4) for k, v in score.items()}


def anomalies(session: Session, investigation_id: str) -> list[dict[str, Any]]:
    entities = list(session.scalars(select(Entity).where(Entity.investigation_id == investigation_id)).all())
    hits: list[dict[str, Any]] = []
    by_addr: dict[str, list[Entity]] = defaultdict(list)
    by_phone: dict[str, list[Entity]] = defaultdict(list)
    by_email: dict[str, list[Entity]] = defaultdict(list)
    for entity in entities:
        addr = str((entity.attrs or {}).get("endereco") or "").strip().casefold()
        if addr and len(addr) > 8:
            by_addr[addr].append(entity)
        for ident in entity.identifiers or []:
            if ident.kind == "PHONE":
                by_phone[ident.canonical_key].append(entity)
            if ident.kind == "EMAIL":
                by_email[ident.canonical_key].append(entity)
    for key, rows in by_addr.items():
        if len(rows) >= 3:
            hits.append(
                {
                    "kind": "address_cluster",
                    "title": f"{len(rows)} empresas no mesmo endereço",
                    "detail": key[:120],
                    "ids": [r.id for r in rows],
                    "note": "Padrão incomum. Não afirma irregularidade.",
                }
            )
    for key, rows in by_phone.items():
        if len(rows) >= 3:
            hits.append(
                {
                    "kind": "phone_cluster",
                    "title": f"{len(rows)} pessoas no mesmo telefone",
                    "detail": key,
                    "ids": [r.id for r in rows],
                    "note": "Padrão incomum. Não afirma irregularidade.",
                }
            )
    for key, rows in by_email.items():
        if len(rows) >= 2:
            hits.append(
                {
                    "kind": "email_cluster",
                    "title": f"{len(rows)} entidades no mesmo e-mail",
                    "detail": key,
                    "ids": [r.id for r in rows],
                    "note": "Padrão incomum. Não afirma irregularidade.",
                }
            )
    return hits


def communities(session: Session, investigation_id: str) -> list[dict[str, Any]]:
    entities = list(session.scalars(select(Entity).where(Entity.investigation_id == investigation_id)).all())
    edges = list(session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)).all())
    comps = connected_components(edges, [e.id for e in entities])
    names = {e.id: e.display_name for e in entities}
    out = []
    for idx, group in enumerate(comps[:12], start=1):
        if len(group) < 2:
            continue
        out.append(
            {
                "id": idx,
                "size": len(group),
                "names": [names[i] for i in group[:8]],
                "ids": group,
            }
        )
    return out


def cross_case_hits(session: Session, investigation_id: str) -> list[dict[str, Any]]:
    keys = list(
        session.scalars(
            select(Entity.canonical_key).where(Entity.investigation_id == investigation_id, Entity.canonical_key != "")
        )
    )
    if not keys:
        return []
    others = session.scalars(
        select(Entity).where(Entity.canonical_key.in_(keys), Entity.investigation_id != investigation_id)
    ).all()
    inv_ids = {e.investigation_id for e in others}
    titles = {
        inv.id: inv.title
        for inv in session.scalars(select(Investigation).where(Investigation.id.in_(inv_ids))).all()
    } if inv_ids else {}
    hits = []
    for entity in others:
        hits.append(
            {
                "key": entity.canonical_key,
                "name": entity.display_name,
                "case_id": entity.investigation_id,
                "case_title": titles.get(entity.investigation_id, entity.investigation_id[:8]),
            }
        )
    return hits[:40]


def parse_search(question: str) -> dict[str, Any]:
    q = (question or "").strip()
    low = q.lower()
    tokens = [t for t in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", low) if t not in _STOP]
    want_org = any(word in low for word in ("empresa", "empresas", "cnpj", "sociedade"))
    want_person = any(word in low for word in ("pessoa", "pessoas", "sócio", "socio", "administrador"))
    want_contract = any(word in low for word in ("contrato", "contratos", "municipal", "licitação", "licitacao"))
    want_change = any(word in low for word in ("mudança", "mudanca", "societária", "societaria", "alterou"))
    return {
        "tokens": tokens,
        "entity_type": "ORG" if want_org else ("PERSON" if want_person else None),
        "need_contract": want_contract,
        "need_change": want_change,
        "raw": q,
    }


def semantic_search(session: Session, investigation_id: str, question: str) -> list[dict[str, Any]]:
    spec = parse_search(question)
    stmt = select(Entity).where(Entity.investigation_id == investigation_id)
    if spec["entity_type"]:
        stmt = stmt.where(Entity.entity_type == spec["entity_type"])
    entities = list(session.scalars(stmt).all())
    tokens = spec["tokens"]
    hits = []
    for entity in entities:
        blob = f"{entity.display_name} {entity.canonical_key} {entity.attrs}".lower()
        score = sum(1 for tok in tokens if tok in blob)
        if spec["need_change"] and (entity.attrs or {}).get("papel"):
            score += 1
        if score or not tokens:
            hits.append(
                {
                    "id": entity.id,
                    "name": entity.display_name,
                    "type": entity.entity_type,
                    "score": score,
                    "key": entity.canonical_key,
                }
            )
    hits.sort(key=lambda row: -row["score"])
    return hits[:30]


def global_lookup(session: Session, query: str, *, user_id: str | None = None, limit: int = 40) -> dict[str, Any]:
    """Onde este identificador ou nome já apareceu: casos, nós e histórico."""
    text = (query or "").strip()
    seeds = extract_seeds(text)
    single = parse_seed(text)
    if single and all(single.canonical_key != item.canonical_key for item in seeds):
        seeds = [single, *seeds]
    keys = [item.canonical_key for item in seeds if item]
    like = f"%{text}%"
    clauses = []
    if keys:
        clauses.append(Entity.canonical_key.in_(keys))
    if text:
        clauses.append(Entity.display_name.ilike(like))
        clauses.append(Entity.canonical_key.ilike(like))
    entities: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if clauses:
        rows = session.execute(
            select(Entity, Investigation)
            .join(Investigation, Investigation.id == Entity.investigation_id)
            .where(Investigation.status != "DELETED", or_(*clauses))
            .order_by(Investigation.updated_at.desc())
            .limit(limit)
        ).all()
        for entity, inv in rows:
            mark = (inv.id, entity.canonical_key)
            if mark in seen:
                continue
            seen.add(mark)
            entities.append(
                {
                    "id": entity.id,
                    "name": entity.display_name,
                    "type": entity.entity_type,
                    "key": entity.canonical_key,
                    "case_id": inv.id,
                    "case_title": inv.title,
                    "status": inv.status,
                }
            )
    if keys:
        extra = session.execute(
            select(Identifier, Entity, Investigation)
            .join(Entity, Identifier.entity_id == Entity.id)
            .join(Investigation, Investigation.id == Entity.investigation_id)
            .where(Investigation.status != "DELETED", Identifier.canonical_key.in_(keys))
            .limit(limit)
        ).all()
        for ident, entity, inv in extra:
            mark = (inv.id, ident.canonical_key)
            if mark in seen:
                continue
            seen.add(mark)
            entities.append(
                {
                    "id": entity.id,
                    "name": entity.display_name,
                    "type": entity.entity_type,
                    "key": ident.canonical_key,
                    "case_id": inv.id,
                    "case_title": inv.title,
                    "status": inv.status,
                }
            )
    cases = []
    if text:
        for inv in session.scalars(
            select(Investigation)
            .where(
                Investigation.status != "DELETED",
                or_(Investigation.title.ilike(like), Investigation.hypothesis.ilike(like)),
            )
            .order_by(Investigation.updated_at.desc())
            .limit(16)
        ):
            cases.append({"id": inv.id, "title": inv.title, "hypothesis": inv.hypothesis or "", "status": inv.status})
    history = []
    if user_id and text:
        for row in session.scalars(
            select(SearchHistory)
            .where(SearchHistory.user_id == user_id, or_(SearchHistory.query.ilike(like), SearchHistory.title.ilike(like)))
            .order_by(SearchHistory.created_at.desc())
            .limit(16)
        ):
            history.append(
                {
                    "query": row.query,
                    "title": row.title or row.query,
                    "kind": row.kind,
                    "kind_label": seed_label(row.kind or row.mode),
                    "mode": row.mode,
                    "ok": row.ok,
                    "when": row.created_at.strftime("%d/%m %H:%M") if row.created_at else "",
                }
            )
    return {
        "query": text,
        "seeds": seed_cards(seeds),
        "entities": entities[:limit],
        "cases": cases,
        "history": history,
    }


def smart_alerts(session: Session, investigation_id: str) -> list[str]:
    from osint4all.quality.changes import recent_changes

    lines: list[str] = []
    for ch in recent_changes(session, investigation_id, limit=12):
        if ch.field == "entity":
            lines.append(f"Nova entidade no grafo: {ch.new_value}.")
        elif ch.field == "display_name":
            lines.append(f"Nome atualizado: {ch.old_value} → {ch.new_value}.")
        else:
            lines.append(f"{ch.field}: {ch.old_value or '—'} → {ch.new_value}.")
    for hit in anomalies(session, investigation_id)[:3]:
        lines.append(f"Cluster: {hit['title']}. {hit['note']}")
    return lines[:16]
