"""Certificate Transparency pública (crt.sh) — padrão SpiderFoot, só domínio."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key

_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", re.I)


def domain_from_entity(entity: Entity) -> str | None:
    candidates: list[str] = []
    for ident in entity.identifiers:
        if ident.kind == "URL":
            host = urlparse(ident.value).hostname
            if host:
                candidates.append(host)
        elif ident.kind == "NAME" and _DOMAIN_RE.match(ident.value.strip()):
            candidates.append(ident.value.strip())
    if entity.display_name and _DOMAIN_RE.match(entity.display_name.strip()):
        candidates.append(entity.display_name.strip())
    for raw in candidates:
        host = raw.lower().lstrip("www.")
        if _DOMAIN_RE.match(host):
            return host
    return None


def parse_crtsh_rows(rows: list[dict[str, Any]], *, origin_key: str, domain: str) -> ConnectorResult:
    out = ConnectorResult()
    seen: set[str] = set()
    for row in rows:
        names = str(row.get("name_value") or row.get("common_name") or "")
        for raw in names.replace(",", "\n").splitlines():
            name = raw.strip().lower().lstrip("*.")
            if not name or name in seen or not _DOMAIN_RE.match(name):
                continue
            seen.add(name)
            if len(seen) > 20:
                return out
            url = f"https://{name}"
            found = FoundEntity(
                entity_type="ORG" if name == domain or name.endswith("." + domain) else "PROFILE",
                kind="URL",
                value=url,
                display_name=name,
                attrs={"crtsh": True, "issuer": row.get("issuer_name")},
                confidence=0.55,
            )
            out.entities.append(found)
            ref = canonical_key("URL", url)
            out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.55))
            out.evidence.append(
                FoundEvidence(
                    source_label="crt.sh",
                    url=f"https://crt.sh/?q={domain}",
                    snippet=f"Nome em certificado público: {name}",
                    payload={"name": name, "id": row.get("id")},
                    entity_ref=ref,
                )
            )
    return out


class CrtshConnector:
    name = "crtsh"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=25.0,
            default_headers={"User-Agent": "osint4all/0.1 (certificate transparency)"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.crtsh_enable}

    def accepts(self, entity: Entity) -> bool:
        return domain_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.crtsh_enable:
            raise SkippedDisabled("crt.sh desabilitado")
        domain = domain_from_entity(entity)
        if not domain:
            return ConnectorResult()
        resp = self.http.request(
            "GET",
            "https://crt.sh/",
            params={"q": domain, "output": "json"},
        )
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            rows = resp.json()
        except Exception:
            return ConnectorResult()
        if not isinstance(rows, list):
            return ConnectorResult()
        return parse_crtsh_rows(rows[:80], origin_key=entity.canonical_key, domain=domain)
