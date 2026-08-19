"""Checagem de URLs públicas canônicas (sem login)."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.http_client import RateLimitedClient
from osint4all.identifiers import canonical_key

PUBLIC_PROFILE_TEMPLATES: list[tuple[str, str]] = [
    ("GitHub", "https://github.com/{user}"),
    ("GitLab", "https://gitlab.com/{user}"),
    ("Reddit", "https://www.reddit.com/user/{user}"),
    ("Medium", "https://medium.com/@{user}"),
    ("Dev.to", "https://dev.to/{user}"),
    ("Hacker News", "https://news.ycombinator.com/user?id={user}"),
    ("Wikipedia (user)", "https://en.wikipedia.org/wiki/User:{user}"),
    ("X", "https://x.com/{user}"),
    ("YouTube", "https://www.youtube.com/@{user}"),
    ("Keybase", "https://keybase.io/{user}"),
    ("Twitch", "https://www.twitch.tv/{user}"),
    ("SoundCloud", "https://soundcloud.com/{user}"),
    ("Telegram", "https://t.me/{user}"),
    ("Pinterest", "https://www.pinterest.com/{user}/"),
    ("Flickr", "https://www.flickr.com/people/{user}/"),
    ("Linktree", "https://linktr.ee/{user}"),
    ("About.me", "https://about.me/{user}"),
]


def parse_public_hits(hits: list[tuple[str, str]], *, origin_key: str) -> ConnectorResult:
    out = ConnectorResult()
    for label, url in hits:
        found = FoundEntity(
            entity_type="PROFILE",
            kind="URL",
            value=url,
            display_name=f"{label}",
            attrs={"network": label},
            confidence=0.7,
        )
        out.entities.append(found)
        ref = canonical_key("URL", url)
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.7))
        out.evidence.append(
            FoundEvidence(
                source_label=f"Perfil público · {label}",
                url=url,
                snippet=f"URL pública respondeu (HTTP 200): {url}",
                payload={"network": label},
                entity_ref=ref,
            )
        )
    return out


def username_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("username:"):
        return entity.canonical_key.split(":", 1)[1]
    for ident in entity.identifiers:
        if ident.kind == "USERNAME":
            return ident.value.lstrip("@").lower()
    if entity.entity_type == "PROFILE" and " " not in entity.display_name:
        return entity.display_name.lstrip("@").lower()
    return None


class UsernamePublicConnector:
    name = "username_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = RateLimitedClient(
            source=self.name,
            max_concurrency=3,
            timeout=12.0,
            default_headers={"User-Agent": "osint4all/0.1 (public profile check)"},
        )

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.username_public_enable,
            "networks": [n for n, _ in PUBLIC_PROFILE_TEMPLATES],
        }

    def accepts(self, entity: Entity) -> bool:
        return username_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.username_public_enable:
            raise SkippedDisabled("username_public desabilitado")
        user = username_from_entity(entity)
        if not user:
            return ConnectorResult()
        hits: list[tuple[str, str]] = []
        for label, template in PUBLIC_PROFILE_TEMPLATES:
            url = template.format(user=user)
            try:
                resp = self.http.request("GET", url, allow_404=True, max_retries=1)
            except Exception:
                continue
            if resp.status_code == 200:
                hits.append((label, url))
        return parse_public_hits(hits, origin_key=entity.canonical_key)
