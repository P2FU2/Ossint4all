"""Ecossistema Google público — GHunt sem cookie e sem People API."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.email_public import email_from_entity
from osint4all.connectors.username_public import username_from_entity
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.identifiers import canonical_key
from osint4all.intel.google import classify_google_url, public_google_hints


def _query_from_entity(entity: Entity) -> tuple[str, str, str]:
    email = email_from_entity(entity) or ""
    user = username_from_entity(entity) or ""
    name = (entity.display_name or "").strip()
    if name.startswith("@"):
        user = user or name.lstrip("@")
        name = ""
    return name, user, email


class GooglePublicConnector:
    name = "google_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.google_public_enable,
            "via": "URLs públicas (Scholar / News / Maps / YouTube)",
        }

    def accepts(self, entity: Entity) -> bool:
        name, user, email = _query_from_entity(entity)
        return bool(user or email or (entity.entity_type == "PERSON" and " " in name))

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.google_public_enable:
            raise SkippedDisabled("Google público desabilitado")
        name, user, email = _query_from_entity(entity)
        query = name or user or (email.split("@", 1)[0] if email else "")
        out = ConnectorResult()
        for label, snippet, url in public_google_hints(query=query, username=user, email=email):
            found = FoundEntity(
                entity_type="PUBLICATION",
                kind="URL",
                value=url,
                display_name=label,
                attrs={"network": label, "fonte": "google_public"},
                confidence=0.35,
            )
            out.entities.append(found)
            ref = canonical_key("URL", url)
            out.edges.append(FoundEdge(from_ref=entity.canonical_key, to_ref=ref, rel_type="MENCAO", confidence=0.35, attrs={"fonte": "google_public"}))
            out.evidence.append(FoundEvidence(source_label=label, url=url, snippet=snippet, payload={"network": label}, entity_ref=ref))
        existing = str((entity.attrs or {}).get("url") or entity.display_name or "")
        label = classify_google_url(existing)
        if label:
            out.notes.append(f"URL já conhecida classificada como {label}.")
        if email.endswith("@gmail.com") or email.endswith("@googlemail.com"):
            out.notes.append("Gmail no alvo: só páginas públicas. Sem cookie GHunt e sem People API.")
        return out
