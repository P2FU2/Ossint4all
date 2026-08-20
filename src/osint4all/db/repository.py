"""Helpers de persistência do grafo."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from osint4all.db.models import (
    BlockedKey,
    CaseComment,
    CaseEvent,
    CaseNote,
    CaseSnapshot,
    CaseTask,
    ChangeLog,
    Claim,
    ClaimApproval,
    Edge,
    Entity,
    EntityVersion,
    Evidence,
    ExpansionJob,
    HostIntel,
    Hypothesis,
    HypothesisStance,
    Identifier,
    Investigation,
    NegativeFinding,
    PlaybookItem,
    QueryLog,
    ResearchPlan,
    VerificationRecord,
)
from osint4all.graph.identity import (
    MAX_GRAPH_DEPTH,
    TargetProfile,
    collapse_name,
    entity_status,
    has_expandable_anchor,
    is_active_node,
    is_weak_name,
    names_match,
    profile_from_fields,
)
from osint4all.security import only_digits
from osint4all.identifiers import STRONG_ID_KINDS

EDGE_REL_TYPES = (
    "SOCIO",
    "ADMIN",
    "MENCAO",
    "ANOTACAO",
    "RELACIONADO",
    "SETA",
    "HIPOTESE",
    "PROPRIETARIO",
    "CANDIDATO",
    "SAME_AS",
    "PARTE",
    "PAI",
    "MAE",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


CASE_ID_LABELS = {
    "NAME": "Nome",
    "CPF": "CPF",
    "CNPJ": "CNPJ",
    "EMAIL": "E-mail",
    "PHONE": "Telefone",
    "USERNAME": "Usuário",
    "PLATE": "Placa",
    "CNJ": "Processo",
    "BIRTHDATE": "Nascimento",
    "FATHER": "Pai",
    "MOTHER": "Mãe",
    "URL": "URL",
}
_TARGET_FIELD_KINDS = frozenset(
    {"NAME", "CPF", "CNPJ", "EMAIL", "PHONE", "USERNAME", "PLATE", "CNJ", "BIRTHDATE"}
)


def case_known_keys(session: Session, investigation_id: str) -> set[str]:
    keys: set[str] = set()
    entities = session.scalars(
        select(Entity).options(selectinload(Entity.identifiers)).where(Entity.investigation_id == investigation_id)
    ).all()
    for entity in entities:
        if entity.canonical_key:
            keys.add(entity.canonical_key)
        for ident in entity.identifiers:
            if ident.canonical_key:
                keys.add(ident.canonical_key)
    return keys


def case_identifiers(session: Session, investigation_id: str) -> list[dict[str, Any]]:
    """Identificadores já no caso, para o dossiê de edição."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    entities = session.scalars(
        select(Entity).options(selectinload(Entity.identifiers)).where(Entity.investigation_id == investigation_id)
    ).all()
    for entity in entities:
        rows = [(ident.kind, ident.value, ident.canonical_key) for ident in entity.identifiers]
        if not rows and entity.canonical_key:
            prefix = entity.canonical_key.split(":", 1)[0].upper()
            rows = [(prefix if prefix in CASE_ID_LABELS else entity.entity_type, entity.display_name, entity.canonical_key)]
        for kind, value, key in rows:
            key = key or f"{kind}:{value}"
            if key in seen:
                continue
            seen.add(key)
            kind = str(kind or "").upper()
            grouped.setdefault(kind, []).append(
                {
                    "kind": kind,
                    "label": CASE_ID_LABELS.get(kind, kind),
                    "value": value,
                    "seed": bool(entity.is_seed),
                }
            )
    order = list(CASE_ID_LABELS)
    out: list[dict[str, Any]] = []
    for kind in order + [k for k in grouped if k not in order]:
        for item in grouped.get(kind, []):
            out.append(item)
    return out


def case_target_fields(session: Session, investigation_id: str) -> dict[str, str]:
    """Nome, CPF e demais âncoras do alvo (semente primeiro)."""
    fields: dict[str, str] = {}
    entities = session.scalars(
        select(Entity)
        .options(selectinload(Entity.identifiers))
        .where(Entity.investigation_id == investigation_id)
        .order_by(Entity.is_seed.desc(), Entity.depth, Entity.display_name)
    ).all()
    for entity in entities:
        attrs = entity.attrs or {}
        if entity.is_seed and entity.entity_type == "PERSON":
            name = (entity.display_name or "").strip()
            if name.count(" ") >= 1:
                fields.setdefault("NAME", name)
            if attrs.get("nascimento"):
                fields.setdefault("BIRTHDATE", str(attrs["nascimento"]))
            if attrs.get("nome_pai"):
                fields.setdefault("FATHER", str(attrs["nome_pai"]))
            if attrs.get("nome_mae"):
                fields.setdefault("MOTHER", str(attrs["nome_mae"]))
        for ident in entity.identifiers or []:
            kind = str(ident.kind or "").upper()
            value = str(ident.value or "").strip()
            if kind in _TARGET_FIELD_KINDS and value:
                fields.setdefault(kind, value)
        key = str(entity.canonical_key or "")
        if key.startswith("cpf:") and "CPF" not in fields:
            fields["CPF"] = key.split(":", 1)[1]
        if key.startswith("cnpj:") and "CNPJ" not in fields:
            fields["CNPJ"] = key.split(":", 1)[1]
    return fields


