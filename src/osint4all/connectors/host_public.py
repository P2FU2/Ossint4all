"""Hosts e subdomínios em índices públicos. Estilo theHarvester/Amass/Subfinder — sem probe HTTP."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.rdap_public import domain_from_entity
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key

_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$", re.I)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _host_ok(host: str, domain: str) -> bool:
    text = (host or "").lower().strip().lstrip("www.")
    if not _HOST_RE.match(text):
        return False
    return text == domain or text.endswith("." + domain)


def _add_host(out: ConnectorResult, *, origin_key: str, host: str, source: str, extra: str = "") -> None:
    url = f"https://{host}"
    if any(e.value == url for e in out.entities):
        return
    found = FoundEntity(
        entity_type="PROFILE",
        kind="URL",
        value=url,
        display_name=host,
        attrs={"fonte": source, "host": host},
        confidence=0.5,
    )
    out.entities.append(found)
    ref = canonical_key("URL", url)
    if ref != origin_key:
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.5, attrs={"fonte": source}))
    out.evidence.append(
        FoundEvidence(
            source_label=source,
            url=url,
            snippet=extra or f"Host público: {host}",
            payload={"host": host, "fonte": source},
            entity_ref=ref,
        )
    )


def parse_hackertarget_text(text: str, *, domain: str, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or raw.lower().startswith("error"):
            continue
        host, _, ip = raw.partition(",")
        host = host.strip().lower().lstrip("www.")
        if not _host_ok(host, domain):
            continue
        _add_host(out, origin_key=origin_key, host=host, source="HackerTarget", extra=ip.strip())
        if len(out.entities) >= 12:
            break
    return out


def parse_wayback_cdx(rows: list[Any], *, domain: str, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for row in rows:
        url = ""
        if isinstance(row, list) and row:
            first = str(row[0] or "")
            if first == "original" and (len(row) == 1 or not str(row[1]).startswith("http")):
                continue
            url = first if first.startswith("http") else str(row[1] if len(row) > 1 else "")
        elif isinstance(row, str):
            url = row
        host = (urlparse(url).hostname or "").lower().lstrip("www.")
        if not _host_ok(host, domain):
            continue
        _add_host(out, origin_key=origin_key, host=host, source="Wayback CDX")
        if len(out.entities) >= 12:
            break
    return out


def parse_urlscan_results(rows: list[Any], *, domain: str, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    emails: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        page = row.get("page") if isinstance(row.get("page"), dict) else {}
        host = str(page.get("domain") or urlparse(str(page.get("url") or "")).hostname or "").lower().lstrip("www.")
        blob = " ".join(str(page.get(k) or "") for k in ("url", "title", "domain"))
        emails.update(m.lower() for m in _EMAIL_RE.findall(blob))
        if _host_ok(host, domain):
            _add_host(out, origin_key=origin_key, host=host, source="urlscan.io")
        if len(out.entities) >= 12:
            break
    for email in sorted(emails):
        if not email.endswith("@" + domain) and not email.endswith("." + domain):
            continue
        found = FoundEntity(
            entity_type="PERSON",
            kind="EMAIL",
            value=email,
            display_name=email,
            attrs={"fonte": "urlscan.io", "status": "unconfirmed"},
            confidence=0.4,
        )
        out.entities.append(found)
        ref = canonical_key("EMAIL", email)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.4, attrs={"fonte": "urlscan"}))
        out.evidence.append(FoundEvidence(source_label="urlscan.io", snippet=email, payload={"email": email}, entity_ref=ref))
    return out


class HostPublicConnector:
    name = "host_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=20.0,
            default_headers={"User-Agent": "osint4all/0.1 (passive host index)", "Accept": "application/json, text/plain"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.host_public_enable,
            "via": "wayback + hackertarget + urlscan",
        }

    def accepts(self, entity: Entity) -> bool:
        return domain_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.host_public_enable:
            raise SkippedDisabled("Hosts públicos desabilitados")
        domain = domain_from_entity(entity)
        if not domain:
            return ConnectorResult()
        out = ConnectorResult()
        out.merge(self._wayback(domain, entity.canonical_key))
        out.merge(self._hackertarget(domain, entity.canonical_key))
        out.merge(self._urlscan(domain, entity.canonical_key))
        return out

    def _wayback(self, domain: str, origin_key: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://web.archive.org/cdx/search/cdx",
                params={
                    "url": f"*.{domain}/*",
                    "output": "json",
                    "fl": "original",
                    "collapse": "urlkey",
                    "limit": 30,
                },
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            rows = resp.json()
        except Exception:
            return ConnectorResult()
        return parse_wayback_cdx(rows if isinstance(rows, list) else [], domain=domain, origin_key=origin_key)

    def _hackertarget(self, domain: str, origin_key: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://api.hackertarget.com/hostsearch/",
                params={"q": domain},
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        return parse_hackertarget_text(resp.text or "", domain=domain, origin_key=origin_key)

    def _urlscan(self, domain: str, origin_key: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://urlscan.io/api/v1/search/",
                params={"q": f"domain:{domain}", "size": 10},
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
        rows = data.get("results") if isinstance(data, dict) else None
        return parse_urlscan_results(rows if isinstance(rows, list) else [], domain=domain, origin_key=origin_key)
