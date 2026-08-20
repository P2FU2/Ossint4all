"""Notícias e imagens públicas do alvo/caso. Sem baixar arquivo, sem leak de CPF."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from osint4all.config import Settings, get_settings
from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity, FoundEvidence
from osint4all.connectors.web_search import WebSearchConnector, searxng_bases, web_search_ready
from osint4all.identifiers import canonical_key
from osint4all.security import only_digits
from osint4all.validators import format_plate, looks_like_plate, validate_cnpj, validate_cpf

_QUERY_KINDS = ("NAME", "CNPJ", "USERNAME", "PLATE", "EMAIL", "CNJ", "COMPANY")
_GENERIC_MAIL = frozenset({"gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com"})


@dataclass
class NewsItem:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    when: str = ""
    via: str = ""


@dataclass
class ImageItem:
    title: str
    page_url: str
    thumb: str
    source: str = ""
    via: str = ""


@dataclass(frozen=True)
class SearchCombo:
    label: str
    query: str
    category: str
    parts: tuple[str, ...]


@dataclass
class MediaBundle:
    queries: list[str] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    images: list[ImageItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = True


def _live(settings: Settings) -> bool:
    if settings.env == "test":
        return False
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _format_cnpj(raw: str) -> str:
    digits = only_digits(raw)
    if len(digits) != 14:
        return raw.strip()
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _public_term(kind: str, value: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    kind = (kind or "").upper()
    if kind == "NAME":
        parts = [p for p in text.split() if p]
        return text if len(parts) >= 2 else None
    if kind == "CNPJ" and validate_cnpj(text):
        return _format_cnpj(text)
    if kind == "USERNAME":
        return text if text.startswith("@") else f"@{text.lstrip('@')}"
    if kind == "PLATE" and looks_like_plate(text):
        return format_plate(text)
    if kind == "EMAIL" and "@" in text:
        return text.lower()
    if kind == "CNJ":
        return text
    if kind == "COMPANY":
        return text if len(text) >= 3 and not text.isdigit() else None
    if kind == "CPF" and validate_cpf(text):
        return None
    return None


def _clean_title(extra: str) -> str:
    title = (extra or "").strip()
    for prefix in ("Consulta · ", "Alvo · ", "Caso corrente"):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
    return title


def _public_fields(fields: dict[str, str], *, extra: str = "") -> dict[str, str]:
    terms: dict[str, str] = {}
    for kind in _QUERY_KINDS:
        term = _public_term(kind, fields.get(kind) or "")
        if term:
            terms[kind] = term
    title = _clean_title(extra)
    if "NAME" not in terms and title and " " in title:
        terms["NAME"] = title
    return terms


def _quote(term: str) -> str:
    return f'"{(term or "").strip()}"'


def plan_search_combos(fields: dict[str, str], *, extra: str = "") -> list[SearchCombo]:
    """Cruza os dados: par especializa; termo sozinho só entra se ainda não foi usado num par."""
    terms = _public_fields(fields, extra=extra)
    name = terms.get("NAME")
    company = terms.get("COMPANY")
    cnpj = terms.get("CNPJ")
    user = terms.get("USERNAME")
    plate = terms.get("PLATE")
    email = terms.get("EMAIL")
    cnj = terms.get("CNJ")
    firm = company or cnpj
    domain = ""
    if email and "@" in email:
        domain = email.split("@", 1)[1].lower()
        if domain in _GENERIC_MAIL:
            domain = ""

    combos: list[SearchCombo] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, query: str, category: str, *parts: str) -> None:
        key = (category, " ".join(parts).casefold())
        if key in seen or not query.strip():
            return
        seen.add(key)
        combos.append(SearchCombo(label=label, query=query, category=category, parts=tuple(parts)))

    if name and firm:
        add(
            "nome + empresa (notícia)",
            f"{_quote(name)} {_quote(firm)} (notícia OR jornal OR sócio OR QSA)",
            "news",
            name,
            firm,
        )
        add("nome + empresa (foto)", f"{_quote(name)} {_quote(firm)}", "images", name, firm)
    if name and user:
        add(
            "nome + @user (notícia)",
            f"{_quote(name)} {_quote(user)} (perfil OR rede OR github)",
            "news",
            name,
            user,
        )
        add("nome + @user (foto)", f"{_quote(name)} {_quote(user)}", "images", name, user)
    if name and plate:
        add(
            "nome + placa (notícia)",
            f"{_quote(name)} {_quote(plate)} (placa OR veículo OR acidente)",
            "news",
            name,
            plate,
        )
        add("nome + placa (foto)", f"{_quote(plate)} {_quote(name)}", "images", name, plate)
    if name and email:
        add("nome + e-mail (notícia)", f"{_quote(name)} {_quote(email)}", "news", name, email)
        if domain:
            add("nome + domínio (notícia)", f"{_quote(name)} {_quote(domain)}", "news", name, domain)
    if name and cnj:
        add(
            "nome + processo (notícia)",
            f"{_quote(name)} {_quote(cnj)} (processo OR tribunal OR sentença)",
            "news",
            name,
            cnj,
        )
    if cnpj and user and not name:
        add("CNPJ + @user (notícia)", f"{_quote(cnpj)} {_quote(user)}", "news", cnpj, user)
    if cnpj and plate and not name:
        add("CNPJ + placa (notícia)", f"{_quote(cnpj)} {_quote(plate)}", "news", cnpj, plate)

    paired_news = {part.casefold() for combo in combos if combo.category == "news" for part in combo.parts}
    paired_images = {part.casefold() for combo in combos if combo.category == "images" for part in combo.parts}

    singles = (
        (name, "nome (notícia)", _news_query(name) if name else "", "nome (foto)", _quote(name) if name else ""),
        (cnpj, "CNPJ (notícia)", f"{_quote(cnpj)} (empresa OR Receita OR QSA)" if cnpj else "", "CNPJ (foto)", _quote(cnpj) if cnpj else ""),
        (user, "@user (notícia)", f"{_quote(user)} (perfil OR username)" if user else "", "@user (foto)", _quote(user) if user else ""),
        (plate, "placa (notícia)", f"{_quote(plate)} (placa OR veículo)" if plate else "", "placa (foto)", _quote(plate) if plate else ""),
        (email, "e-mail (notícia)", _quote(email) if email else "", "", ""),
        (cnj, "processo (notícia)", f"{_quote(cnj)} (processo OR CNJ)" if cnj else "", "", ""),
        (
            company if company and company.casefold() != (cnpj or "").casefold() else None,
            "empresa (notícia)",
            f"{_quote(company)} (empresa OR notícia)" if company else "",
            "empresa (foto)",
            _quote(company) if company else "",
        ),
    )
    for term, news_label, news_q, img_label, img_q in singles:
        if not term:
            continue
        key = term.casefold()
        if news_q and key not in paired_news:
            add(news_label, news_q, "news", term)
        if img_q and key not in paired_images:
            add(img_label, img_q, "images", term)

    return combos[:14]


def fields_from_identifiers(rows: list[dict[str, Any]], *, company: str = "", name: str = "") -> dict[str, str]:
    fields: dict[str, str] = {}
    ranked = sorted(rows, key=lambda row: 0 if row.get("seed") else 1)
    for row in ranked:
        kind = str(row.get("kind") or "").upper()
        if kind in fields or kind in {"CPF", "FATHER", "MOTHER", "BIRTHDATE", "PHONE"}:
            continue
        value = str(row.get("value") or "").strip()
        if value:
            fields[kind] = value
    text = (company or "").strip()
    if text and "COMPANY" not in fields and not validate_cnpj(text) and not text.isdigit():
        fields["COMPANY"] = text
    person = (name or "").strip()
    if person and " " in person and "NAME" not in fields:
        fields["NAME"] = person
    return fields


def media_queries_from_fields(fields: dict[str, str], *, extra: str = "") -> list[str]:
    return [combo.label for combo in plan_search_combos(fields, extra=extra)]


def media_queries_from_identifiers(rows: list[dict[str, Any]], *, title: str = "", company: str = "") -> list[str]:
    return media_queries_from_fields(fields_from_identifiers(rows, company=company), extra=title)


def parse_news_rows(rows: list[dict[str, Any]], *, source: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or row.get("link") or row.get("page_url") or "").strip()
        title = str(row.get("title") or "").strip()
        if not url.startswith("http") or not title or url in seen:
            continue
        seen.add(url)
        snippet = str(row.get("content") or row.get("snippet") or row.get("description") or "").strip()
        when = str(row.get("publishedDate") or row.get("age") or row.get("date") or "").strip()
        meta = row.get("meta_url")
        engine = str(meta.get("hostname") or "") if isinstance(meta, dict) else ""
        engine = engine or str(row.get("engine") or "")
        items.append(
            NewsItem(title=title[:220], url=url, snippet=snippet[:400], source=engine or source, when=when[:40], via=source)
        )
        if len(items) >= 16:
            break
    return items


def parse_image_rows(rows: list[dict[str, Any]], *, source: str) -> list[ImageItem]:
    items: list[ImageItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        image = row.get("image") if isinstance(row.get("image"), dict) else {}
        thumb = str(
            row.get("thumbnail_src")
            or row.get("thumbnail")
            or row.get("thumbnailUrl")
            or image.get("thumbnailLink")
            or row.get("img_src")
            or image.get("thumbnailUrl")
            or ""
        ).strip()
        page = str(row.get("url") or row.get("link") or image.get("contextLink") or row.get("img_src") or "").strip()
        if not thumb.startswith("http") or thumb in seen:
            continue
        seen.add(thumb)
        title = str(row.get("title") or row.get("source") or "imagem pública").strip()[:160]
        items.append(
            ImageItem(
                title=title,
                page_url=page if page.startswith("http") else thumb,
                thumb=thumb,
                source=source,
                via=source,
            )
        )
        if len(items) >= 16:
            break
    return items


def _news_query(term: str) -> str:
    return f'"{term}" (notícia OR news OR jornal OR g1 OR "folha de s.paulo" OR "o globo")'


def _fields_from_terms(queries: list[str]) -> dict[str, str]:
    from osint4all.identifiers import parse_seed

    bag: dict[str, str] = {}
    for raw in queries:
        text = (raw or "").strip()
        if not text:
            continue
        seed = parse_seed(text)
        if seed and seed.kind in _QUERY_KINDS:
            bag.setdefault(seed.kind, seed.value)
        elif " " in text:
            bag.setdefault("NAME", text)
    return bag


def collect_target_media(
    queries: list[str] | None = None,
    *,
    fields: dict[str, str] | None = None,
    title: str = "",
    settings: Settings | None = None,
    live: bool | None = None,
) -> MediaBundle:
    settings = settings or get_settings()
    bag = dict(fields or {})
    if not bag:
        bag = _fields_from_terms(queries or [])
    combos = plan_search_combos(bag, extra=title)
    out = MediaBundle(queries=[combo.label for combo in combos])
    if not combos:
        out.ok = False
        out.notes.append("Sem nome, CNPJ, @user, placa, e-mail ou processo para buscar em público. CPF sozinho não vai à busca web.")
        return out
    go_live = _live(settings) if live is None else live
    if not go_live:
        out.notes.append(
            "Combinações prontas, mas notícias e fotos só rodam ao vivo. Em teste a busca pública fica desligada."
        )
        return out
    if not web_search_ready(settings):
        out.ok = False
        out.notes.append("Busca pública indisponível. Configure SearXNG, Brave ou Google CSE.")
        return out
    conn = WebSearchConnector(settings)
    seen_news: set[str] = set()
    seen_img: set[str] = set()
    empty_runs = 0
    for combo in combos:
        rows = _fetch_category(conn, settings, combo.query, combo.category)
        if not rows:
            empty_runs += 1
        if combo.category == "news":
            for item in parse_news_rows(rows, source=combo.label):
                if item.url in seen_news:
                    continue
                seen_news.add(item.url)
                out.news.append(item)
        else:
            for item in parse_image_rows(rows, source=combo.label):
                if item.thumb in seen_img:
                    continue
                seen_img.add(item.thumb)
                out.images.append(item)
        if len(out.news) >= 24 and len(out.images) >= 24:
            break
    out.news = out.news[:24]
    out.images = out.images[:24]
    if not out.news and not out.images:
        if empty_runs == len(combos):
            out.notes.append(
                "Nenhuma instância de busca respondeu agora. Tente de novo daqui a pouco ou configure Brave / Google CSE."
            )
        else:
            out.notes.append(
                "As combinações rodaram, mas não veio menção ou miniatura pública nesta passagem."
            )
    else:
        out.notes.append(
            "Cada combinação especializa a anterior (nome+empresa, nome+@user…). "
            "Só menções e miniaturas públicas — foto e título não provam identidade. "
            "Marque o que quiser e adicione ao caso; nada entra no grafo sozinho."
        )
    return out


def _fetch_category(conn: WebSearchConnector, settings: Settings, query: str, category: str) -> list[dict[str, Any]]:
    if settings.brave_search_api_key:
        rows = _brave_category(conn, query, category)
        if not rows and category == "news":
            rows = _brave_web(conn, query)
        if rows:
            return rows
    if category == "images" and settings.google_cse_api_key and settings.google_cse_cx:
        rows = _google_images(conn, query)
        if rows:
            return rows
    if settings.searxng_enable:
        rows = _searxng_category(conn, settings, query, category)
        if rows:
            return rows
        if category != "general":
            return _searxng_category(conn, settings, query, "general")
    return []


def _searxng_category(conn: WebSearchConnector, settings: Settings, query: str, category: str) -> list[dict[str, Any]]:
    for base in searxng_bases(settings)[:4]:
        try:
            resp = conn.http.request(
                "GET",
                f"{base}/search",
                params={"q": query, "format": "json", "categories": category, "language": "pt-BR"},
                allow_404=True,
                max_retries=1,
            )
        except Exception:
            continue
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code >= 400:
            continue
        if "json" not in ctype and not (resp.content or b"").lstrip().startswith(b"{"):
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        rows = data.get("results") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)]
    return []


def _brave_category(conn: WebSearchConnector, query: str, category: str) -> list[dict[str, Any]]:
    path = "news/search" if category == "news" else "images/search"
    try:
        resp = conn.http.request(
            "GET",
            f"https://api.search.brave.com/res/v1/{path}",
            headers={"X-Subscription-Token": conn.settings.brave_search_api_key, "Accept": "application/json"},
            params={"q": query, "count": 10},
        )
    except Exception:
        return []
    if resp.status_code >= 400:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _brave_web(conn: WebSearchConnector, query: str) -> list[dict[str, Any]]:
    try:
        resp = conn.http.request(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": conn.settings.brave_search_api_key, "Accept": "application/json"},
            params={"q": query, "count": 10},
        )
    except Exception:
        return []
    if resp.status_code >= 400:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    rows = ((data.get("web") or {}).get("results")) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _google_images(conn: WebSearchConnector, query: str) -> list[dict[str, Any]]:
    try:
        resp = conn.http.request(
            "GET",
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": conn.settings.google_cse_api_key,
                "cx": conn.settings.google_cse_cx,
                "q": query,
                "searchType": "image",
                "num": 10,
            },
        )
    except Exception:
        return []
    if resp.status_code >= 400:
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    rows = data.get("items") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _pick_indexes(raw: list[str] | None) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for item in raw or []:
        try:
            idx = int(str(item).strip())
        except ValueError:
            continue
        if idx < 0 or idx in seen:
            continue
        seen.add(idx)
        out.append(idx)
    return out


def _cell(rows: list[str] | None, idx: int) -> str:
    if not rows or idx < 0 or idx >= len(rows):
        return ""
    return str(rows[idx] or "").strip()


def parse_media_picks(
    *,
    news_pick: list[str] | None = None,
    news_url: list[str] | None = None,
    news_title: list[str] | None = None,
    news_snippet: list[str] | None = None,
    news_source: list[str] | None = None,
    news_when: list[str] | None = None,
    news_via: list[str] | None = None,
    image_pick: list[str] | None = None,
    image_url: list[str] | None = None,
    image_title: list[str] | None = None,
    image_thumb: list[str] | None = None,
    image_via: list[str] | None = None,
) -> tuple[list[NewsItem], list[ImageItem]]:
    news: list[NewsItem] = []
    seen_news: set[str] = set()
    for idx in _pick_indexes(news_pick):
        url = _cell(news_url, idx)
        title = _cell(news_title, idx) or url
        if not url.startswith("http") or url in seen_news:
            continue
        seen_news.add(url)
        news.append(
            NewsItem(
                title=title[:220],
                url=url,
                snippet=_cell(news_snippet, idx)[:400],
                source=_cell(news_source, idx),
                when=_cell(news_when, idx)[:40],
                via=_cell(news_via, idx),
            )
        )
    images: list[ImageItem] = []
    seen_img: set[str] = set()
    for idx in _pick_indexes(image_pick):
        page = _cell(image_url, idx)
        thumb = _cell(image_thumb, idx)
        title = _cell(image_title, idx) or page or thumb
        if not page.startswith("http") and not thumb.startswith("http"):
            continue
        key = page or thumb
        if key in seen_img:
            continue
        seen_img.add(key)
        images.append(
            ImageItem(
                title=title[:220],
                page_url=page if page.startswith("http") else "",
                thumb=thumb if thumb.startswith("http") else "",
                via=_cell(image_via, idx),
            )
        )
    return news, images


def media_picks_to_result(origin_key: str, news: list[NewsItem], images: list[ImageItem]) -> ConnectorResult:
    out = ConnectorResult()
    for item in news:
        url = (item.url or "").strip()
        if not url.startswith("http"):
            continue
        ref = canonical_key("URL", url)
        out.entities.append(
            FoundEntity(
                entity_type="PUBLICATION",
                kind="URL",
                value=url,
                display_name=(item.title or url)[:160],
                attrs={
                    "snippet": item.snippet,
                    "fonte": item.source,
                    "quando": item.when,
                    "via": item.via,
                    "tipo": "noticia",
                },
                confidence=0.4,
            )
        )
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.4))
        out.evidence.append(
            FoundEvidence(
                source_label=item.source or item.via or "Notícia pública",
                url=url,
                snippet=item.snippet or item.title,
                payload={"title": item.title, "via": item.via, "quando": item.when, "tipo": "noticia"},
                entity_ref=ref,
            )
        )
    for item in images:
        page = (item.page_url or "").strip()
        thumb = (item.thumb or "").strip()
        url = page if page.startswith("http") else thumb
        if not url.startswith("http"):
            continue
        ref = canonical_key("URL", url)
        out.entities.append(
            FoundEntity(
                entity_type="PUBLICATION",
                kind="URL",
                value=url,
                display_name=(item.title or url)[:160],
                attrs={
                    "thumb": thumb if thumb.startswith("http") else "",
                    "page_url": page if page.startswith("http") else "",
                    "via": item.via,
                    "tipo": "imagem",
                },
                confidence=0.4,
            )
        )
        out.edges.append(FoundEdge(from_ref=origin_key, to_ref=ref, rel_type="MENCAO", confidence=0.4))
        out.evidence.append(
            FoundEvidence(
                source_label=item.via or "Imagem pública",
                url=url,
                snippet=item.title or url,
                payload={"title": item.title, "thumb": thumb, "page_url": page, "via": item.via, "tipo": "imagem"},
                entity_ref=ref,
            )
        )
    return out
