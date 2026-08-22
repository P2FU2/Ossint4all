"""Ativos manuais: conta, patrimônio e imóvel. Sem consulta a banco nem cartório."""

from __future__ import annotations

from dataclasses import asdict

from osint4all.connectors.base import FoundEntity
from osint4all.db.models import Entity, Investigation
from osint4all.db.repository import create_manual_edge
from osint4all.graph.match import infer_place, places_from_attrs
from osint4all.graph.resolve import upsert_found_entity

ACCOUNT_TYPES = ("corrente", "poupança", "pagamento", "investimento", "outro")
PROPERTY_TYPES = ("casa", "apartamento", "terreno", "sala", "galpão", "sítio", "outro")


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


def _attach_place(host: Entity, *, municipio: str, uf: str, source: str) -> None:
    place = infer_place(municipio=municipio, uf=uf, role="imovel", source=source or "manual", kind="associated")
    if place is None:
        return
    attrs = dict(host.attrs or {})
    places = [asdict(item) for item in places_from_attrs(attrs)]
    mark = (place.kind, place.municipio, place.uf, place.role)
    if any((p.get("kind"), p.get("municipio"), p.get("uf"), p.get("role")) == mark for p in places):
        return
    places.append(asdict(place))
    attrs["places"] = places
    host.attrs = attrs


def add_property(
    session,
    investigation: Investigation,
    host: Entity,
    *,
    address: str = "",
    city: str = "",
    uf: str = "",
    property_type: str = "",
    amount: str = "",
    registry: str = "",
    source: str = "",
    note: str = "",
    photos: list[dict] | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> Entity | None:
    address = _clean(address)
    city = _clean(city)
    uf = _clean(uf).upper()[:2]
    amount = _clean(amount)
    registry = _clean(registry)
    source = _clean(source)
    note = _clean(note)
    tipo = _clean(property_type).casefold()
    if tipo not in PROPERTY_TYPES:
        tipo = ""
    shots: list[dict] = []
    seen: set[str] = set()
    for raw in photos or []:
        if not isinstance(raw, dict):
            continue
        url = _clean(str(raw.get("url") or ""))
        if not url or url in seen:
            continue
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/app/casos/")):
            continue
        seen.add(url)
        shots.append({"url": url[:800], "title": _clean(str(raw.get("title") or ""))[:160]})
        if len(shots) >= 8:
            break
    if not (address or city or shots):
        return None
    label = address or " · ".join(part for part in (tipo and tipo.title(), city, uf) if part) or "Imóvel"
    value = " | ".join(part for part in (address, city, uf, host.id) if part)
    thumb = shots[0]["url"] if shots else ""
    geo: dict = {}
    if lat is not None and lng is not None:
        geo = {"lat": float(lat), "lng": float(lng)}
        if not thumb:
            from osint4all.graph.satellite import satellite_urls

            urls = satellite_urls(float(lat), float(lng))
            thumb = urls["thumb"]
            geo.update(urls)
    node = upsert_found_entity(
        session,
        investigation,
        FoundEntity(
            entity_type="ASSET",
            kind="PROPERTY",
            value=value,
            display_name=label[:180],
            attrs={
                "endereco": address,
                "municipio": city,
                "uf": uf,
                "tipo_imovel": tipo,
                "valor": amount,
                "matricula": registry,
                "fonte": source,
                "nota": note,
                "fotos": shots,
                "thumb": thumb,
                "tipo": "imagem" if thumb else "imovel",
                **geo,
                "place_role": "imovel",
                "place_kind": "associated",
                "place_source": source or "manual",
                "status": "unconfirmed",
            },
            confidence=0.4,
        ),
        depth=max(1, int(host.depth or 0) + 1),
        is_seed=False,
    )
    _attach_place(host, municipio=city, uf=uf, source=source)
    create_manual_edge(
        session,
        investigation,
        from_id=host.id,
        to_id=node.id,
        rel_type="PROPRIETARIO",
        note=source or "Imóvel acrescentado no dossiê",
    )
    return node


def add_graph_photo(
    session,
    investigation: Investigation,
    host: Entity,
    *,
    title: str = "",
    source: str = "",
    note: str = "",
    photos: list[dict] | None = None,
    as_profile: bool = False,
) -> Entity | None:
    shots: list[dict] = []
    seen: set[str] = set()
    for raw in photos or []:
        if not isinstance(raw, dict):
            continue
        url = _clean(str(raw.get("url") or ""))
        if not url or url in seen:
            continue
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/app/casos/")):
            continue
        seen.add(url)
        shots.append({"url": url[:800], "title": _clean(str(raw.get("title") or title))[:160]})
        if len(shots) >= 6:
            break
    if not shots:
        return None
    thumb = shots[0]["url"]
    label = _clean(title) or shots[0]["title"] or "Foto"
    if as_profile and host.entity_type == "PERSON":
        attrs = dict(host.attrs or {})
        attrs["thumb"] = thumb
        attrs["profile_photo"] = thumb
        attrs["profile_photo_source"] = _clean(source) or "manual"
        attrs["fotos"] = list(attrs.get("fotos") or []) + shots
        host.attrs = attrs
    node = upsert_found_entity(
        session,
        investigation,
        FoundEntity(
            entity_type="PUBLICATION",
            kind="URL",
            value=thumb,
            display_name=label[:180],
            attrs={
                "thumb": thumb,
                "tipo": "imagem",
                "fonte": _clean(source),
                "nota": _clean(note),
                "fotos": shots,
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
        rel_type="MENCAO",
        note=_clean(source) or "Foto acrescentada no grafo",
    )
    return node