def case_target_profile(session: Session, investigation_id: str) -> TargetProfile:
    return profile_from_fields(case_target_fields(session, investigation_id))


def seed_entity_ids(session: Session, investigation_id: str) -> set[str]:
    rows = session.scalars(
        select(Entity.id).where(Entity.investigation_id == investigation_id, Entity.is_seed.is_(True))
    ).all()
    ids = {str(item) for item in rows}
    if ids:
        return ids
    fallback = session.scalars(
        select(Entity.id).where(Entity.investigation_id == investigation_id, Entity.depth == 0)
    ).all()
    return {str(item) for item in fallback}


def _undirected_adj(session: Session, investigation_id: str) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for edge in session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)):
        src, dst = str(edge.from_entity_id), str(edge.to_entity_id)
        adj.setdefault(src, set()).add(dst)
        adj.setdefault(dst, set()).add(src)
    return adj


def _bfs_ids(starts: set[str], adj: dict[str, set[str]], *, blocked: set[str] | None = None) -> set[str]:
    blocked = blocked or set()
    seen: set[str] = set()
    stack = [item for item in starts if item not in blocked]
    while stack:
        cur = stack.pop()
        if cur in seen or cur in blocked:
            continue
        seen.add(cur)
        for nxt in adj.get(cur, ()):
            if nxt not in seen and nxt not in blocked:
                stack.append(nxt)
    return seen


def linked_entity_ids(session: Session, investigation_id: str) -> set[str]:
    seeds = seed_entity_ids(session, investigation_id)
    if not seeds:
        return set()
    return _bfs_ids(seeds, _undirected_adj(session, investigation_id))


def derived_entity_ids(session: Session, investigation_id: str, root_id: str) -> set[str]:
    """Nós que só existem neste caso porque passam pelo `root_id`."""
    adj = _undirected_adj(session, investigation_id)
    keep = seed_entity_ids(session, investigation_id) - {root_id}
    from_root = _bfs_ids({root_id}, adj)
    from_keep = _bfs_ids(keep, adj, blocked={root_id}) if keep else set()
    return (from_root - from_keep) | {root_id}


def prune_unlinked_entities(session: Session, investigation_id: str) -> int:
    """Tira pessoas/empresas que não têm caminho até o alvo."""
    linked = linked_entity_ids(session, investigation_id)
    seeds = seed_entity_ids(session, investigation_id)
    if not seeds:
        return 0
    removed = 0
    for entity in list(session.scalars(select(Entity).where(Entity.investigation_id == investigation_id))):
        if entity.id in linked or entity.id in seeds or entity.is_seed:
            continue
        if entity.entity_type not in {"PERSON", "ORG"}:
            continue
        _delete_entity_local(session, investigation_id, entity, block=False)
        removed += 1
    return removed


def get_investigation(session: Session, investigation_id: str) -> Investigation | None:
    return session.get(Investigation, investigation_id)


def find_entity_by_key(session: Session, investigation_id: str, canonical_key: str) -> Entity | None:
    key = (canonical_key or "").strip()
    if not key:
        return None
    entity = session.scalar(
        select(Entity).where(
            Entity.investigation_id == investigation_id,
            Entity.canonical_key == key,
        )
    )
    if entity:
        return entity
    ident = session.scalar(select(Identifier).where(Identifier.canonical_key == key))
    if not ident:
        return None
    other = session.get(Entity, ident.entity_id)
    if other and other.investigation_id == investigation_id:
        return other
    return None


_FOLD_PREFIXES = ("cpf:", "email:", "phone:", "username:")
_CARD_ID_KINDS = ("CPF", "EMAIL", "PHONE", "USERNAME", "BIRTHDATE", "CNPJ", "PLATE", "CNJ")


def person_cpf(entity: Entity) -> str:
    key = str(entity.canonical_key or "")
    if key.startswith("cpf:"):
        digits = only_digits(key.split(":", 1)[1])
        return digits if len(digits) == 11 else ""
    for ident in entity.identifiers or []:
        if str(ident.kind or "").upper() == "CPF":
            digits = only_digits(ident.value)
            if len(digits) == 11:
                return digits
    return ""


def find_person_by_name(session: Session, investigation_id: str, name: str) -> Entity | None:
    if is_weak_name(name):
        return None
    people = session.scalars(
        select(Entity)
        .options(selectinload(Entity.identifiers))
        .where(Entity.investigation_id == investigation_id, Entity.entity_type == "PERSON")
    ).all()
    hits = [row for row in people if names_match(row.display_name, name)]
    if not hits:
        return None
    hits.sort(key=lambda row: (not row.is_seed, 0 if person_cpf(row) else 1, row.depth or 0))
    return hits[0]


