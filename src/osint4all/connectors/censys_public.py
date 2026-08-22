"""Censys oficial — Uncover só com API, sem FOFA scrape e sem scan."""

from __future__ import annotations

import base64
from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.rdap_public import domain_from_entity
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key


def parse_censys_hits(rows: list[Any], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_names = row.get("name") or row.get("names") or []
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        names = [str(n).lower().lstrip("www.") for n in raw_names if str(n).strip()]
        host = names[0] if names else ""
        ip = str(row.get("ip") or "").strip()
        loc = row.get("location") if isinstance(row.get("location"), dict) else {}
        place = ", ".join(part for part in (str(loc.get("city") or ""), str(loc.get("country") or "")) if part)
        if host:
            url = f"https://{host}"
            label = host
        elif ip:
            url = f"https://search.censys.io/hosts/{ip}"
            label = ip
        else:
            continue
        if any(e.value == url for e in out.entities):
            continue
        found = FoundEntity(
            entity_type="PROFILE",
            kind="URL",
            value=url,
            display_name=label[:180],
            attrs={"fonte": "censys", "local": place, "host": host},
            confidence=0.5,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        if ref != origin_key:
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5, attrs={"fonte": "censys"}))
        out.evidence.append(
            FoundEvidence(
                source_label="Censys",
                url=url if host else f"https://search.censys.io/hosts/{ip}",
                snippet=" · ".join(part for part in (label, place) if part),
                payload={"host": host, "ip": ip, "local": place},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 8:
            break
    return out


class CensysPublicConnector:
    name = "censys_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"User-Agent": "osint4all/0.1 (censys api)", "Accept": "application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.censys_enable,
            "api_key_configured": bool(self.settings.censys_api_id and self.settings.censys_api_secret),
            "paid_only": True,
            "via": "search.censys.io",
        }

    def accepts(self, entity: Entity) -> bool:
        return domain_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.censys_enable:
            raise SkippedDisabled("Censys desabilitado")
        if not (self.settings.censys_api_id and self.settings.censys_api_secret):
            raise SkippedDisabled("Censys sem CENSYS_API_ID / CENSYS_API_SECRET")
        domain = domain_from_entity(entity)
        if not domain:
            return ConnectorResult()
        token = base64.b64encode(
            f"{self.settings.censys_api_id}:{self.settings.censys_api_secret}".encode()
        ).decode()
        try:
            resp = self.http.request(
                "GET",
                "https://search.censys.io/api/v2/hosts/search",
                params={"q": f"names:{domain}", "per_page": 8},
                headers={"Authorization": f"Basic {token}"},
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        result = data.get("result") if isinstance(data, dict) else {}
        rows = result.get("hits") if isinstance(result, dict) else None
        return parse_censys_hits(rows if isinstance(rows, list) else [], origin_key=entity.canonical_key)
