"""Serviços públicos ligados a um e-mail — estilo Holehe, sem caixa e sem leak."""

from __future__ import annotations

import hashlib
from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key


def email_from_entity(entity: Entity) -> str | None:
    if str(getattr(entity, "canonical_key", "")).startswith("email:"):
        value = entity.canonical_key.split(":", 1)[1]
        return value if "@" in value else None
    for ident in getattr(entity, "identifiers", None) or []:
        if ident.kind == "EMAIL" and "@" in (ident.value or ""):
            return ident.value.strip().lower()
    raw = str((entity.attrs or {}).get("email") or "")
    return raw.lower() if "@" in raw else None


def parse_keybase_lookup(data: dict[str, Any], *, email: str, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    if not isinstance(data, dict):
        return out
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    them = data.get("them") if isinstance(data.get("them"), list) else []
    if status.get("code") not in (0, None) or not them:
        return out
    first = them[0] if isinstance(them[0], dict) else {}
    basics = first.get("basics") if isinstance(first.get("basics"), dict) else {}
    user = str(basics.get("username") or "").strip()
    if not user:
        return out
    url = f"https://keybase.io/{user}"
    found = FoundEntity(
        entity_type="PROFILE",
        kind="USERNAME",
        value=user,
        display_name=f"Keybase · @{user}",
        attrs={"network": "Keybase", "email": email},
        confidence=0.7,
    )
    out.entities.append(found)
    ref = canonical_key("USERNAME", user)
    out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.7, attrs={"fonte": "keybase"}))
    out.evidence.append(
        FoundEvidence(source_label="Keybase", url=url, snippet=f"{email} ligado a @{user}", payload={"username": user}, entity_ref=ref)
    )
    return out


def parse_gravatar_entry(data: dict[str, Any], *, email: str, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    entries = data.get("entry") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return out
    entry = entries[0] if isinstance(entries[0], dict) else {}
    name = str(entry.get("displayName") or entry.get("preferredUsername") or "").strip()
    profile = str(entry.get("profileUrl") or f"https://gravatar.com/{entry.get('hash') or ''}").strip()
    if not profile.startswith("http"):
        return out
    found = FoundEntity(
        entity_type="PROFILE",
        kind="URL",
        value=profile,
        display_name=name or "Gravatar",
        attrs={"network": "Gravatar", "email": email},
        confidence=0.65,
    )
    out.entities.append(found)
    ref = canonical_key("URL", profile)
    out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.65, attrs={"fonte": "gravatar"}))
    out.evidence.append(
        FoundEvidence(source_label="Gravatar", url=profile, snippet=name or email, payload={"display": name}, entity_ref=ref)
    )
    return out


class EmailPublicConnector:
    name = "email_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=2,
            timeout=12.0,
            default_headers={"User-Agent": "osint4all/0.1 (public email lookup)", "Accept": "application/json"},
        )

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.email_public_enable, "via": "keybase + gravatar"}

    def accepts(self, entity: Entity) -> bool:
        return email_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.email_public_enable:
            raise SkippedDisabled("E-mail público desabilitado")
        email = email_from_entity(entity)
        if not email:
            return ConnectorResult()
        out = ConnectorResult()
        out.merge(self._keybase(email, entity.canonical_key))
        out.merge(self._gravatar(email, entity.canonical_key))
        return out

    def _keybase(self, email: str, origin_key: str) -> ConnectorResult:
        try:
            resp = self.http.request(
                "GET",
                "https://keybase.io/_/api/1.0/user/lookup.json",
                params={"email": email},
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            return parse_keybase_lookup(resp.json(), email=email, origin_key=origin_key)
        except Exception:
            return ConnectorResult()

    def _gravatar(self, email: str, origin_key: str) -> ConnectorResult:
        digest = hashlib.md5(email.encode("utf-8"), usedforsecurity=False).hexdigest()
        try:
            resp = self.http.request(
                "GET",
                f"https://en.gravatar.com/{digest}.json",
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            return ConnectorResult()
        if resp.status_code >= 400:
            return ConnectorResult()
        try:
            return parse_gravatar_entry(resp.json(), email=email, origin_key=origin_key)
        except Exception:
            return ConnectorResult()