def absorb_entity(session: Session, investigation_id: str, keeper: Entity, extra: Entity) -> None:
    """Junta o nó extra no keeper: identificadores, arestas e evidências."""
    if not keeper or not extra or keeper.id == extra.id:
        return
    if extra.is_seed:
        keeper.is_seed = True
    if extra.depth is not None and (keeper.depth or 0) > extra.depth:
        keeper.depth = extra.depth
    keeper.confidence = max(keeper.confidence or 0, extra.confidence or 0)
    extra_key = str(extra.canonical_key or "")
    if extra_key and extra_key != str(keeper.canonical_key or ""):
        extra.canonical_key = f"absorbed:{extra.id}"
        session.flush()
        prefix = extra_key.split(":", 1)[0].upper()
        if prefix in _CARD_ID_KINDS:
            add_identifier(keeper, prefix, extra.display_name or extra_key, extra_key)
        if extra_key.startswith("cpf:") and not str(keeper.canonical_key or "").startswith("cpf:"):
            keeper.canonical_key = extra_key
    if extra.display_name and (
        not keeper.display_name
        or keeper.display_name == keeper.canonical_key
        or (len(extra.display_name) > len(keeper.display_name) and " " in extra.display_name)
    ):
        keeper.display_name = extra.display_name
    attrs = dict(keeper.attrs or {})
    for key, value in (extra.attrs or {}).items():
        if value not in (None, "") and key not in attrs:
            attrs[key] = value
    if extra_key.startswith("username:"):
        attrs.setdefault("username", extra.display_name)
    keeper.attrs = attrs
    for ident in list(extra.identifiers or []):
        add_identifier(keeper, ident.kind, ident.value, ident.canonical_key)
    edges = list(
        session.scalars(
            select(Edge).where(
                Edge.investigation_id == investigation_id,
                or_(Edge.from_entity_id == extra.id, Edge.to_entity_id == extra.id),
            )
        )
    )
    for edge in edges:
        src = keeper.id if edge.from_entity_id == extra.id else edge.from_entity_id
        dst = keeper.id if edge.to_entity_id == extra.id else edge.to_entity_id
        session.delete(edge)
        session.flush()
        if src == dst:
            continue
        exists = session.scalar(
            select(Edge).where(
                Edge.investigation_id == investigation_id,
                Edge.from_entity_id == src,
                Edge.to_entity_id == dst,
                Edge.rel_type == edge.rel_type,
            )
        )
        if exists:
            continue
        session.add(
            Edge(
                investigation_id=investigation_id,
                from_entity_id=src,
                to_entity_id=dst,
                rel_type=edge.rel_type,
                confidence=edge.confidence,
                attrs=dict(edge.attrs or {}),
                source_connector=edge.source_connector,
            )
        )
    session.execute(update(Evidence).where(Evidence.entity_id == extra.id).values(entity_id=keeper.id))
    session.flush()
    _delete_entity_local(session, investigation_id, extra, block="#cand:" in extra_key)


def consolidate_identities(session: Session, investigation_id: str) -> int:
    """Uma pessoa = um bloco. CPF/@user/e-mail/telefone entram no cartão, sem nó solto."""
    merged = 0
    entities = list(
        session.scalars(
            select(Entity)
            .options(selectinload(Entity.identifiers))
            .where(Entity.investigation_id == investigation_id)
        )
    )
    people = [row for row in entities if row.entity_type == "PERSON"]
    named = [
        row
        for row in people
        if not is_weak_name(row.display_name) and not str(row.canonical_key or "").startswith(("father:", "mother:"))
    ]
    named_seeds = [row for row in named if row.is_seed]
    seed_person = next((row for row in named_seeds if person_cpf(row)), None)
    if seed_person is None and len(named_seeds) == 1:
        seed_person = named_seeds[0]
    if seed_person is None and len(named) == 1:
        seed_person = named[0]

    for row in list(entities):
        key = str(row.canonical_key or "")
        if not key.startswith(_FOLD_PREFIXES) or row.entity_type not in {"PERSON", "PROFILE"}:
            continue
        host = None
        if key.startswith("cpf:"):
            digits = only_digits(key.split(":", 1)[1])
            host = next((p for p in people if p.id != row.id and person_cpf(p) == digits), None)
            if host is None and len(named) == 1:
                host = named[0]
        else:
            host = seed_person
        if host is None or host.id == row.id:
            continue
        absorb_entity(session, investigation_id, host, row)
        merged += 1

    people = list(
        session.scalars(
            select(Entity)
            .options(selectinload(Entity.identifiers))
            .where(Entity.investigation_id == investigation_id, Entity.entity_type == "PERSON")
        )
    )
    groups: dict[str, list[Entity]] = {}
    for row in people:
        if is_weak_name(row.display_name):
            continue
        groups.setdefault(collapse_name(row.display_name), []).append(row)
    for group in groups.values():
        if len(group) < 2:
            continue
        by_cpf: dict[str, list[Entity]] = {}
        nameless: list[Entity] = []
        for row in group:
            digits = person_cpf(row)
            if digits:
                by_cpf.setdefault(digits, []).append(row)
            else:
                nameless.append(row)
        buckets = list(by_cpf.values())
        if len(by_cpf) == 1:
            buckets[0].extend(nameless)
        elif not by_cpf:
            buckets = [nameless]
        else:
            buckets.append(nameless)
        for bucket in buckets:
            if len(bucket) < 2:
                continue
            bucket.sort(key=lambda row: (not row.is_seed, 0 if person_cpf(row) else 1, row.depth or 0))
            keeper = bucket[0]
            for extra in bucket[1:]:
                absorb_entity(session, investigation_id, keeper, extra)
                merged += 1
    return merged


