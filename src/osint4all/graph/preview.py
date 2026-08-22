"""Prévia pública de URL: PDF, imagem, matéria (Open Graph) e perfil social."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from osint4all.connectors.base import FoundEntity

_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"""([a-zA-Z_:-]+)\s*=\s*["']([^"']*)["']""")
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{1,200})</title>", re.I)
_SOCIAL_HOSTS = (
    "x.com",
    "twitter.com",
    "instagram.com",
    "facebook.com",
    "fb.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "github.com",
    "gitlab.com",
    "reddit.com",
    "t.me",
    "telegram.me",
    "threads.net",
    "bsky.app",
    "twitch.tv",
    "pinterest.com",
    "medium.com",
)


def _live() -> bool:
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


_MAX_LIVE = 8


def looks_like_pdf(url: str) -> bool:
    raw = (url or "").casefold()
    path = urlparse(url or "").path.casefold()
    return path.endswith(".pdf") or ".pdf?" in raw or "/pdf/" in path


def looks_like_image(url: str) -> bool:
    path = urlparse(url or "").path.casefold()
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))


def is_social_url(url: str) -> bool:
    host = urlparse(url or "").netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    return any(host == item or host.endswith("." + item) for item in _SOCIAL_HOSTS)


def youtube_embed(url: str) -> str:
    host = urlparse(url or "").netloc.casefold()
    query = urlparse(url or "").query
    path = urlparse(url or "").path
    video = ""
    if "youtu.be" in host:
        video = path.strip("/").split("/", 1)[0]
    elif "youtube.com" in host:
        if "v=" in query:
            video = query.split("v=", 1)[1].split("&", 1)[0]
        elif "/embed/" in path:
            video = path.rsplit("/embed/", 1)[-1].split("/", 1)[0]
        elif "/@" not in path and path.strip("/"):
            video = ""
    if video and re.fullmatch(r"[\w-]{6,20}", video):
        return f"https://www.youtube.com/embed/{video}"
    return ""


def parse_open_graph(html: str, *, base_url: str = "") -> dict[str, str]:
    bag: dict[str, str] = {}
    for tag in _META_RE.findall(html or ""):
        attrs = {key.casefold(): val.strip() for key, val in _ATTR_RE.findall(tag)}
        prop = attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or ""
        content = attrs.get("content") or ""
        if not prop or not content:
            continue
        key = prop.casefold()
        if key in {"og:title", "twitter:title"} and "og_title" not in bag:
            bag["og_title"] = content[:220]
        elif key in {"og:description", "twitter:description", "description"} and "description" not in bag:
            bag["description"] = content[:500]
        elif key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"} and "thumb" not in bag:
            image = content
            if image.startswith("//"):
                image = "https:" + image
            elif image.startswith("/") and base_url:
                image = urljoin(base_url, image)
            if image.startswith("http"):
                bag["thumb"] = image
    if "og_title" not in bag:
        title = _TITLE_RE.search(html or "")
        if title:
            bag["og_title"] = " ".join(title.group(1).split())[:220]
    return bag


def preview_kind_for_url(url: str) -> str:
    if looks_like_pdf(url):
        return "pdf"
    if looks_like_image(url):
        return "image"
    if is_social_url(url):
        return "social"
    return "article"


def preview_from_html(html: str, url: str) -> dict[str, Any]:
    kind = preview_kind_for_url(url)
    attrs: dict[str, Any] = {
        "preview_kind": kind,
        "page_url": url,
        "tipo": "pdf" if kind == "pdf" else ("imagem" if kind == "image" else kind),
    }
    embed = youtube_embed(url)
    if embed:
        attrs["embed_url"] = embed
    if kind == "pdf":
        return attrs
    if kind == "image":
        attrs["thumb"] = url
        return attrs
    attrs.update(parse_open_graph(html, base_url=url))
    if attrs.get("og_title") and not attrs.get("snippet"):
        attrs["snippet"] = attrs["og_title"]
    return attrs


def fetch_preview(url: str) -> dict[str, Any]:
    """GET público curto. Em teste não sai da máquina."""
    kind = preview_kind_for_url(url)
    if kind == "pdf":
        return preview_from_html("", url)
    if kind == "image":
        return preview_from_html("", url)
    if not _live() or not str(url).startswith("http"):
        return {"preview_kind": kind, "page_url": url, "tipo": kind}
    from osint4all.http_client import RateLimitedClient

    http = RateLimitedClient(
        source="preview",
        max_concurrency=2,
        timeout=10.0,
        default_headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "osint4all/0.3 (https://github.com/P2FU2/Ossint4all; public preview)",
        },
    )
    resp, err = http.safe_request("GET", url, max_retries=1)
    if err or resp is None:
        return {"preview_kind": kind, "page_url": url, "tipo": kind}
    ctype = (resp.headers.get("content-type") or "").casefold()
    if "pdf" in ctype:
        return preview_from_html("", url)
    if ctype.startswith("image/"):
        return {"preview_kind": "image", "thumb": url, "page_url": url, "tipo": "imagem"}
    return preview_from_html((resp.text or "")[:80000], url)


def attach_preview(found: FoundEntity) -> FoundEntity:
    if found.kind != "URL":
        return found
    url = str(found.value or found.attrs.get("page_url") or "").strip()
    if not url.startswith("http"):
        return found
    attrs = dict(found.attrs or {})
    if attrs.get("thumb") and attrs.get("preview_kind"):
        return found
    extra = fetch_preview(url)
    for key, val in extra.items():
        if val not in (None, "", [], {}) and not attrs.get(key):
            attrs[key] = val
    if extra.get("og_title") and (not found.display_name or found.display_name.startswith("http")):
        found.display_name = str(extra["og_title"])[:160]
    found.attrs = attrs
    return found


def enrich_found_entities(entities: list[FoundEntity]) -> None:
    """Carimba PDF/imagem na hora; busca Open Graph só em URLs sem prévia, com teto."""
    live = 0
    for found in entities:
        if found.kind != "URL":
            continue
        url = str(found.value or "").strip()
        if not url.startswith("http"):
            continue
        attrs = dict(found.attrs or {})
        kind = preview_kind_for_url(url)
        if looks_like_pdf(url) or looks_like_image(url):
            attach_preview(found)
            continue
        if attrs.get("thumb") and attrs.get("preview_kind"):
            continue
        if not _live() or live >= _MAX_LIVE:
            if not attrs.get("preview_kind"):
                attrs["preview_kind"] = kind
                attrs.setdefault("page_url", url)
                found.attrs = attrs
            continue
        live += 1
        attach_preview(found)
