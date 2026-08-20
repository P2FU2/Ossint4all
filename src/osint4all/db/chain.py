"""Cadeia de consultas: cruza identificadores entre buscas do mesmo usuário."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, desc, select, update
from sqlalchemy.orm import Session

from osint4all.db.history import kind_label, replay_spec
from osint4all.db.models import SearchChain, SearchChainStep, User
from osint4all.identifiers import parse_seed

KEEP_CHAINS = 8
MAX_STEPS = 16
SHOW_FINDINGS = 10

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_AT_USER_RE = re.compile(r"(?<![A-Za-z0-9._%+-])@([A-Za-z0-9._-]{2,32})\b")

_GENERIC_HOSTS = frozenset(
    {
        "gmail.com",
        "google.com",
        "hotmail.com",
        "outlook.com",
        "yahoo.com",
        "icloud.com",
        "live.com",
        "msn.com",
        "proton.me",
        "protonmail.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "fb.com",
        "github.com",
        "linkedin.com",
        "tiktok.com",
        "youtube.com",
        "whatsapp.com",
        "t.me",
        "telegram.me",
        "gravatar.com",
        "googleusercontent.com",
        "minhareceita.org",
        "brasil.io",
        "truecaller.com",
    }
)

_GRAPH_KIND = {
    "EMAIL": "email",
    "USERNAME": "profile",
    "URL": "profile",
    "CNPJ": "org",
    "NAME": "person",
    "CPF": "person",
    "PHONE": "person",
    "PLATE": "vehicle",
    "CNJ": "org",
}

_SEED_KINDS = frozenset({"EMAIL", "USERNAME", "PHONE", "PLATE", "CPF", "CNPJ", "CNJ", "URL"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _add_ident(
    items: list[dict[str, str]],
    seen: set[str],
    kind: str,
    value: str,
    source: str,
) -> None:
    seed = parse_seed(value, forced_kind=kind or None)
    if not seed:
        return
    if seed.kind == "NAME" and " " not in (seed.display_name or "").strip():
        return
    if seed.kind == "URL":
        host = ""
        raw = seed.value or ""
        if "://" in raw:
            host = (urlparse(raw).hostname or "").lower().removeprefix("www.")
        else:
            host = raw.split("/")[0].lower().removeprefix("www.")
        if host in _GENERIC_HOSTS:
            return
    if seed.canonical_key in seen:
        return
    seen.add(seed.canonical_key)
    items.append(
        {
            "kind": seed.kind,
            "value": seed.display_name,
            "key": seed.canonical_key,
            "source": source,
        }
    )


def _scan_text(items: list[dict[str, str]], seen: set[str], text: str, source: str) -> None:
    blob = text or ""
    if not blob.strip():
        return
    for match in _EMAIL_RE.finditer(blob):
        _add_ident(items, seen, "EMAIL", match.group(0), source)
    stripped = _EMAIL_RE.sub(" ", blob)
    for match in _AT_USER_RE.finditer(stripped):
        _add_ident(items, seen, "USERNAME", match.group(1), source)


def _derive_bridges(items: list[dict[str, str]], seen: set[str], kind: str, query: str) -> None:
    if kind == "EMAIL" and "@" in (query or ""):
        local, _, _domain = query.partition("@")
        if local:
            _add_ident(items, seen, "USERNAME", local, "deriva")
    if kind == "USERNAME":
        _add_ident(items, seen, "USERNAME", query, "consulta")


def identifiers_from_outcome(outcome: object) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    parts = [outcome]
    extra = getattr(outcome, "parts", None)
    if extra:
        parts.extend(extra)
    for part in parts:
        kind = str(getattr(part, "kind", "") or "")
        query = str(getattr(part, "query", "") or "")
        if query:
            forced = kind if kind and kind not in {"massa", "FILE"} else None
            _add_ident(items, seen, forced or "", query, "consulta")
            _derive_bridges(items, seen, kind, query)
        for label, value in list(getattr(part, "facts", None) or [])[:12]:
            _add_ident(items, seen, "", str(value), "fato")
            _scan_text(items, seen, f"{label} {value}", "fato")
        for hit in list(getattr(part, "hits", None) or [])[:16]:
            _scan_text(items, seen, " ".join(filter(None, [getattr(hit, "title", ""), getattr(hit, "meta", ""), getattr(hit, "url", "") or ""])), "hit")
        for event in list(getattr(part, "timeline", None) or [])[:16]:
            _scan_text(items, seen, " ".join(filter(None, [getattr(event, "title", ""), getattr(event, "meta", "")])), "linha")
        graph = getattr(part, "graph", None)
        for node in list(getattr(graph, "nodes", None) or [])[:16]:
            _add_ident(items, seen, "", str(getattr(node, "label", "") or ""), "grafo")
            _scan_text(items, seen, str(getattr(node, "label", "") or ""), "grafo")
    derived = getattr(outcome, "derived", None)
    for kind, value in list(derived or [])[:8]:
        _add_ident(items, seen, str(kind), str(value), "deriva")
    return items


def slim_findings(outcome: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def push(title: str, meta: str = "", url: str = "") -> None:
        text = (title or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        rows.append({"title": text[:180], "meta": (meta or "")[:160], "url": url or ""})

    parts = getattr(outcome, "parts", None) or [outcome]
    if getattr(outcome, "parts", None) and getattr(outcome, "summary", None):
        push(str(outcome.summary))
    for part in parts:
        for label, value in list(getattr(part, "facts", None) or [])[:8]:
            push(f"{label}: {value}")
        for hit in list(getattr(part, "hits", None) or [])[:8]:
            push(str(getattr(hit, "title", "") or ""), str(getattr(hit, "meta", "") or ""), str(getattr(hit, "url", "") or ""))
        for event in list(getattr(part, "timeline", None) or [])[:6]:
            push(str(getattr(event, "title", "") or ""), str(getattr(event, "meta", "") or ""), str(getattr(event, "url", "") or ""))
    return rows[:20]


def _keys(idents: list[dict[str, str]] | None) -> set[str]:
    return {str(item.get("key") or "") for item in (idents or []) if item.get("key")}


def _link_label(shared: set[str], idents: list[dict[str, str]]) -> str:
    by_key = {item["key"]: item for item in idents if item.get("key")}
    for key in shared:
        item = by_key.get(key)
        if not item:
            continue
        if item["kind"] == "USERNAME":
            return f"@{item['value'].lstrip('@')}"
        return str(item["value"])
    return "identificador comum"


def _chain_steps(session: Session, chain_id: str) -> list[SearchChainStep]:
    return list(
        session.scalars(
            select(SearchChainStep)
            .where(SearchChainStep.chain_id == chain_id)
            .order_by(SearchChainStep.created_at)
        )
    )


def _prune_chains(session: Session, user: User) -> None:
    old_ids = list(
        session.scalars(
            select(SearchChain.id)
            .where(SearchChain.user_id == user.id)
            .order_by(desc(SearchChain.updated_at))
            .offset(KEEP_CHAINS)
        )
    )
    if old_ids:
        session.execute(delete(SearchChainStep).where(SearchChainStep.chain_id.in_(old_ids)))
        session.execute(delete(SearchChain).where(SearchChain.id.in_(old_ids)))


def active_chain(session: Session, user: User) -> SearchChain | None:
    return session.scalar(
        select(SearchChain)
        .where(SearchChain.user_id == user.id, SearchChain.active.is_(True))
        .order_by(desc(SearchChain.updated_at))
        .limit(1)
    )


def reset_chain(session: Session, user: User) -> None:
    session.execute(update(SearchChain).where(SearchChain.user_id == user.id, SearchChain.active.is_(True)).values(active=False))


def ingest_outcome(session: Session, user: User, outcome: object) -> SearchChain | None:
    if not bool(getattr(outcome, "ok", True)):
        return active_chain(session, user)
    query = str(getattr(outcome, "query", "") or "").strip()
    if not query:
        return active_chain(session, user)
    idents = identifiers_from_outcome(outcome)
    if not idents:
        return active_chain(session, user)
    kind = str(getattr(outcome, "kind", "") or "")
    title = str(getattr(outcome, "title", "") or query)
    summary = str(getattr(outcome, "summary", "") or "")
    keys = _keys(idents)

    chains = list(
        session.scalars(
            select(SearchChain)
            .where(SearchChain.user_id == user.id)
            .order_by(desc(SearchChain.updated_at))
            .limit(KEEP_CHAINS)
        )
    )
    matched: SearchChain | None = None
    for chain in chains:
        for step in _chain_steps(session, chain.id):
            if _keys(step.identifiers) & keys:
                matched = chain
                break
        if matched:
            break

    if matched is None:
        reset_chain(session, user)
        matched = SearchChain(user_id=user.id, title=f"Cadeia · {title}"[:255], active=True)
        session.add(matched)
        session.flush()
    else:
        session.execute(update(SearchChain).where(SearchChain.user_id == user.id, SearchChain.id != matched.id).values(active=False))
        matched.active = True
        matched.updated_at = _now()

    existing = _chain_steps(session, matched.id)
    if existing:
        last = existing[-1]
        if _same_query(last.query, query) and (last.kind or "") == kind:
            last.identifiers = idents
            last.findings = slim_findings(outcome)
            last.summary = summary[:400]
            last.title = title[:255]
            last.ok = True
            return matched
        if len(existing) >= MAX_STEPS:
            oldest = existing[0]
            session.delete(oldest)

    session.add(
        SearchChainStep(
            chain_id=matched.id,
            kind=kind[:32],
            query=query[:512],
            title=title[:255],
            summary=summary[:400],
            ok=True,
            identifiers=idents,
            findings=slim_findings(outcome),
        )
    )
    _prune_chains(session, user)
    session.flush()
    return matched


def chain_seeds(session: Session, chain: SearchChain) -> list:
    seeds = []
    seen: set[str] = set()
    for step in _chain_steps(session, chain.id):
        primary = parse_seed(step.query, forced_kind=step.kind or None)
        candidates = [primary] if primary else []
        for item in step.identifiers or []:
            if item.get("kind") not in _SEED_KINDS:
                continue
            seed = parse_seed(str(item.get("value") or ""), forced_kind=str(item.get("kind") or None))
            if seed:
                candidates.append(seed)
        for seed in candidates:
            if seed.canonical_key in seen:
                continue
            seen.add(seed.canonical_key)
            seeds.append(seed)
    return seeds


def _same_query(stored: str, current: str) -> bool:
    left = (stored or "").strip().casefold()
    right = (current or "").strip().casefold()
    if not right:
        return False
    if left == right:
        return True
    a = parse_seed(stored)
    b = parse_seed(current)
    return bool(a and b and a.canonical_key == b.canonical_key)


def chain_view(session: Session, user: User, *, current_query: str = "") -> dict[str, Any] | None:
    chain = active_chain(session, user)
    if not chain:
        return None
    steps = _chain_steps(session, chain.id)
    if not steps:
        return None
    needle = (current_query or "").strip()
    view_steps: list[dict[str, Any]] = []
    all_findings: list[dict[str, str]] = []
    seen_findings: set[str] = set()
    prev_keys: set[str] = set()
    shared_labels: list[str] = []
    for index, step in enumerate(steps):
        keys = _keys(step.identifiers)
        shared = keys & prev_keys
        link = _link_label(shared, step.identifiers) if shared else ""
        if link:
            shared_labels.append(link)
        stamp = step.created_at.strftime("%d/%m %H:%M") if step.created_at else ""
        findings = list(step.findings or [])[:SHOW_FINDINGS]
        for item in findings:
            title = str(item.get("title") or "")
            if title and title not in seen_findings:
                seen_findings.add(title)
                all_findings.append(item)
        spec = replay_spec(step.kind, step.kind)
        view_steps.append(
            {
                "id": step.id,
                "kind": step.kind,
                "kind_label": kind_label(step.kind),
                "query": step.query,
                "title": step.title or step.query,
                "summary": step.summary,
                "when": stamp,
                "ok": step.ok,
                "link": link,
                "findings": findings,
                "is_current": _same_query(step.query, needle),
                "index": index + 1,
                "action": spec["action"],
                "tool": spec["tool"],
                "mode": spec["mode"],
            }
        )
        prev_keys = keys

    nodes = []
    edges = []
    for item in view_steps:
        nodes.append(
            {
                "id": item["id"],
                "label": item["query"],
                "kind": _GRAPH_KIND.get(item["kind"], "person"),
                "meta": item["kind_label"],
            }
        )
    for prev, nxt in zip(view_steps, view_steps[1:], strict=False):
        edges.append(
            {
                "source": prev["id"],
                "target": nxt["id"],
                "label": nxt["link"] or "seguinte",
                "explain": f"Cruza com {nxt['link']}" if nxt["link"] else "Consulta seguinte nesta cadeia.",
            }
        )
    linked = len(view_steps) > 1
    chips: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for step in steps:
        for ident in step.identifiers or []:
            key = str(ident.get("key") or "")
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            value = str(ident.get("value") or "")
            kind = str(ident.get("kind") or "")
            chips.append(
                {
                    "kind": kind,
                    "kind_label": kind_label(kind),
                    "value": value,
                    "label": f"@{value.lstrip('@')}" if kind == "USERNAME" else value,
                }
            )
    export_lines = [chain.title or "Cadeia", ""]
    for step in view_steps:
        export_lines.append(f"{step['index']}. [{step['kind_label']}] {step['query']}")
        if step["link"]:
            export_lines.append(f"   cruza em {step['link']}")
        if step["summary"]:
            export_lines.append(f"   {step['summary']}")
        for item in step["findings"][:6]:
            export_lines.append(f"   - {item.get('title') or ''}")
    if chips:
        export_lines.append("")
        export_lines.append("Identificadores: " + ", ".join(c["label"] for c in chips))
    return {
        "id": chain.id,
        "title": chain.title,
        "linked": linked,
        "shared": list(dict.fromkeys(shared_labels)),
        "steps": view_steps,
        "findings": all_findings[:16],
        "just_linked": linked and bool(needle) and view_steps[-1]["is_current"],
        "idents": chips[:20],
        "export": "\n".join(export_lines).strip(),
        "graph_payload": {
            "nodes": nodes,
            "edges": edges,
            "caption": (
                f"Cadeia com {len(view_steps)} consultas. "
                + (f"Nó de ligação: {', '.join(dict.fromkeys(shared_labels))}." if shared_labels else "Ainda um ponto só — o próximo identificador relacionado entra aqui.")
            ),
        }
        if linked
        else None,
    }
