"""Enriquece um hostname já conhecido: status, título, tech, security.txt, links do domínio.

Não é scanner. Um host por nó. Só HTTPS :443. Sem lista, sem porta, sem IP.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.rdap_public import domain_from_entity
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key
from osint4all.intel.hosts import (
    extract_same_domain_links,
    is_public_hostname,
    normalize_host,
    parse_http_snapshot,
    parse_robots,
    parse_security_txt,
)


def observe_host_from_entity(entity: Entity) -> str | None:
    for ident in getattr(entity, "identifiers", None) or []:
        if ident.kind == "URL":
            host = normalize_host(ident.value or "")
            if host:
                return host
    key = str(getattr(entity, "canonical_key", "") or "")
    if key.startswith("url:"):
        host = normalize_host(key.split(":", 1)[1])
        if host:
            return host
    attrs_host = normalize_host(str((entity.attrs or {}).get("host") or entity.display_name or ""))
    if attrs_host:
        return attrs_host
    return domain_from_entity(entity)


def observation_to_result(obs, *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    url = f"https://{obs.host}/"
    snippet = obs.snippet or obs.title or obs.host
    out.evidence.append(
        FoundEvidence(
            source_label="Ficha de host",
            url=url,
            snippet=snippet,
            payload={
                "host": obs.host,
                "status": obs.status,
                "title": obs.title,
                "tech": obs.tech,
                "origin": obs.origin,
                "fonte": obs.source,
            },
            entity_ref=origin_key,
        )
    )
    return out


class HostObserveConnector:
    name = "host_observe"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=12.0,
            default_headers={
                "User-Agent": "osint4all/0.1 (dossier host observe; +https://github.com/P2FU2/Ossint4all)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.host_observe_enable,
            "via": "GET único no hostname já conhecido",
        }

    def accepts(self, entity: Entity) -> bool:
        if entity.entity_type == "PUBLICATION":
            return False
        host = observe_host_from_entity(entity)
        return bool(host and is_public_hostname(host))

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.host_observe_enable:
            raise SkippedDisabled("Observação de host desabilitada")
        host = observe_host_from_entity(entity)
        if not host:
            return ConnectorResult()
        out = ConnectorResult()
        page = self._get(f"https://{host}/")
        if page is not None:
            status, headers, html, final = page
            if not self._same_site(host, final):
                html = ""
            obs = parse_http_snapshot(f"https://{host}/", status=status, headers=headers, html=html)
            if obs:
                extra = observation_to_result(obs, origin_key=entity.canonical_key)
                inv = getattr(ctx, "investigation", None)
                if html and getattr(inv, "id", None):
                    from osint4all.quality.provenance import content_hash, write_snapshot

                    digest = content_hash({"host": host, "status": status}, html[:2000], f"https://{host}/")
                    path = write_snapshot(inv.id, digest, html.encode("utf-8", errors="replace"))
                    if extra.evidence:
                        extra.evidence[0].raw_path = path
                        extra.evidence[0].http_status = status
                        extra.evidence[0].method = "GET"
                        payload = dict(extra.evidence[0].payload or {})
                        payload["raw_path"] = path
                        payload["http_status"] = status
                        payload["method"] = "GET"
                        extra.evidence[0].payload = payload
                out.merge(extra)
            for link in extract_same_domain_links(html, host, limit=8):
                found = FoundEntity(
                    entity_type="PUBLICATION",
                    kind="URL",
                    value=link,
                    display_name=urlparse(link).path or link,
                    attrs={"fonte": "photon_lite", "host": host},
                    confidence=0.45,
                )
                out.entities.append(found)
                ref = canonical_key("URL", link)
                out.edges.append(
                    FoundEdge(from_ref=entity.canonical_key, to_ref=ref, rel_type="MENCAO", confidence=0.4, attrs={"fonte": "photon_lite"})
                )
                out.evidence.append(
                    FoundEvidence(source_label="Página do domínio", url=link, snippet="Link na homepage do host já conhecido", payload={"host": host, "origin": "observe"}, entity_ref=ref)
                )
        sec = self._get_text(f"https://{host}/.well-known/security.txt")
        for kind, value in parse_security_txt(sec or ""):
            if kind == "contact" and "@" in value:
                found = FoundEntity(
                    entity_type="PERSON",
                    kind="EMAIL",
                    value=value,
                    display_name=value,
                    attrs={"fonte": "security.txt", "status": "unconfirmed"},
                    confidence=0.45,
                )
                out.entities.append(found)
                ref = canonical_key("EMAIL", value)
                out.edges.append(FoundEdge(from_ref=entity.canonical_key, to_ref=ref, rel_type="MENCAO", confidence=0.45, attrs={"fonte": "security.txt"}))
                out.evidence.append(
                    FoundEvidence(source_label="security.txt", snippet=f"Contact: {value}", payload={"host": host, "origin": "observe"}, entity_ref=ref)
                )
            elif kind == "policy":
                found = FoundEntity(
                    entity_type="PUBLICATION",
                    kind="URL",
                    value=value,
                    display_name="Política de segurança",
                    attrs={"fonte": "security.txt", "host": host},
                    confidence=0.5,
                )
                out.entities.append(found)
        robots = self._get_text(f"https://{host}/robots.txt")
        for sitemap in parse_robots(robots or ""):
            found = FoundEntity(
                entity_type="PUBLICATION",
                kind="URL",
                value=sitemap,
                display_name="Sitemap",
                attrs={"fonte": "robots.txt", "host": host},
                confidence=0.4,
            )
            out.entities.append(found)
            ref = canonical_key("URL", sitemap)
            out.evidence.append(
                FoundEvidence(source_label="robots.txt", url=sitemap, snippet="Sitemap anunciado", payload={"host": host, "origin": "observe"}, entity_ref=ref)
            )
        return out

    def _same_site(self, expected: str, final_url: str) -> bool:
        host = normalize_host(final_url)
        return bool(host and (host == expected or host.endswith("." + expected) or expected.endswith("." + host)))

    def _get(self, url: str) -> tuple[int, dict[str, str], str, str] | None:
        try:
            resp = self.http.request("GET", url, allow_404=True, max_retries=1)
        except Exception:
            return None
        headers = {k: v for k, v in resp.headers.items()}
        body = (resp.text or "")[:80_000]
        return resp.status_code, headers, body, str(resp.url)

    def _get_text(self, url: str) -> str:
        page = self._get(url)
        if not page or page[0] >= 400:
            return ""
        return page[2][:20_000]
