"""Vista de satélite da sede/imóvel. URL pública — sem baixar imagem."""

from __future__ import annotations

from typing import Any

from osint4all.connectors.base import FoundEntity
from osint4all.db.models import Entity, Investigation
from osint4all.db.repository import create_manual_edge, find_entity_by_key
from osint4all.graph.resolve import upsert_found_entity
from osint4all.identifiers import canonical_key


def _coord(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number) > 180:
        return None
    return number


def coords_of(obj: Entity | dict[str, Any] | None) -> tuple[float, float] | None:
    attrs = obj if isinstance(obj, dict) else getattr(obj, "attrs", None) or {}
    lat, lng = _coord(attrs.get("lat")), _coord(attrs.get("lng"))
    if lat is None or lng is None:
        return None
    if abs(lat) > 90:
        return None
    return lat, lng


def geo_token(lat: float, lng: float) -> str:
    return f"{round(lat, 5)},{round(lng, 5)}"


def satellite_preview_url(lat: float, lng: float, *, zoom: int = 18, size: int = 400) -> str:
    """Recorte de satélite (Esri World Imagery). Não hospedamos o arquivo."""
    span = 0.0018 if zoom >= 18 else 0.004
    west, south = lng - span, lat - span
    east, north = lng + span, lat + span
    return (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
        f"?bbox={west:.6f},{south:.6f},{east:.6f},{north:.6f}"
        f"&bboxSR=4326&imageSR=3857&size={size},{size}&format=jpg&f=image"
    )


def google_maps_satellite_url(lat: float, lng: float, *, zoom: int = 18) -> str:
    return f"https://www.google.com/maps/@{lat:.6f},{lng:.6f},{zoom}z/data=!3m1!1e3"


def google_maps_embed_url(lat: float, lng: float, *, zoom: int = 18) -> str:
    return f"https://maps.google.com/maps?ll={lat:.6f},{lng:.6f}&z={zoom}&t=k&hl=pt-BR&output=embed"


def satellite_urls(lat: float, lng: float) -> dict[str, str]:
    return {
        "thumb": satellite_preview_url(lat, lng),
        "page_url": google_maps_satellite_url(lat, lng),
        "maps_url": google_maps_satellite_url(lat, lng),
        "embed_url": google_maps_embed_url(lat, lng),
    }


def _host_kind(entity: Entity) -> str:
    if entity.entity_type == "ORG":
        return "SEDE"
    return "LOCAL"


def ensure_satellite_cards(session, investigation: Investigation | str) -> int:
    """Um quadro de satélite por coordenada, ligado à empresa ou ao imóvel."""
    from sqlalchemy import select

    inv_id = investigation if isinstance(investigation, str) else investigation.id
    if not isinstance(investigation, Investigation):
        investigation = session.get(Investigation, inv_id)
    if investigation is None:
        return 0
    hosts = list(session.scalars(select(Entity).where(Entity.investigation_id == inv_id)))
    added = 0
    for host in hosts:
        key = str(host.canonical_key or "")
        if key.startswith("geo:") or host.entity_type in {"NOTE", "CASE"}:
            continue
        if host.entity_type not in {"ORG", "ASSET", "VEHICLE"}:
            continue
        pair = coords_of(host)
        if pair is None:
            continue
        lat, lng = pair
        token = geo_token(lat, lng)
        urls = satellite_urls(lat, lng)
        label = str(host.display_name or "local").strip() or "local"
        prefix = "Sede" if host.entity_type == "ORG" else "Local"
        existed = find_entity_by_key(session, inv_id, canonical_key("GEO", token))
        node = upsert_found_entity(
            session,
            investigation,
            FoundEntity(
                entity_type="PUBLICATION",
                kind="GEO",
                value=token,
                display_name=f"Satélite · {label}"[:180],
                attrs={
                    "tipo": "imagem",
                    "thumb": urls["thumb"],
                    "page_url": urls["page_url"],
                    "maps_url": urls["maps_url"],
                    "embed_url": urls["embed_url"],
                    "lat": lat,
                    "lng": lng,
                    "via": "google_maps",
                    "fonte": "Google Maps / satélite",
                    "papel": prefix.lower(),
                    "status": "confirmed",
                },
                confidence=0.7,
            ),
            depth=max(1, int(host.depth or 0) + 1),
            is_seed=False,
        )
        create_manual_edge(
            session,
            investigation,
            from_id=host.id,
            to_id=node.id,
            rel_type=_host_kind(host),
            note=f"{prefix} no Google Maps (satélite)",
        )
        if existed is None:
            added += 1
    return added
