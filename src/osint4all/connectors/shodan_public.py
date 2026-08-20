"""Shodan oficial: serviços anunciados na internet. Sem scrape, sem CVE, sem banner de exploit."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.rdap_public import domain_from_entity
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key


def query_from_entity(entity: Entity) -> str | None:
    domain = domain_from_entity(entity)
    if domain:
        return f"hostname:{domain}"
    if entity.entity_type != "ORG":
        return None
    name = str((entity.attrs or {}).get("razao_social") or entity.display_name or "").strip()
    if len(name) < 5 or name.isdigit():
        return None
    return f'org:"{name}"'


def parse_shodan_matches(rows: list[Any], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        hostnames = [str(h).strip().lower().lstrip("www.") for h in (row.get("hostnames") or []) if str(h).strip()]
        host = hostnames[0] if hostnames else ""
        ip = str(row.get("ip_str") or "").strip()
        port = row.get("port")
        product = str(row.get("product") or "").strip()
        http = row.get("http") if isinstance(row.get("http"), dict) else {}
        title = str(http.get("title") or "").strip()
        loc = row.get("location") if isinstance(row.get("location"), dict) else {}
        place = ", ".join(part for part in (str(loc.get("city") or "").strip(), str(loc.get("country_name") or "").strip()) if part)
        org = str(row.get("org") or "").strip()
        if host:
            url = f"https://{host}"
            label = host
        elif ip:
            url = f"https://www.shodan.io/host/{ip}"
            label = ip
        else:
            continue
        if url in seen:
            continue
        seen.add(url)
        snippet = " · ".join(str(part) for part in (label, f"porta {port}" if port else "", product, org, place, title) if part)
        found = FoundEntity(
            entity_type="PROFILE",
            kind="URL",
            value=url,
            display_name=label[:180],
            attrs={
                "host": host,
                "porta": port,
                "produto": product,
                "org": org,
                "local": place,
                "fonte": "shodan",
            },
            confidence=0.55,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        if ref != origin_key:
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5, attrs={"fonte": "shodan"}))
        out.evidence.append(
            FoundEvidence(
                source_label="Shodan",
                url=url if host else f"https://www.shodan.io/host/{ip}",
                snippet=snippet[:400],
                payload={"host": host, "ip": ip, "port": port, "product": product, "org": org, "local": place},
                entity_ref=ref,
            )
        )
        if len(out.entities) >= 8:
            break
    return out


class ShodanPublicConnector:
    name = "shodan_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"User-Agent": "osint4all/0.1 (shodan api)", "Accept": "application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.shodan_enable,
            "api_key_configured": bool(self.settings.shodan_api_key),
            "via": "api.shodan.io",
        }

    def accepts(self, entity: Entity) -> bool:
        return query_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.shodan_enable:
            raise SkippedDisabled("Shodan desabilitado")
        if not self.settings.shodan_api_key:
            raise SkippedDisabled("Shodan sem SHODAN_API_KEY — sem scrape do site")
        query = query_from_entity(entity)
        if not query:
            return ConnectorResult()
        resp = self.http.request(
            "GET",
            "https://api.shodan.io/shodan/host/search",
            params={"key": self.settings.shodan_api_key, "query": query, "minify": "true"},
            allow_404=True,
            max_retries=1,
        )
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            data = resp.json()
        except Exception:
            return ConnectorResult()
        rows = data.get("matches") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return ConnectorResult()
        return parse_shodan_matches(rows, origin_key=entity.canonical_key)