def enqueue_expand(
    session: Session,
    *,
    investigation: Investigation,
    entity: Entity,
    depth: int,
    max_attempts: int = 3,
    force: bool = False,
) -> ExpansionJob | None:
    existing = session.scalar(
        select(ExpansionJob).where(
            ExpansionJob.investigation_id == investigation.id,
            ExpansionJob.entity_id == entity.id,
            ExpansionJob.job_type == "EXPAND",
            ExpansionJob.status.in_(("PENDING", "RUNNING")),
        )
    )
    if existing:
        return existing
    done = session.scalar(
        select(ExpansionJob).where(
            ExpansionJob.investigation_id == investigation.id,
            ExpansionJob.entity_id == entity.id,
            ExpansionJob.job_type == "EXPAND",
            ExpansionJob.status == "DONE",
        )
    )
    if done and not force:
        return None
    job = ExpansionJob(
        investigation_id=investigation.id,
        entity_id=entity.id,
        depth=depth,
        max_attempts=max_attempts,
    )
    session.add(job)
    return job


def enqueue_qsa_network(session: Session, investigation: Investigation, *, max_attempts: int = 3) -> int:
    """Enfileira só âncoras ativas ligadas ao alvo — sem homônimo solto no grafo."""
    investigation.max_depth = max(investigation.max_depth or 0, MAX_GRAPH_DEPTH)
    prune_unlinked_entities(session, investigation.id)
    linked = linked_entity_ids(session, investigation.id)
    queued = 0
    entities = session.scalars(select(Entity).where(Entity.investigation_id == investigation.id)).all()
    for entity in entities:
        if linked and entity.id not in linked and not entity.is_seed:
            continue
        if not is_active_node(entity):
            continue
        if not has_expandable_anchor(entity):
            continue
        force = entity.entity_type == "ORG" or entity.canonical_key.startswith(("cnpj:", "cpf:"))
        job = enqueue_expand(
            session,
            investigation=investigation,
            entity=entity,
            depth=entity.depth,
            max_attempts=max_attempts,
            force=force,
        )
        if job:
            queued += 1
    return queued


def claim_next_job(session: Session, *, investigation_id: str | None = None) -> ExpansionJob | None:
    stmt = select(ExpansionJob).where(ExpansionJob.status == "PENDING").order_by(ExpansionJob.created_at)
    if investigation_id:
        stmt = stmt.where(ExpansionJob.investigation_id == investigation_id)
    bind = session.get_bind()
    if bind is not None and getattr(bind.dialect, "name", "") == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = session.scalars(stmt.limit(1)).first()
    if not job:
        return None
    job.status = "RUNNING"
    job.started_at = utcnow()
    job.attempt_count = (job.attempt_count or 0) + 1
    session.flush()
    return job


def job_counts(session: Session, investigation_id: str) -> dict[str, int]:
    rows = session.execute(
        select(ExpansionJob.status, ExpansionJob.id).where(
            ExpansionJob.investigation_id == investigation_id
        )
    ).all()
    counts = {"PENDING": 0, "RUNNING": 0, "DONE": 0, "FAILED": 0, "TOTAL": len(rows)}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts


def graph_counts(session: Session, investigation_id: str) -> dict[str, int]:
    entities = session.scalar(select(func.count()).select_from(Entity).where(Entity.investigation_id == investigation_id)) or 0
    edges = session.scalar(select(func.count()).select_from(Edge).where(Edge.investigation_id == investigation_id)) or 0
    return {"entities": int(entities), "edges": int(edges)}


def requeue_stale_running_jobs(session: Session, investigation_id: str, *, older_than: int = 90) -> int:
    """RUNNING órfão (aba fechada / timeout) volta para a fila."""
    cutoff = utcnow() - timedelta(seconds=max(15, older_than))
    rows = list(
        session.scalars(
            select(ExpansionJob).where(
                ExpansionJob.investigation_id == investigation_id,
                ExpansionJob.status == "RUNNING",
            )
        )
    )
    changed = 0
    for job in rows:
        started = job.started_at
        if started is None:
            job.status = "PENDING"
            changed += 1
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if started > cutoff:
            continue
        if (job.attempt_count or 0) >= (job.max_attempts or 3):
            job.status = "FAILED"
            job.last_error = (job.last_error or "interrompido")[:400]
            job.finished_at = utcnow()
        else:
            job.status = "PENDING"
            job.started_at = None
        changed += 1
    if changed:
        session.flush()
    return changed


