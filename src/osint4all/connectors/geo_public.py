"""CEP + Nominatim — pino no mapa a partir do endereço já público no QSA."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj


def _origin_seed(entity: Entity) -> tuple[str, str] | None:
    if entity.canonical_key.startswith("cnpj:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        if validate_cnpj(digits):
            return "CNPJ", digits
    for ident in entity.identifiers:
        if ident.kind == "CNPJ" and validate_cnpj(ident.value):
            return "CNPJ", only_digits(ident.value)
        if ident.kind in {"NAME", "URL"} and ident.value:
            return ident.kind, ident.value
    if entity.display_name:
        return "NAME", entity.display_name
    return None


def address_query(attrs: dict[str, Any]) -> str:
    parts = [
        str(attrs.get("endereco") or "").strip(),
        str(attrs.get("bairro") or "").strip(),
        str(attrs.get("municipio") or "").strip(),
        str(attrs.get("uf") or "").strip(),
        "Brasil",
    ]
    return ", ".join(part for part in parts if part and part != "Brasil") + ", Brasil"


def parse_viacep(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("erro"):
        return {}
    out: dict[str, Any] = {}
    if data.get("localidade"):
        out["municipio"] = data["localidade"]
    if data.get("uf"):
        out["uf"] = data["uf"]
    if data.get("bairro"):
        out["bairro"] = data["bairro"]
    logradouro = " ".join(str(data.get(k) or "").strip() for k in ("logradouro", "complemento") if data.get(k))
    if logradouro.strip():
        out["endereco"] = logradouro.strip()
    return out


def parse_nominatim_rows(rows: list[Any]) -> dict[str, Any]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            lat = float(row.get("lat"))
            lng = float(row.get("lon"))
        except (TypeError, ValueError):
            continue
        return {
            "lat": lat,
            "lng": lng,
            "geo_label": str(row.get("display_name") or "")[:220],
            "geo_fonte": "nominatim",
        }
    return {}


class GeoPublicConnector:
    name = "geo_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=20.0,
            default_headers={"User-Agent": "osint4all/0.1 (investigative journalism; nominatim)", "Accept": "application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.geo_public_enable, "via": "viacep+nominatim"}

    def accepts(self, entity: Entity) -> bool:
        if entity.entity_type != "ORG":
            return False
        attrs = entity.attrs or {}
        if attrs.get("lat") not in (None, "") and attrs.get("lng") not in (None, ""):
            return False
        return bool(attrs.get("cep") or attrs.get("municipio") or attrs.get("endereco") or attrs.get("uf"))

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.geo_public_enable:
            raise SkippedDisabled("Geo público desabilitado")
        seed = _origin_seed(entity)
        if not seed:
            return ConnectorResult()
        kind, value = seed
        attrs = dict(entity.attrs or {})
        extra = dict(attrs)
        cep = only_digits(str(attrs.get("cep") or ""))
        if len(cep) == 8:
            resp = self.http.request("GET", f"https://viacep.com.br/ws/{cep}/json/", allow_404=True)
            if resp.status_code < 400:
                try:
                    extra.update(parse_viacep(resp.json()))
                except Exception:
                    pass
        query = address_query(extra)
        if len(query) < 8:
            return ConnectorResult()
        resp = self.http.request(
            "GET",
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "br"},
            allow_404=True,
        )
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            rows = resp.json()
        except Exception:
            return ConnectorResult()
        geo = parse_nominatim_rows(rows if isinstance(rows, list) else [])
        if not geo:
            return ConnectorResult()
        extra.update(geo)
        return ConnectorResult(
            entities=[
                FoundEntity(
                    entity_type="ORG",
                    kind=kind,
                    value=value,
                    display_name=entity.display_name,
                    attrs=extra,
                    confidence=max(0.55, entity.confidence or 0.5),
                )
            ],
            evidence=[
                FoundEvidence(
                    source_label="Nominatim / ViaCEP",
                    url="https://nominatim.openstreetmap.org/",
                    snippet=geo.get("geo_label") or query,
                    payload={"query": query, **geo},
                    entity_ref=entity.canonical_key,
                )
            ],
        )
