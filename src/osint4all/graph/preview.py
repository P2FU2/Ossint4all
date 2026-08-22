"""Prévia pública de URL: PDF, imagem, matéria (Open Graph) e perfil social."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from osint4all.connectors.base import FoundEntity

_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
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
    "flickr.com",
    "huggingface.co",
    "ko-fi.com",
    "linktr.ee",
    "soundcloud.com",
    "about.me",
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


def _host(url: str) -> str:
    host = urlparse(url or "").netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def is_social_url(url: str) -> bool:
    host = _host(url)
    return any(host == item or host.endswith("." + item) for item in _SOCIAL_HOSTS)


def is_public_http_url(url: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold()
    if not host or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"):
        return False
    if host.startswith(("10.", "192.168.", "169.254.")):
        return False
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
        except (IndexError, ValueError):
            return True
        if 16 <= second <= 31:
            return False
    return True


def opensanctions_entity_url(ident: str) -> str:
    slug = (ident or "").strip().strip("/")
    if re.fullmatch(r"q\d+", slug, re.I):
        slug = "Q" + slug[1:]
    return f"https://www.opensanctions.org/entities/{slug}"


def normalize_official_url(url: str) -> str:
    """Corrige IDs públicos case-sensitive (OpenSanctions / Wikidata)."""
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return raw
    parsed = urlparse(raw)
    host = (parsed.netloc or "").casefold()
    path = parsed.path or ""
    if "opensanctions.org" in host:
        path = re.sub(r"/entities/q(\d+)", lambda m: f"/entities/Q{m.group(1)}", path, flags=re.I)
    if "wikidata.org" in host:
        path = re.sub(r"/wiki/q(\d+)", lambda m: f"/wiki/Q{m.group(1)}", path, flags=re.I)
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def verify_source_url(url: str) -> dict[str, Any]:
    """Confirma se a fonte oficial responde. 404/410 não entram no grafo."""
    url = normalize_official_url(url)
    if not is_public_http_url(url):
        return {"ok": False, "status": 0, "final_url": url, "reason": "inválida"}
    if not _live():
        return {"ok": True, "status": 200, "final_url": url, "reason": ""}
    raw, _ctype, status = _fetch_status(url)
    if status in {404, 410} and url != normalize_official_url(url):
        alt = normalize_official_url(url)
        raw, _ctype, status = _fetch_status(alt)
        url = alt
    ok = 200 <= status < 400
    if ok and raw:
        head = raw[:5000].decode("utf-8", errors="ignore").casefold()
        if "page not found" in head or "página não encontrada" in head:
            ok = False
            status = 404
    return {
        "ok": ok,
        "status": status,
        "final_url": url,
        "reason": "" if ok else "página não encontrada",
    }


def entity_source_url(entity: Any = None, *, key: str = "", attrs: dict[str, Any] | None = None) -> str:
    bag = attrs if attrs is not None else dict(getattr(entity, "attrs", None) or {})
    for field in ("page_url", "fonte", "maps_url"):
        val = str(bag.get(field) or "").strip()
        if val.startswith("http"):
            return normalize_official_url(val)
    raw_key = key or str(getattr(entity, "canonical_key", "") or "")
    if raw_key.startswith("url:"):
        return normalize_official_url(raw_key[4:])
    return ""


def username_from_url(url: str) -> str:
    path = urlparse(url or "").path.strip("/")
    if not path:
        return ""
    part = path.split("/")[-1]
    if part.casefold() in {"people", "user", "users", "profile", "channel", "c"}:
        parts = path.split("/")
        part = parts[-1] if len(parts) == 1 else (parts[-1] or (parts[-2] if len(parts) > 1 else ""))
    return part.lstrip("@").split("?")[0].split("#")[0]


def social_avatar_url(url: str, username: str = "", network: str = "") -> str:
    """Avatar público conhecido — sem chave. Serve para o nó já nascer com foto."""
    user = (username or username_from_url(url) or "").strip().lstrip("@")
    host = _host(url)
    net = (network or "").casefold()
    if not user or user.casefold() in {"www", "http", "https"}:
        return ""
    if "github.com" in host or net == "github":
        return f"https://github.com/{user}.png?size=240"
    if "gitlab.com" in host or net == "gitlab":
        return f"https://gitlab.com/{user}.png"
    if "gravatar.com" in host or net == "gravatar":
        return f"https://www.gravatar.com/avatar/{user}?s=240&d=identicon"
    if host in {"x.com", "twitter.com"} or net in {"x", "twitter"}:
        return f"https://unavatar.io/twitter/{user}"
    if "instagram.com" in host or net == "instagram":
        return f"https://unavatar.io/instagram/{user}"
    if "youtube.com" in host or "youtu.be" in host or net == "youtube":
        return f"https://unavatar.io/youtube/{user}"
    if "tiktok.com" in host or net == "tiktok":
        return f"https://unavatar.io/tiktok/{user}"
    if "reddit.com" in host or net == "reddit":
        return f"https://unavatar.io/reddit/{user}"
    if "twitch.tv" in host or net == "twitch":
        return f"https://unavatar.io/twitch/{user}"
    if "facebook.com" in host or "fb.com" in host or net == "facebook":
        return f"https://unavatar.io/facebook/{user}"
    if "linkedin.com" in host or net == "linkedin":
        return f"https://unavatar.io/linkedin/{user}"
    if host:
        return f"https://unavatar.io/{host}/{user}"
    return ""


def decorate_graph_attrs(
    attrs: dict[str, Any],
    *,
    url: str = "",
    entity_type: str = "",
    entity_id: str = "",
    investigation_id: str = "",
) -> dict[str, Any]:
    """Completa thumb/título no payload do grafo. Foto de perfil/matéria vai pelo proxy do caso."""
    source = url or str(attrs.get("page_url") or attrs.get("fonte") or "")
    kind = str(attrs.get("preview_kind") or attrs.get("tipo") or "")
    if source and not kind:
        kind = preview_kind_for_url(source)
        attrs["preview_kind"] = kind
    social = entity_type == "PROFILE" or kind == "social" or attrs.get("tipo") == "social"
    if social:
        attrs.setdefault("preview_kind", "social")
        attrs.setdefault("tipo", "social")
        remote = str(attrs.get("thumb") or attrs.get("remote_thumb") or "")
        if remote.startswith("http") and "/entidades/" not in remote:
            attrs.setdefault("remote_thumb", remote)
    if entity_type in {"PROFILE", "PUBLICATION"} and investigation_id and entity_id:
        attrs["thumb"] = f"/app/casos/{investigation_id}/entidades/{entity_id}/thumb"
    return attrs


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
    if "thumb" not in bag:
        for tag in _LINK_RE.findall(html or ""):
            attrs = {key.casefold(): val.strip() for key, val in _ATTR_RE.findall(tag)}
            rel = (attrs.get("rel") or "").casefold()
            href = attrs.get("href") or ""
            if rel in {"image_src", "apple-touch-icon", "icon"} and href:
                image = href
                if image.startswith("//"):
                    image = "https:" + image
                elif image.startswith("/") and base_url:
                    image = urljoin(base_url, image)
                if image.startswith("http") and rel == "image_src":
                    bag["thumb"] = image
                    break
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
    if kind == "social" and not attrs.get("thumb"):
        avatar = social_avatar_url(url)
        if avatar:
            attrs["thumb"] = avatar
    if attrs.get("og_title") and not attrs.get("snippet"):
        attrs["snippet"] = attrs["og_title"]
    return attrs


def fetch_preview(url: str) -> dict[str, Any]:
    """GET público curto. Em teste não sai da máquina."""
    kind = preview_kind_for_url(url)
    if kind == "pdf":
        extra = preview_from_html("", url)
        if _live() and is_public_http_url(url):
            raw, ctype = _fetch_bytes(url)
            if raw.startswith(b"%PDF") or "pdf" in ctype:
                text = pdf_first_page_text(raw)
                if text:
                    extra["description"] = text[:500]
                    extra["snippet"] = text[:220]
        return extra
    if kind == "image":
        return preview_from_html("", url)
    if not _live() or not str(url).startswith("http"):
        extra = {"preview_kind": kind, "page_url": url, "tipo": kind}
        if kind == "social":
            avatar = social_avatar_url(url)
            if avatar:
                extra["thumb"] = avatar
        return extra
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


def _mark_dead_source(found: FoundEntity) -> None:
    if found.kind != "URL":
        return
    url = normalize_official_url(str(found.value or found.attrs.get("page_url") or ""))
    if not url.startswith("http"):
        return
    attrs = dict(found.attrs or {})
    if url != str(found.value or ""):
        found.value = url
        attrs["page_url"] = url
    if not _live():
        found.attrs = attrs
        return
    check = verify_source_url(url)
    attrs["fonte_ok"] = check["ok"]
    if check.get("final_url") and check["ok"]:
        found.value = str(check["final_url"])
        attrs["page_url"] = found.value
    if int(check.get("status") or 0) in {404, 410}:
        attrs["_drop"] = True
        attrs["motivo"] = "fonte oficial não encontrada"
    found.attrs = attrs


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
    for found in entities:
        _mark_dead_source(found)


def _xml(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _wrap_lines(text: str, width: int, limit: int) -> list[str]:
    words = str(text or "").split()
    rows: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) <= width:
            current = trial
            continue
        if current:
            rows.append(current)
        current = word
        if len(rows) >= limit:
            return rows
    if current and len(rows) < limit:
        rows.append(current)
    return rows


def render_card_svg(*, kicker: str = "", title: str = "", body: str = "", kind: str = "article") -> bytes:
    """Cartão SVG sempre válido — o nó nunca fica preto."""
    pdf = kind == "pdf"
    bg = "#120e08" if pdf else "#0c1410"
    ink = "#d4b45a" if pdf else "#8fbc8f"
    title_lines = _wrap_lines(title, 21, 3)
    body_lines = _wrap_lines(body, 23, 9 if pdf else 6)
    y = 26
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="132" height="156" viewBox="0 0 132 156">',
        f'<rect width="132" height="156" fill="{bg}"/>',
        f'<rect x="5" y="5" width="122" height="146" fill="none" stroke="{ink}" stroke-width="1.2"/>',
        f'<text x="12" y="{y}" fill="{ink}" font-size="8" font-family="IBM Plex Mono,monospace">{_xml((kicker or kind).upper()[:26])}</text>',
    ]
    y += 16
    for line in title_lines:
        parts.append(
            f'<text x="12" y="{y}" fill="#d7e4dc" font-size="10" font-family="IBM Plex Mono,monospace">{_xml(line)}</text>'
        )
        y += 13
    y += 4
    for line in body_lines:
        parts.append(
            f'<text x="12" y="{y}" fill="#8aa394" font-size="8" font-family="IBM Plex Mono,monospace">{_xml(line)}</text>'
        )
        y += 11
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def pdf_first_page_text(data: bytes) -> str:
    if not data or not data.startswith(b"%PDF"):
        return ""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        page = PdfReader(BytesIO(data)).pages[0]
        return " ".join((page.extract_text() or "").split())[:900]
    except Exception:  # noqa: BLE001
        return ""


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    raw, ctype, _status = _fetch_status(url)
    return raw, ctype


def _fetch_status(url: str) -> tuple[bytes, str, int]:
    if not _live() or not is_public_http_url(url):
        return b"", "", 0
    from osint4all.http_client import RateLimitedClient

    http = RateLimitedClient(
        source="thumb",
        max_concurrency=2,
        timeout=16.0,
        default_headers={
            "Accept": "text/html,application/xhtml+xml,application/pdf,image/*,*/*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    )
    resp, err = http.safe_request("GET", url, max_retries=1)
    if resp is None:
        return b"", "", 0
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().casefold()
    return resp.content[: 6 * 1024 * 1024], ctype, int(resp.status_code or 0)


def _is_image_bytes(data: bytes, ctype: str) -> bool:
    if not data:
        return False
    if ctype.startswith("image/") and "svg+xml" not in ctype:
        return True
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] in {b"GIF8", b"RIFF"}:
        return True
    head = data.lstrip()[:200].casefold()
    return head.startswith(b"<svg") or b"<svg" in head


def _thumb_cache_file(entity: Any, suffix: str):
    inv = str(getattr(entity, "investigation_id", "") or "")
    eid = str(getattr(entity, "id", "") or "")
    if not inv or not eid or not _live():
        return None
    from osint4all.paths import project_root

    folder = project_root() / "data" / "uploads" / inv / "thumbs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{eid}{suffix}"


def _read_thumb_cache(entity: Any) -> tuple[bytes, str] | None:
    for suffix, ctype in ((".jpg", "image/jpeg"), (".png", "image/png"), (".svg", "image/svg+xml"), (".webp", "image/webp")):
        path = _thumb_cache_file(entity, suffix)
        if path is not None and path.exists():
            data = path.read_bytes()
            if data:
                return data, ctype
    return None


def _write_thumb_cache(entity: Any, data: bytes, ctype: str) -> None:
    suffix = ".svg"
    if "jpeg" in ctype or "jpg" in ctype:
        suffix = ".jpg"
    elif "png" in ctype:
        suffix = ".png"
    elif "webp" in ctype:
        suffix = ".webp"
    path = _thumb_cache_file(entity, suffix)
    if path is None:
        return
    path.write_bytes(data)


def build_entity_thumb(entity: Any) -> tuple[bytes, str]:
    """Devolve sempre uma imagem (foto real ou cartão com o texto da fonte)."""
    cached = _read_thumb_cache(entity)
    if cached:
        return cached
    attrs = dict(getattr(entity, "attrs", None) or {})
    title = str(attrs.get("og_title") or getattr(entity, "display_name", "") or "fonte")
    body = str(attrs.get("description") or attrs.get("snippet") or "")
    url = entity_source_url(entity)
    kind = str(attrs.get("preview_kind") or attrs.get("tipo") or (preview_kind_for_url(url) if url else "article"))
    network = str(attrs.get("network") or "")
    user = str(attrs.get("username") or username_from_url(url))
    if _live():
        seen: set[str] = set()
        for cand in (
            str(attrs.get("remote_thumb") or ""),
            str(attrs.get("thumb") or ""),
            str(attrs.get("profile_photo") or ""),
            social_avatar_url(url, user, network) if kind == "social" else "",
        ):
            if not cand.startswith("http") or "/entidades/" in cand or cand in seen:
                continue
            seen.add(cand)
            raw, ctype = _fetch_bytes(cand)
            if _is_image_bytes(raw, ctype):
                _write_thumb_cache(entity, raw, ctype or "image/jpeg")
                return raw, ctype or "image/jpeg"
        if is_public_http_url(url):
            raw, ctype = _fetch_bytes(url)
            if raw.startswith(b"%PDF") or "pdf" in ctype or looks_like_pdf(url):
                text = pdf_first_page_text(raw) or body
                svg = render_card_svg(kicker="PDF · documento", title=title, body=text or title, kind="pdf")
                _write_thumb_cache(entity, svg, "image/svg+xml")
                return svg, "image/svg+xml"
            if _is_image_bytes(raw, ctype):
                _write_thumb_cache(entity, raw, ctype or "image/jpeg")
                return raw, ctype or "image/jpeg"
            if raw:
                html = raw.decode("utf-8", errors="ignore")[:80000]
                og = parse_open_graph(html, base_url=url)
                if og.get("og_title"):
                    title = og["og_title"]
                if og.get("description"):
                    body = og["description"]
                image = og.get("thumb") or ""
                if image.startswith("http"):
                    img, ictype = _fetch_bytes(image)
                    if _is_image_bytes(img, ictype):
                        _write_thumb_cache(entity, img, ictype or "image/jpeg")
                        return img, ictype or "image/jpeg"
    if kind == "social":
        kicker = network or "Rede social"
        if user and (not title or title.startswith("http")):
            title = f"{kicker} · @{user}"
        body = body or (f"perfil público @{user}" if user else "perfil público")
    elif kind == "pdf":
        kicker = "PDF · documento"
    else:
        kicker = "Matéria"
    svg = render_card_svg(kicker=kicker, title=title, body=body or title, kind="pdf" if kind == "pdf" else kind)
    if _live():
        _write_thumb_cache(entity, svg, "image/svg+xml")
    return svg, "image/svg+xml"