def add_identifier(entity: Entity, kind: str, value: str, canonical_key: str) -> Identifier:
    for existing in entity.identifiers:
        if existing.canonical_key == canonical_key:
            return existing
    ident = Identifier(
        entity_id=entity.id,
        kind=kind,
        value=value,
        canonical_key=canonical_key,
        strong=kind in STRONG_ID_KINDS,
    )
    entity.identifiers.append(ident)
    return ident


def _card_ids(entity: Entity) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for ident in entity.identifiers or []:
        kind = str(ident.kind or "").upper()
        if kind not in _CARD_ID_KINDS:
            continue
        key = ident.canonical_key or f"{kind}:{ident.value}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "value": str(ident.value or ""), "key": key})
    key = str(entity.canonical_key or "")
    prefix = key.split(":", 1)[0].upper() if ":" in key else ""
    if prefix in _CARD_ID_KINDS and key not in seen:
        out.insert(0, {"kind": prefix, "value": entity.display_name, "key": key})
    return out


def collapse_graph_view(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """No desenho: mesma pessoa vira um bloco; CPF/@user entram no cartão."""
    alias: dict[str, str] = {}
    people = [n for n in nodes if n.get("type") == "PERSON"]
    named = [n for n in people if not is_weak_name(str(n.get("label") or ""))]
    seed = next((n for n in named if n.get("seed")), None) or (named[0] if len(named) == 1 else None)

    def cpf_of(node: dict[str, Any]) -> str:
        key = str(node.get("key") or "")
        if key.startswith("cpf:"):
            return only_digits(key.split(":", 1)[1])
        for item in node.get("ids") or []:
            if str(item.get("kind") or "").upper() == "CPF":
                return only_digits(str(item.get("value") or ""))
        return ""

    for node in nodes:
        key = str(node.get("key") or "")
        if not key.startswith(_FOLD_PREFIXES) or node.get("type") not in {"PERSON", "PROFILE"}:
            continue
        host = seed
        if key.startswith("cpf:"):
            digits = only_digits(key.split(":", 1)[1])
            host = next((p for p in people if p["id"] != node["id"] and cpf_of(p) == digits), host)
        if host and host["id"] != node["id"]:
            alias[node["id"]] = host["id"]
            have = {(i.get("kind"), i.get("value")) for i in (host.get("ids") or [])}
            extra = [i for i in (node.get("ids") or []) if (i.get("kind"), i.get("value")) not in have]
            host["ids"] = list(host.get("ids") or []) + extra
            if node.get("seed"):
                host["seed"] = True

    groups: dict[str, list[dict[str, Any]]] = {}
    for node in people:
        if node["id"] in alias or is_weak_name(str(node.get("label") or "")):
            continue
        groups.setdefault(collapse_name(str(node.get("label") or "")), []).append(node)
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda n: (not n.get("seed"), 0 if cpf_of(n) else 1, n.get("depth") or 0))
        cpfs = {cpf_of(n) for n in group if cpf_of(n)}
        if len(cpfs) > 1:
            continue
        keeper = group[0]
        for extra in group[1:]:
            alias[extra["id"]] = keeper["id"]
            have = {(i.get("kind"), i.get("value")) for i in (keeper.get("ids") or [])}
            keeper["ids"] = list(keeper.get("ids") or []) + [
                i for i in (extra.get("ids") or []) if (i.get("kind"), i.get("value")) not in have
            ]
            if extra.get("seed"):
                keeper["seed"] = True

    if not alias:
        return nodes, links
    kept = [n for n in nodes if n["id"] not in alias]
    rewritten = []
    seen_edge: set[tuple[str, str, str]] = set()
    for link in links:
        src = alias.get(link["source"], link["source"])
        dst = alias.get(link["target"], link["target"])
        if src == dst:
            continue
        mark = (src, dst, str(link.get("type") or ""))
        if mark in seen_edge:
            continue
        seen_edge.add(mark)
        item = dict(link)
        item["source"] = src
        item["target"] = dst
        rewritten.append(item)
    return kept, rewritten


