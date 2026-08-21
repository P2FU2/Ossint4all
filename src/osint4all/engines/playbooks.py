"""Playbooks de investigação: empresa, pessoa e customizados."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from osint4all.db.models import Entity, Investigation, PlaybookItem, QueryLog
from osint4all.graph.expand import connectors_for_kinds

STEP_PROBES: dict[str, list[str] | None] = {
    "legal": ["CNPJ"],
    "registry": ["CNPJ"],
    "admins": ["QSA"],
    "partners": ["QSA"],
    "ubo": ["QSA"],
    "addresses": ["CNPJ"],
    "phones": ["PHONE"],
    "emails": ["EMAIL"],
    "websites": ["URL"],
    "domains": ["URL"],
    "infra": ["URL"],
    "related_orgs": ["COMPANIES"],
    "contracts": ["CONTRACTS"],
    "cases": ["PROCESSOS"],
    "sanctions": ["SANCTIONS"],
    "news": ["NAME"],
    "documents": None,
    "key_people": ["QSA"],
    "history": ["CNPJ"],
    "verify": None,
    "parties": ["PROCESSOS"],
    "lawyers": ["PROCESSOS"],
    "moves": ["CNJ"],
    "related": ["PROCESSOS"],
    "capa": ["CNJ"],
    "whois": ["URL"],
    "certs": ["URL"],
    "hosts": ["URL"],
    "observe": ["URL"],
    "org": ["CNPJ"],
    "identity": ["CPF", "NAME"],
    "aliases": ["NAME"],
    "usernames": ["USERNAME"],
    "companies": ["COMPANIES"],
    "roles": ["COMPANIES"],
    "relations": ["COMPANIES"],
    "timeline": None,
}

COMPANY_STEPS = [
    ("legal", "Identidade legal"),
    ("registry", "Registro societário"),
    ("admins", "Administradores"),
    ("partners", "Sócios"),
    ("ubo", "Beneficiários relacionados"),
    ("addresses", "Endereços"),
    ("phones", "Telefones"),
    ("emails", "E-mails"),
    ("websites", "Websites"),
    ("domains", "Domínios"),
    ("infra", "Infraestrutura pública associada"),
    ("related_orgs", "Empresas relacionadas"),
    ("contracts", "Contratos públicos"),
    ("cases", "Processos"),
    ("sanctions", "Sanções"),
    ("news", "Notícias"),
    ("documents", "Documentos"),
    ("key_people", "Pessoas-chave"),
    ("history", "Mudanças históricas"),
    ("verify", "Verificação final"),
]

CASE_STEPS = [
    ("capa", "Número e capa"),
    ("parties", "Partes"),
    ("lawyers", "Advogados e menções"),
    ("moves", "Movimentos públicos"),
    ("news", "Notícias"),
    ("related", "Mesmas partes"),
    ("verify", "Verificação final"),
]

DOMAIN_STEPS = [
    ("whois", "Titular do domínio"),
    ("certs", "Certificados"),
    ("hosts", "Subdomínios e hosts"),
    ("infra", "Infraestrutura pública"),
    ("org", "Empresa ligada"),
    ("news", "Menções"),
    ("observe", "Ficha do host"),
    ("verify", "Verificação final"),
]

PERSON_STEPS = [
    ("identity", "Identidade"),
    ("aliases", "Aliases"),
    ("usernames", "Usernames"),
    ("emails", "E-mails públicos"),
    ("phones", "Telefone público"),
    ("companies", "Empresas"),
    ("roles", "Cargos"),
    ("addresses", "Endereços históricos"),
    ("domains", "Domínios"),
    ("documents", "Documentos"),
    ("cases", "Processos"),
    ("news", "Notícias"),
    ("relations", "Relações"),
    ("timeline", "Timeline"),
]

TEMPLATES = {
    "COMPANY": COMPANY_STEPS,
    "PERSON": PERSON_STEPS,
    "CASE": CASE_STEPS,
    "DOMAIN": DOMAIN_STEPS,
}


def infer_playbook(investigation: Investigation) -> str:
    if investigation.playbook_key in TEMPLATES:
        return investigation.playbook_key
    kinds = set()
    for entity in investigation.entities or []:
        for ident in entity.identifiers or []:
            kinds.add(ident.kind)
        if entity.entity_type == "ORG":
            kinds.add("CNPJ")
        if entity.entity_type == "CASE":
            kinds.add("CNJ")
        if entity.entity_type == "PROFILE":
            kinds.add("URL")
    if "CNJ" in kinds:
        return "CASE"
    if "CNPJ" in kinds:
        return "COMPANY"
    if "URL" in kinds and not ({"CPF", "NAME", "EMAIL", "PHONE"} & kinds):
        return "DOMAIN"
    return "PERSON"


def attach_playbook(session: Session, investigation: Investigation, key: str | None = None) -> list[PlaybookItem]:
    playbook = (key or infer_playbook(investigation)).upper()
    if playbook not in TEMPLATES:
        playbook = "PERSON"
    investigation.playbook_key = playbook
    already = list(session.scalars(select(PlaybookItem).where(PlaybookItem.investigation_id == investigation.id)))
    used_keys = {row.step_key for row in already}
    prefix = f"{playbook}:"
    have_logical = {
        (row.step_key[len(prefix) :] if row.step_key.startswith(prefix) else row.step_key)
        for row in already
        if row.playbook_key == playbook
    }
    rows: list[PlaybookItem] = []
    for idx, (step_key, title) in enumerate(TEMPLATES[playbook], start=1):
        if step_key in have_logical:
            continue
        db_key = step_key if step_key not in used_keys else f"{playbook}:{step_key}"
        item = PlaybookItem(
            investigation_id=investigation.id,
            playbook_key=playbook,
            step_key=db_key,
            title=title,
            sort=idx,
            status="todo",
        )
        session.add(item)
        rows.append(item)
    session.flush()
    return rows


def list_items(session: Session, investigation_id: str, playbook_key: str | None = None) -> list[PlaybookItem]:
    stmt = select(PlaybookItem).where(PlaybookItem.investigation_id == investigation_id)
    if playbook_key:
        stmt = stmt.where(PlaybookItem.playbook_key == playbook_key)
    return list(session.scalars(stmt.order_by(PlaybookItem.sort)).all())


def set_item_status(session: Session, investigation_id: str, item_id: str, status: str, note: str = "") -> PlaybookItem | None:
    row = session.scalar(
        select(PlaybookItem).where(PlaybookItem.id == item_id, PlaybookItem.investigation_id == investigation_id)
    )
    if not row:
        return None
    if status in {"todo", "doing", "done", "na"}:
        row.status = status
    if note:
        row.note = note[:400]
    return row


def progress(items: list[PlaybookItem]) -> dict[str, int]:
    total = len(items)
    done = sum(1 for item in items if item.status in {"done", "na"})
    return {"total": total, "done": done, "pct": int(round(100 * done / total)) if total else 0}


def logical_step(item: PlaybookItem | str) -> str:
    raw = item.step_key if isinstance(item, PlaybookItem) else item
    key = (raw or "").strip()
    if ":" in key:
        return key.split(":", 1)[-1]
    return key


def step_probes(item: PlaybookItem | str) -> list[str] | None:
    return STEP_PROBES.get(logical_step(item))


def step_can_run(item: PlaybookItem) -> bool:
    return step_probes(item) is not None


def _entity_matches(entity: Entity, kinds: list[str]) -> bool:
    idents = {row.kind for row in (entity.identifiers or [])}
    key = entity.canonical_key or ""
    wanted = {item.upper() for item in kinds}
    if wanted & {"CNPJ", "QSA"}:
        return entity.entity_type == "ORG" or key.startswith("cnpj:") or "CNPJ" in idents
    if "COMPANIES" in wanted:
        return entity.is_seed or entity.entity_type in {"PERSON", "ORG"}
    if "EMAIL" in wanted:
        return key.startswith("email:") or "EMAIL" in idents
    if "PHONE" in wanted:
        return key.startswith("phone:") or "PHONE" in idents
    if "USERNAME" in wanted:
        return key.startswith("username:") or "USERNAME" in idents
    if "URL" in wanted:
        return entity.entity_type in {"PROFILE"} or key.startswith(("url:", "host:"))
    if "PROCESSOS" in wanted:
        return entity.is_seed or key.startswith("cnj:") or "CNJ" in idents
    if "CPF" in wanted:
        return key.startswith("cpf:") or "CPF" in idents or entity.is_seed
    if wanted & {"NAME", "SANCTIONS", "CONTRACTS"}:
        return entity.is_seed or entity.entity_type in {"PERSON", "ORG"}
    return entity.is_seed


def targets_for_step(session: Session, investigation_id: str, kinds: list[str], *, limit: int = 4) -> list[Entity]:
    rows = list(
        session.scalars(
            select(Entity)
            .where(Entity.investigation_id == investigation_id)
            .order_by(Entity.is_seed.desc(), Entity.display_name)
        )
    )
    matched = [row for row in rows if _entity_matches(row, kinds)]
    if not matched:
        matched = [row for row in rows if row.is_seed]
    seen: set[str] = set()
    out: list[Entity] = []
    for row in matched:
        if row.id in seen:
            continue
        seen.add(row.id)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def enqueue_playbook_step(session: Session, investigation: Investigation, item: PlaybookItem, *, max_attempts: int = 3) -> dict:
    kinds = step_probes(item)
    if not kinds:
        return {"ok": False, "queued": 0, "message": "Este passo é manual — não há fonte pública para disparar."}
    targets = targets_for_step(session, investigation.id, kinds)
    if not targets:
        return {"ok": False, "queued": 0, "message": "Nenhum nó neste caso para este passo. Complete o alvo e tente de novo."}
    from osint4all.db.repository import enqueue_expand

    queued = 0
    for entity in targets:
        attrs = dict(entity.attrs or {})
        attrs["probe_kinds"] = kinds
        entity.attrs = attrs
        if enqueue_expand(
            session,
            investigation=investigation,
            entity=entity,
            depth=entity.depth,
            max_attempts=max_attempts,
            force=True,
        ):
            queued += 1
    item.status = "doing"
    item.note = f"Fila: {queued} consulta(s) deste passo."
    session.flush()
    from osint4all.db.repository import utcnow

    return {"ok": True, "queued": queued, "since": utcnow(), "message": f"{queued} consulta(s) na fila para «{item.title}»."}


def evaluate_playbook_step(session: Session, investigation: Investigation, item: PlaybookItem, *, since=None) -> dict:
    kinds = step_probes(item) or []
    connectors = connectors_for_kinds(kinds) or set()
    logs = list(
        session.scalars(
            select(QueryLog)
            .where(QueryLog.investigation_id == investigation.id)
            .order_by(desc(QueryLog.created_at))
            .limit(40)
        )
    )
    if since is not None:
        from datetime import timedelta, timezone

        def _stamp(value):
            if value is None:
                return None
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        floor = _stamp(since) - timedelta(seconds=5)
        logs = [row for row in logs if _stamp(row.created_at) and _stamp(row.created_at) >= floor]
    relevant = [row for row in logs if connectors and row.connector in connectors]
    hits = [row for row in relevant if (row.result_count or 0) > 0]
    fails = [row for row in relevant if (row.params or {}).get("error")]
    empties = [row for row in relevant if row.empty]
    if hits:
        total = sum(int(row.result_count or 0) for row in hits)
        item.status = "done"
        item.note = f"{total} achado(s) nas fontes deste passo."
        return {"ok": True, "status": "done", "message": f"«{item.title}» feito — {total} achado(s)."}
    if fails:
        item.status = "doing"
        item.note = str((fails[0].params or {}).get("error") or "fonte falhou")[:400]
        return {"ok": False, "status": "doing", "message": f"«{item.title}» falhou numa fonte. Reprocesse na fila do grafo."}
    if empties:
        item.status = "todo"
        item.note = "Fonte pública vazia neste passo. Pode marcar como não se aplica."
        return {"ok": False, "status": "todo", "message": f"«{item.title}» sem resultado público."}
    item.status = "doing"
    item.note = "Consultas na fila — processe o grafo se ainda não rodou."
    return {"ok": True, "status": "doing", "message": f"«{item.title}» enfileirado."}


def add_custom_step(session: Session, investigation: Investigation, title: str) -> PlaybookItem:
    book = investigation.playbook_key or "CUSTOM"
    items = list_items(session, investigation.id, book)
    nxt = max((item.sort for item in items), default=0) + 1
    row = PlaybookItem(
        investigation_id=investigation.id,
        playbook_key=book,
        step_key=f"custom-{book}-{nxt}",
        title=(title or "Passo").strip()[:255] or "Passo",
        sort=nxt,
        status="todo",
    )
    session.add(row)
    return row
