"""Ativos manuais: conta bancária e patrimônio estimado. Sem consulta a banco."""

from __future__ import annotations

from osint4all.connectors.base import FoundEntity
from osint4all.db.models import Entity, Investigation
from osint4all.db.repository import create_manual_edge
from osint4all.graph.resolve import upsert_found_entity

ACCOUNT_TYPES = ("corrente", "poupança", "pagamento", "investimento", "outro")


def _clean(value: str) -> str:
    return " ".join((value or "").split()).strip()


def add_bank_account(
    session,
    investigation: Investigation,
    host: Entity,
    *,
    bank: str = "",
    agency: str = "",
    account: str = "",
    account_type: str = "",
    pix: str = "",
    source: str = "",
    note: str = "",
) -> Entity | None:
    bank = _clean(bank)
    agency = _clean(agency)
    account = _clean(account)
    pix = _clean(pix)
    source = _clean(source)
    note = _clean(note)
    tipo = _clean(account_type).casefold()
    if tipo not in ACCOUNT_TYPES:
        tipo = ""
    if not (bank or agency or account or pix):
        return None
    bits = [bank, agency, account]
    value = " / ".join(part for part in bits if part) or pix
    label = " · ".join(part for part in (bank or None, agency and f"ag {agency}", account) if part) or pix
    node = upsert_found_entity(
        session,
        investigation,
        FoundEntity(
            entity_type="ASSET",
            kind="BANK",
            value=value,
            display_name=label or "Conta bancária",
            attrs={
                "banco": bank,
                "agencia": agency,
                "conta": account,
                "tipo_conta": tipo,
                "pix": pix,
                "fonte": source,
                "nota": note,
                "status": "unconfirmed",
            },
            confidence=0.4,
        ),
        depth=max(1, int(host.depth or 0) + 1),
        is_seed=False,
    )
    create_manual_edge(
        session,
        investigation,
        from_id=host.id,
        to_id=node.id,
        rel_type="TITULAR",
        note=source or "Conta acrescentada no dossiê",
    )
    return node


def add_wealth_estimate(
    session,
    investigation: Investigation,
    host: Entity,
    *,
    amount: str = "",
    year: str = "",
    source: str = "",
    note: str = "",
) -> Entity | None:
    amount = _clean(amount)
    year = _clean(year)
    source = _clean(source)
    note = _clean(note)
    if not amount:
        return None
    label = f"Patrimônio ~ {amount}"
    if year:
        label = f"{label} ({year})"
    value = f"{amount}|{year}|{host.id}"
    node = upsert_found_entity(
        session,
        investigation,
        FoundEntity(
            entity_type="ASSET",
            kind="WEALTH",
            value=value,
            display_name=label,
            attrs={
                "valor": amount,
                "ano": year,
                "fonte": source,
                "nota": note,
                "status": "unconfirmed",
            },
            confidence=0.35,
        ),
        depth=max(1, int(host.depth or 0) + 1),
        is_seed=False,
    )
    attrs = dict(host.attrs or {})
    attrs["patrimonio_estimado"] = amount
    if year:
        attrs["patrimonio_ano"] = year
    if source:
        attrs["patrimonio_fonte"] = source
    host.attrs = attrs
    create_manual_edge(
        session,
        investigation,
        from_id=host.id,
        to_id=node.id,
        rel_type="PATRIMONIO",
        note=source or "Estimativa acrescentada no dossiê",
    )
    return node
