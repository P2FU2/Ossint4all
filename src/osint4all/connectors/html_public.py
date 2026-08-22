"""Parsers de HTML público — DuckDuckGo, OpenSanctions e Portal da Transparência."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from osint4all.security import only_digits

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_TITLE_RE = re.compile(r">([^<]{3,160})<")


def _abs(url: str, base: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    if raw.startswith("http"):
        return raw
    if raw.startswith("/"):
        return urljoin(base, raw)
    return ""


def parse_ddg_html(html: str) -> list[dict[str, str]]:
    """Resultados do html.duckduckgo.com / lite.duckduckgo.com."""
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    blob = html or ""
    for raw in _HREF_RE.findall(blob):
        link = raw
        if "uddg=" in link:
            qs = parse_qs(urlparse(link).query)
            encoded = (qs.get("uddg") or [""])[0]
            link = unquote(encoded)
        link = _abs(link, "https://duckduckgo.com/")
        if not link.startswith("http"):
            continue
        host = urlparse(link).netloc.casefold()
        if "duckduckgo.com" in host or "duck.com" in host:
            continue
        if link in seen:
            continue
        seen.add(link)
        idx = blob.find(raw)
        window = blob[idx : idx + 280]
        title_m = _TITLE_RE.search(window)
        title = " ".join((title_m.group(1) if title_m else link).split())
        hits.append({"url": link, "title": title[:160], "snippet": title[:240]})
        if len(hits) >= 10:
            break
    return hits


def parse_opensanctions_html(html: str, *, origin_key: str) -> ConnectorResult:
    from osint4all.connectors.opensanctions_public import parse_opensanctions_hits

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _HREF_RE.findall(html or ""):
        if "/entities/" not in raw:
            continue
        path = raw.split("?", 1)[0]
        ident = path.rstrip("/").rsplit("/", 1)[-1]
        if not ident or ident in seen or ident in {"entities", "search"}:
            continue
        seen.add(ident)
        idx = (html or "").find(raw)
        window = (html or "")[idx : idx + 220]
        title_m = _TITLE_RE.search(window)
        caption = " ".join((title_m.group(1) if title_m else ident).split())
        rows.append({"id": ident, "caption": caption, "schema": "Person", "datasets": []})
        if len(rows) >= 8:
            break
    return parse_opensanctions_hits(rows, origin_key=origin_key)


def parse_portal_payload(data: Any, *, origin_key: str, lista: str) -> ConnectorResult:
    from osint4all.connectors.transparencia import parse_transparencia_rows

    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("data", "dados", "records", "items", "resultado"):
            value = data.get(key)
            if isinstance(value, list):
                rows = value
                break
    return parse_transparencia_rows(
        [row for row in rows if isinstance(row, dict)],
        origin_key=origin_key,
        lista=lista,
    )


def parse_portal_html(html: str, *, origin_key: str, lista: str) -> ConnectorResult:
    """Tabela pública do portal: nome + CPF/CNPJ no texto."""
    from osint4all.connectors.transparencia import parse_transparencia_rows

    rows: list[dict[str, Any]] = []
    for block in re.split(r"</tr>|<tr", html or "", flags=re.I):
        text = re.sub(r"<[^>]+>", " ", block)
        text = " ".join(text.split())
        if len(text) < 8:
            continue
        docs = re.findall(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b|\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", text)
        nome = ""
        for token in text.split("  "):
            if len(token.split()) >= 2 and not only_digits(token):
                nome = token.strip()[:180]
                break
        if not nome and not docs:
            continue
        doc = only_digits(docs[0]) if docs else ""
        rows.append({"nome": nome or lista, "cpfCnpj": doc, "orgao": lista})
        if len(rows) >= 12:
            break
    if not rows:
        try:
            marker = html.find("{")
            if marker >= 0:
                payload = json.loads(html[marker : html.rfind("}") + 1])
                return parse_portal_payload(payload, origin_key=origin_key, lista=lista)
        except Exception:
            pass
    return parse_transparencia_rows(rows, origin_key=origin_key, lista=lista)


def parse_pep_portal_rows(rows: list[Any], *, origin_key: str, needle: str) -> ConnectorResult:
    from osint4all.connectors.politicos_public import parse_pep_rows

    return parse_pep_rows(rows if isinstance(rows, list) else [], origin_key=origin_key, needle=needle)
