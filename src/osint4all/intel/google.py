"""GHunt sem sessão: só normaliza URLs públicas do ecossistema Google."""

from __future__ import annotations

from urllib.parse import quote, urlparse

_GOOGLE_NET = (
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("maps.google.", "Google Maps"),
    ("google.com/maps", "Google Maps"),
    ("news.google.", "Google News"),
    ("scholar.google.", "Google Scholar"),
    ("sites.google.", "Google Sites"),
    ("docs.google.", "Google Docs"),
    ("drive.google.", "Google Drive"),
    ("photos.google.", "Google Photos"),
    ("blogger.com", "Blogger"),
    ("blogspot.", "Blogger"),
)


def classify_google_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = f"{host}{parsed.path or ''}"
    for needle, label in _GOOGLE_NET:
        if needle in host or needle in path:
            return label
    return None


def public_google_hints(*, query: str, username: str = "", email: str = "") -> list[tuple[str, str, str]]:
    """Páginas de busca/perfil públicas. Sem cookie, sem People API."""
    q = (query or username or (email.split("@", 1)[0] if email else "")).strip().lstrip("@")
    if len(q) < 2:
        return []
    enc = quote(q)
    user = (username or q).lstrip("@")
    rows = [
        ("Google Scholar", f"Busca pública de autor «{q}»", f"https://scholar.google.com/citations?view_op=search_authors&mauthors={enc}"),
        ("Google News", f"Menções públicas de «{q}»", f"https://news.google.com/search?q={enc}"),
        ("Google Maps", f"Busca pública de lugar/nome «{q}»", f"https://www.google.com/maps/search/{enc}"),
    ]
    if user and " " not in user:
        rows.insert(0, ("YouTube", f"Canal @{user} se o handle existir", f"https://www.youtube.com/@{quote(user)}"))
    return rows[:6]