def graph_payload(session: Session, investigation_id: str) -> dict[str, Any]:
    entities = session.scalars(
        select(Entity).options(selectinload(Entity.identifiers)).where(Entity.investigation_id == investigation_id)
    ).all()
    edges = session.scalars(select(Edge).where(Edge.investigation_id == investigation_id)).all()
    nodes = [
        {
            "id": e.id,
            "label": e.display_name,
            "type": e.entity_type,
            "seed": e.is_seed,
            "depth": e.depth,
            "confidence": e.confidence,
            "key": e.canonical_key,
            "status": entity_status(e),
            "ids": _card_ids(e),
            "attrs": {
                k: e.attrs.get(k)
                for k in (
                    "razao_social",
                    "situacao",
                    "municipio",
                    "uf",
                    "cnae",
                    "simples",
                    "mei",
                    "lat",
                    "lng",
                    "cep",
                    "endereco",
                    "capital_social",
                    "porte",
                    "nota",
                    "motivo",
                    "papel",
                    "nome",
                    "kind",
                    "nascimento",
                    "nome_pai",
                    "nome_mae",
                    "username",
                )
                if e.attrs and e.attrs.get(k) not in (None, "", [])
            },
        }
        for e in entities
    ]
    from osint4all.engines.knowledge import annotate_edge

    links = []
    for edge in edges:
        info = annotate_edge(edge)
        links.append(
            {
                "id": edge.id,
                "source": edge.from_entity_id,
                "target": edge.to_entity_id,
                "type": edge.rel_type,
                "confidence": edge.confidence,
                "note": (edge.attrs or {}).get("nota") or "",
                "source_connector": edge.source_connector or "",
                "grau": (edge.attrs or {}).get("grau"),
                "strength": info["strength"],
                "period": info["period"],
                "year": info["year"],
            }
        )
    nodes, links = collapse_graph_view(nodes, links)
    years = sorted({int(link["year"]) for link in links if link.get("year")})
    inv = session.get(Investigation, investigation_id)
    return {
        "nodes": nodes,
        "edges": links,
        "entity_count": len(nodes),
        "edge_count": len(links),
        "years": years,
        "layout": dict(inv.graph_layout or {}) if inv else {},
    }


