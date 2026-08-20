"""Checagem de URLs públicas canônicas (sem login)."""

from __future__ import annotations

import re
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
    ("Bitbucket", "https://bitbucket.org/{user}"),
    ("Codeberg", "https://codeberg.org/{user}"),
    ("Reddit", "https://www.reddit.com/user/{user}"),
    ("Medium", "https://medium.com/@{user}"),
    ("Dev.to", "https://dev.to/{user}"),
    ("Hacker News", "https://news.ycombinator.com/user?id={user}"),
    ("Wikipedia (user)", "https://en.wikipedia.org/wiki/User:{user}"),
    ("X", "https://x.com/{user}"),
    ("YouTube", "https://www.youtube.com/@{user}"),
    ("TikTok", "https://www.tiktok.com/@{user}"),
    ("Keybase", "https://keybase.io/{user}"),
    ("Twitch", "https://www.twitch.tv/{user}"),
    ("SoundCloud", "https://soundcloud.com/{user}"),
    ("Telegram", "https://t.me/{user}"),
    ("Pinterest", "https://www.pinterest.com/{user}/"),
    ("Flickr", "https://www.flickr.com/people/{user}/"),
    ("Linktree", "https://linktr.ee/{user}"),
    ("About.me", "https://about.me/{user}"),
    ("Replit", "https://replit.com/@{user}"),
    ("Kaggle", "https://www.kaggle.com/{user}"),
    ("Hugging Face", "https://huggingface.co/{user}"),
    ("npm", "https://www.npmjs.com/~{user}"),
    ("Docker Hub", "https://hub.docker.com/u/{user}"),
    ("Gravatar", "https://gravatar.com/{user}"),
    ("Vimeo", "https://vimeo.com/{user}"),
    ("Dribbble", "https://dribbble.com/{user}"),
    ("Behance", "https://www.behance.net/{user}"),
    ("Steam", "https://steamcommunity.com/id/{user}"),
    ("Lichess", "https://lichess.org/@/{user}"),
    ("Product Hunt", "https://www.producthunt.com/@{user}"),
]

CORE_PROFILE_TEMPLATES = PUBLIC_PROFILE_TEMPLATES[:12]

# Slugs de marca/plataforma e caminhos genéricos — não são o @user do alvo.
RESERVED_USERNAMES = frozenset(
    {
        "github",
        "gitlab",
        "bitbucket",
        "codeberg",
        "reddit",
        "medium",
        "devto",
        "dev",
        "hackernews",
        "news",
        "wikipedia",
        "wiki",
        "x",
        "twitter",
        "nitter",
        "youtube",
        "yt",
        "tiktok",
        "keybase",
        "twitch",
        "soundcloud",
        "telegram",
        "tg",
        "pinterest",
        "flickr",
        "linktree",
        "linktr",
        "about",
        "aboutme",
        "replit",
        "kaggle",
        "huggingface",
        "hugging",
        "npm",
        "docker",
        "dockerhub",
        "gravatar",
        "vimeo",
        "dribbble",
        "behance",
        "steam",
        "lichess",
        "producthunt",
        "instagram",
        "insta",
        "facebook",
        "fb",
        "whatsapp",
        "linkedin",
        "snapchat",
        "discord",
        "threads",
        "mastodon",
        "tumblr",
        "signal",
        "skype",
        "google",
        "apple",
        "microsoft",
        "amazon",
        "netflix",
        "spotify",
        "official",
        "oficial",
        "admin",
        "administrador",
        "root",
        "support",
        "suporte",
        "help",
        "info",
        "contato",
        "contact",
        "login",
        "signup",
        "api",
        "www",
        "http",
        "https",
        "mailto",
        "settings",
        "explore",
        "search",
        "download",
        "app",
        "apps",
        "blog",
        "shop",
        "store",
        "status",
        "privacy",
        "terms",
        "legal",
        "careers",
        "jobs",
        "press",
        "brand",
        "business",
        "ads",
        "security",
        "safety",
        "community",
        "developer",
        "developers",
        "home",
        "index",
        "user",
        "users",
        "profile",
        "perfil",
        "channel",
        "canal",
        "page",
        "pagina",
    }
)


def normalize_username(value: str | None) -> str:
    if not value:
        return ""
    user = str(value).strip().lstrip("@")
    user = user.split("/")[-1].split("?")[0].split("#")[0]
    user = user.casefold()
    return re.sub(r"[^a-z0-9._-]", "", user)


def is_reserved_username(value: str | None) -> bool:
    user = normalize_username(value)
    if not user or len(user) < 2:
        return True
    compact = user.replace(".", "").replace("_", "").replace("-", "")
    return user in RESERVED_USERNAMES or compact in RESERVED_USERNAMES


def parse_public_hits(hits: list[tuple[str, str]], *, origin_key: str, user: str = "") -> ConnectorResult:
    handle = normalize_username(user) or normalize_username(
        origin_key.split(":", 1)[1] if origin_key.startswith("username:") else ""
    )
    out = ConnectorResult()
    if handle and is_reserved_username(handle):
        return out
    for label, url in hits:
        slug = normalize_username(url.rstrip("/").rsplit("/", 1)[-1])
        network = normalize_username(label)
        if is_reserved_username(slug) or (network and slug == network):
            continue
        if handle and slug and slug != handle:
            continue
        found = FoundEntity(
            entity_type="PROFILE",
            kind="URL",
            value=url,
            display_name=f"{label} · @{handle}" if handle else label,
            attrs={"network": label, "username": handle, "status": "confirmed"},
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
                payload={"network": label, "username": handle},
                entity_ref=ref,
            )
        )
    return out


def username_from_entity(entity: Entity) -> str | None:
    raw = ""
    if str(getattr(entity, "canonical_key", "")).startswith("username:"):
        raw = entity.canonical_key.split(":", 1)[1]
    else:
        for ident in getattr(entity, "identifiers", None) or []:
            if ident.kind == "USERNAME":
                raw = ident.value
                break
    user = normalize_username(raw)
    if not user or is_reserved_username(user):
        return None
    return user


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
        templates = CORE_PROFILE_TEMPLATES if getattr(ctx, "core_only", False) else PUBLIC_PROFILE_TEMPLATES
        hits: list[tuple[str, str]] = []
        for label, template in templates:
            if normalize_username(label) == user or is_reserved_username(user):
                continue
            url = template.format(user=user)
            try:
                resp = self.http.request("GET", url, allow_404=True, max_retries=1)
            except Exception:
                continue
            if resp.status_code == 200:
                hits.append((label, url))
        return parse_public_hits(hits, origin_key=entity.canonical_key, user=user)
