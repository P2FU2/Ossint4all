"""RDAP público do domínio — titular e eventos. Complementa crt.sh (certificado ≠ whois)."""

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
_GENERIC_MAIL = frozenset(
    {"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com", "msn.com"}
)


def domain_from_entity(entity: Entity) -> str | None:
    candidates: list[str] = []
    for ident in entity.identifiers:
        if ident.kind == "EMAIL" and "@" in ident.value:
            candidates.append(ident.value.split("@", 1)[1])
        elif ident.kind == "URL":
            host = urlparse(ident.value).hostname
            if host:
                candidates.append(host)
        elif ident.kind in {"NAME", "USERNAME"} and _DOMAIN_RE.match((ident.value or "").strip()):
            candidates.append(ident.value.strip())
    email = str((entity.attrs or {}).get("email") or "")
    if "@" in email:
        candidates.append(email.split("@", 1)[1])
    for raw in candidates:
        host = raw.lower().strip().lstrip("www.")
        if host in _GENERIC_MAIL or not _DOMAIN_RE.match(host):
            continue
        return host
    return None


def _vcard_fn(entity: dict[str, Any]) -> str:
    vcard = entity.get("vcardArray")
    if not isinstance(vcard, list) or len(vcard) < 2 or not isinstance(vcard[1], list):
        return str(entity.get("handle") or "")
    for item in vcard[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
            return str(item[3] or "")
    return str(entity.get("handle") or "")


def parse_rdap(data: dict[str, Any], *, origin_key: str, domain: str) -> ConnectorResult:
    out = ConnectorResult()
    if not isinstance(data, dict):
        return out
    ldh = str(data.get("ldhName") or domain).lower().rstrip(".")
    url = f"https://{ldh}"
    names: list[str] = []
    for item in data.get("entities") or []:
        if isinstance(item, dict):
            label = _vcard_fn(item).strip()
            if label and label.casefold() not in {n.casefold() for n in names}:
                names.append(label)
    events = []
    for item in data.get("events") or []:
        if isinstance(item, dict) and item.get("eventAction") and item.get("eventDate"):
            events.append(f"{item['eventAction']}: {item['eventDate']}")
    snippet = " · ".join(names[:3] + events[:3]) or ldh
    found = FoundEntity(
        entity_type="ORG",
        kind="URL",
        value=url,
        display_name=ldh,
        attrs={"rdap": True, "titular": names[0] if names else "", "eventos": events[:6]},
        confidence=0.6,
    )
    out.entities.append(found)
    ref = canonical_key("URL", url)
    if ref != origin_key:
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.55, attrs={"fonte": "rdap"}))
    out.evidence.append(
        FoundEvidence(
            source_label="RDAP",
            url=f"https://rdap.org/domain/{ldh}",
            snippet=snippet[:400],
            payload={"domain": ldh, "titulares": names, "eventos": events[:8]},
            entity_ref=ref,
        )
    )
    if names and " " in names[0]:
        person = FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value=names[0],
            display_name=names[0],
            attrs={"papel": "titular_dominio", "status": "unconfirmed"},
            confidence=0.4,
        )
        out.entities.append(person)
        out.edges.append(
            FoundEdge(
                from_ref=ref,
                to_ref=canonical_key("NAME", names[0]),
                rel_type="RELACIONADO",
                confidence=0.4,
                attrs={"relacao": "titular_rdap"},
            )
        )
    return out


class RdapPublicConnector:
    name = "rdap_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=1,
            timeout=20.0,
            default_headers={"User-Agent": "osint4all/0.1 (rdap)", "Accept": "application/rdap+json, application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.rdap_public_enable, "via": "registro.br / rdap.org"}

    def accepts(self, entity: Entity) -> bool:
        return domain_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.rdap_public_enable:
            raise SkippedDisabled("RDAP desabilitado")
        domain = domain_from_entity(entity)
        if not domain:
            return ConnectorResult()
        urls = (
            [f"https://rdap.registro.br/domain/{domain}", f"https://rdap.org/domain/{domain}"]
            if domain.endswith(".br")
            else [f"https://rdap.org/domain/{domain}"]
        )
        for url in urls:
            resp = self.http.request("GET", url, allow_404=True, max_retries=1)
            if resp.status_code >= 400:
                continue
            try:
                data = resp.json()
            except Exception:
                continue
            if isinstance(data, dict) and (data.get("ldhName") or data.get("entities")):
                return parse_rdap(data, origin_key=entity.canonical_key, domain=domain)
        return ConnectorResult()