def save_graph_layout(session: Session, investigation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Guarda posições, zoom e vista da rede no caso — vale em qualquer dispositivo."""
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return None
    known = set(session.scalars(select(Entity.id).where(Entity.investigation_id == investigation_id)))
    nodes: dict[str, dict[str, float]] = {}
    raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), dict) else {}
    for entity_id, pos in raw_nodes.items():
        if entity_id not in known or not isinstance(pos, dict):
            continue
        try:
            x = float(pos.get("x"))
            y = float(pos.get("y"))
        except (TypeError, ValueError):
            continue
        if not (-1_000_000 < x < 1_000_000 and -1_000_000 < y < 1_000_000):
            continue
        nodes[str(entity_id)] = {"x": round(x, 2), "y": round(y, 2)}
        if len(nodes) >= 2500:
            break
    view = payload.get("view") if payload.get("view") in {"rede", "arvore", "split", "mapa"} else "rede"
    try:
        zoom = float(payload.get("zoom"))
    except (TypeError, ValueError):
        zoom = 1.0
    zoom = max(0.15, min(2.4, zoom))
    pan = payload.get("pan") if isinstance(payload.get("pan"), dict) else {}
    try:
        pan_x = float(pan.get("x") or 0)
        pan_y = float(pan.get("y") or 0)
    except (TypeError, ValueError):
        pan_x, pan_y = 0.0, 0.0
    raw_map = payload.get("map") if isinstance(payload.get("map"), dict) else {}
    map_view: dict[str, float] = {}
    try:
        if raw_map:
            map_view = {
                "zoom": float(raw_map.get("zoom") or 4),
                "lat": float(raw_map.get("lat")),
                "lng": float(raw_map.get("lng")),
            }
    except (TypeError, ValueError):
        map_view = {}
    layout = {
        "view": view,
        "zoom": round(zoom, 4),
        "pan": {"x": round(pan_x, 2), "y": round(pan_y, 2)},
        "nodes": nodes,
        "locked": True,
    }
    if map_view:
        layout["map"] = map_view
    inv.graph_layout = layout
    return layout


def _delete_entity_local(session: Session, investigation_id: str, entity: Entity, *, block: bool = True) -> None:
    if block:
        block_key(session, investigation_id, entity.canonical_key)
    entity_id = entity.id
    ev_ids = list(session.scalars(select(Evidence.id).where(Evidence.entity_id == entity_id)))
    if ev_ids:
        session.execute(delete(HypothesisStance).where(HypothesisStance.evidence_id.in_(ev_ids)))
    session.execute(delete(CaseEvent).where(CaseEvent.entity_id == entity_id))
    session.execute(delete(EntityVersion).where(EntityVersion.entity_id == entity_id))
    session.execute(delete(QueryLog).where(QueryLog.entity_id == entity_id))
    session.execute(delete(NegativeFinding).where(NegativeFinding.entity_id == entity_id))
    session.execute(delete(CaseComment).where(CaseComment.entity_id == entity_id))
    session.execute(delete(ExpansionJob).where(ExpansionJob.entity_id == entity_id))
    session.execute(
        delete(Edge).where(
            Edge.investigation_id == investigation_id,
            or_(Edge.from_entity_id == entity_id, Edge.to_entity_id == entity_id),
        )
    )
    session.execute(delete(Evidence).where(Evidence.entity_id == entity_id))
    session.execute(delete(CaseNote).where(CaseNote.entity_id == entity_id))
    session.delete(entity)
    session.flush()


def detach_entity(session: Session, investigation_id: str, entity_id: str) -> bool:
    entity = session.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.investigation_id == investigation_id)
    )
    if not entity:
        return False
    victims = derived_entity_ids(session, investigation_id, entity_id)
    keep = seed_entity_ids(session, investigation_id) - {entity_id}
    for vid in victims:
        if vid in keep:
            continue
        row = session.get(Entity, vid)
        if row and row.investigation_id == investigation_id:
            _delete_entity_local(session, investigation_id, row, block=True)
    return True


def blocked_key_set(session: Session, investigation_id: str) -> set[str]:
    rows = session.scalars(select(BlockedKey.canonical_key).where(BlockedKey.investigation_id == investigation_id)).all()
    return {str(key) for key in rows}


def block_key(session: Session, investigation_id: str, canonical_key: str) -> BlockedKey | None:
    key = (canonical_key or "").strip()
    if not key:
        return None
    existing = session.scalar(
        select(BlockedKey).where(BlockedKey.investigation_id == investigation_id, BlockedKey.canonical_key == key)
    )
    if existing:
        return existing
    row = BlockedKey(investigation_id=investigation_id, canonical_key=key)
    session.add(row)
    return row


def delete_edge(session: Session, investigation_id: str, edge_id: str) -> bool:
    edge = session.scalar(select(Edge).where(Edge.id == edge_id, Edge.investigation_id == investigation_id))
    if not edge:
        return False
    session.execute(delete(Evidence).where(Evidence.edge_id == edge_id))
    session.delete(edge)
    session.flush()
    return True


def update_edge(
    session: Session,
    investigation_id: str,
    edge_id: str,
    *,
    rel_type: str,
    note: str = "",
    period: str = "",
    strength: str = "",
) -> Edge | None:
    edge = session.scalar(select(Edge).where(Edge.id == edge_id, Edge.investigation_id == investigation_id))
    if not edge:
        return None
    kind = (rel_type or edge.rel_type or "RELACIONADO").strip().upper()[:32]
    clash = session.scalar(
        select(Edge).where(
            Edge.investigation_id == investigation_id,
            Edge.from_entity_id == edge.from_entity_id,
            Edge.to_entity_id == edge.to_entity_id,
            Edge.rel_type == kind,
            Edge.id != edge.id,
        )
    )
    if clash:
        return None
    edge.rel_type = kind
    attrs = dict(edge.attrs or {})
    if note.strip():
        attrs["nota"] = note.strip()[:2000]
    else:
        attrs.pop("nota", None)
    if period.strip():
        attrs["periodo"] = period.strip()[:64]
    if strength.strip().upper() in {"HIGH", "MEDIUM", "LOW"}:
        attrs["strength"] = strength.strip().upper()
    edge.attrs = attrs
    session.flush()
    return edge


def create_manual_edge(
    session: Session,
    investigation: Investigation,
    *,
    from_id: str,
    to_id: str,
    rel_type: str,
    note: str = "",
) -> Edge | None:
    if from_id == to_id:
        return None
    src = session.scalar(select(Entity).where(Entity.id == from_id, Entity.investigation_id == investigation.id))
    dst = session.scalar(select(Entity).where(Entity.id == to_id, Entity.investigation_id == investigation.id))
    if not src or not dst:
        return None
    kind = (rel_type or "RELACIONADO").strip().upper()[:32]
    existing = session.scalar(
        select(Edge).where(
            Edge.investigation_id == investigation.id,
            Edge.from_entity_id == from_id,
            Edge.to_entity_id == to_id,
            Edge.rel_type == kind,
        )
    )
    if existing:
        if note.strip():
            attrs = dict(existing.attrs or {})
            attrs["nota"] = note.strip()[:2000]
            existing.attrs = attrs
        return existing
    edge = Edge(
        investigation_id=investigation.id,
        from_entity_id=from_id,
        to_entity_id=to_id,
        rel_type=kind,
        confidence=0.99,
        attrs={"nota": note.strip()[:2000]} if note.strip() else {},
        source_connector="manual",
    )
    session.add(edge)
    session.flush()
    return edge


def list_notes(session: Session, investigation_id: str) -> list[CaseNote]:
    return list(
        session.scalars(
            select(CaseNote).where(CaseNote.investigation_id == investigation_id).order_by(CaseNote.created_at)
        ).all()
    )


def add_case_note(
    session: Session,
    investigation: Investigation,
    *,
    title: str,
    body: str,
    entity_id: str | None = None,
    parent_id: str | None = None,
    created_by: str | None = None,
    on_graph: bool = False,
    kind: str = "note",
) -> CaseNote:
    note = CaseNote(
        investigation_id=investigation.id,
        entity_id=entity_id or None,
        parent_id=parent_id or None,
        title=(title or "Anotação").strip()[:255] or "Anotação",
        body=(body or "").strip()[:8000],
        created_by=created_by,
    )
    session.add(note)
    session.flush()
    if on_graph:
        shape = "diagram" if str(kind or "").strip().lower() == "diagram" else "note"
        key = f"{shape}:{note.id}"
        node = Entity(
            investigation_id=investigation.id,
            entity_type="NOTE",
            canonical_key=key,
            display_name=("Diagrama · " + note.title) if shape == "diagram" else note.title,
            attrs={"nota": note.body, "status": "confirmed", "kind": shape},
            confidence=0.99,
            is_seed=False,
            depth=0,
        )
        session.add(node)
        session.flush()
        note.entity_id = node.id
        if entity_id:
            create_manual_edge(
                session,
                investigation,
                from_id=node.id,
                to_id=entity_id,
                rel_type="ANOTACAO",
                note=note.body,
            )
    return note


def purge_investigation(session: Session, investigation_id: str) -> bool:
    """Apaga o caso e todos os filhos. Evita IntegrityError do cascade ORM."""
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return False
    entity_ids = list(session.scalars(select(Entity.id).where(Entity.investigation_id == investigation_id)))
    hyp_ids = list(session.scalars(select(Hypothesis.id).where(Hypothesis.investigation_id == investigation_id)))
    if hyp_ids:
        session.execute(delete(HypothesisStance).where(HypothesisStance.hypothesis_id.in_(hyp_ids)))
    claim_ids = list(session.scalars(select(Claim.id).where(Claim.investigation_id == investigation_id)))
    if claim_ids:
        session.execute(delete(ClaimApproval).where(ClaimApproval.claim_id.in_(claim_ids)))
    session.execute(delete(Hypothesis).where(Hypothesis.investigation_id == investigation_id))
    session.execute(delete(Claim).where(Claim.investigation_id == investigation_id))
    session.execute(delete(PlaybookItem).where(PlaybookItem.investigation_id == investigation_id))
    session.execute(delete(EntityVersion).where(EntityVersion.investigation_id == investigation_id))
    session.execute(delete(QueryLog).where(QueryLog.investigation_id == investigation_id))
    session.execute(delete(NegativeFinding).where(NegativeFinding.investigation_id == investigation_id))
    session.execute(delete(CaseComment).where(CaseComment.investigation_id == investigation_id))
    session.execute(delete(ResearchPlan).where(ResearchPlan.investigation_id == investigation_id))
    session.execute(delete(CaseSnapshot).where(CaseSnapshot.investigation_id == investigation_id))
    session.execute(delete(CaseEvent).where(CaseEvent.investigation_id == investigation_id))
    session.execute(delete(CaseTask).where(CaseTask.investigation_id == investigation_id))
    session.execute(delete(VerificationRecord).where(VerificationRecord.investigation_id == investigation_id))
    session.execute(delete(ChangeLog).where(ChangeLog.investigation_id == investigation_id))
    session.execute(delete(HostIntel).where(HostIntel.investigation_id == investigation_id))
    session.execute(delete(Evidence).where(Evidence.investigation_id == investigation_id))
    session.execute(delete(ExpansionJob).where(ExpansionJob.investigation_id == investigation_id))
    session.execute(delete(Edge).where(Edge.investigation_id == investigation_id))
    if entity_ids:
        session.execute(delete(Identifier).where(Identifier.entity_id.in_(entity_ids)))
    session.execute(delete(CaseNote).where(CaseNote.investigation_id == investigation_id))
    session.execute(delete(BlockedKey).where(BlockedKey.investigation_id == investigation_id))
    session.execute(delete(Entity).where(Entity.investigation_id == investigation_id))
    session.execute(delete(Investigation).where(Investigation.id == investigation_id))
    session.expire_all()
    return True


def delete_case_note(session: Session, investigation_id: str, note_id: str) -> bool:
    note = session.scalar(select(CaseNote).where(CaseNote.id == note_id, CaseNote.investigation_id == investigation_id))
    if not note:
        return False
    entity_id = note.entity_id
    children = session.scalars(select(CaseNote).where(CaseNote.parent_id == note.id)).all()
    for child in children:
        child.parent_id = note.parent_id
    session.delete(note)
    session.flush()
    if entity_id:
        leftover = session.scalar(select(CaseNote).where(CaseNote.entity_id == entity_id))
        entity = session.scalar(
            select(Entity).where(
                Entity.id == entity_id,
                Entity.investigation_id == investigation_id,
                Entity.entity_type == "NOTE",
            )
        )
        if entity and leftover is None:
            _delete_entity_local(session, investigation_id, entity, block=False)
    return True


def note_tree(notes: list[CaseNote]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[CaseNote]] = {}
    for note in notes:
        by_parent.setdefault(note.parent_id, []).append(note)

    def walk(parent: str | None) -> list[dict[str, Any]]:
        rows = []
        for note in by_parent.get(parent, []):
            rows.append({"note": note, "children": walk(note.id)})
        return rows

    return walk(None)


def confirm_entity(session: Session, entity: Entity, *, reason: str) -> Entity:
    inv = session.get(Investigation, entity.investigation_id)
    if inv:
        from osint4all.quality.verification import apply_verdict

        apply_verdict(session, inv, entity, verdict="confirmed", reason=reason, created_by=None)
        return entity
    attrs = dict(entity.attrs or {})
    attrs["status"] = "confirmed"
    attrs["motivo"] = reason
    entity.attrs = attrs
    entity.confidence = max(entity.confidence, 0.85)
    return entity
