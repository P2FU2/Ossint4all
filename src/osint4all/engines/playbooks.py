"""Playbooks de investigação: empresa, pessoa e customizados."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import Investigation, PlaybookItem

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
    if "CNPJ" in kinds:
        return "COMPANY"
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
