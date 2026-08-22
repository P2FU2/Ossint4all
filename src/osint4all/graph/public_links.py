"""Filtro de URL pública: resultado oficial vs capa de portal ou chrome de site."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

_CHROME_MARKS = (
    "googlelogo",
    "wordmark",
    "favicon",
    "apple-touch-icon",
    "android-chrome",
    "mstile-",
    "safari-pinned",
    "/sprite",
    "/sprites/",
    "/icons/",
    "/icon-",
    "logo_color",
    "logo-mark",
    "branding",
    "gstatic.com/images",
    "google.com/images/branding",
    "google_wordmark",
    "1x1.gif",
    "pixel.gif",
    "tracking.gif",
)
_CHROME_TITLE = ("logo", "favicon", "ícone", "icone", "sprite", "wordmark", "brand")
_BRAND_MARKS = (
    "opensanctions.org",
    "static.opensanctions.org",
    "/logo.",
    "/logo/",
    "/logos/",
    "logo_color",
    "brand-logo",
    "og-logo",
    "default-og",
)
_PORTRAIT_HOSTS = (
    "upload.wikimedia.org",
    "commons.wikimedia.org",
    "divulgacandcontas.tse.jus.br",
    "www.camara.leg.br",
    "camara.leg.br",
    "www.senado.leg.br",
    "senado.leg.br",
    "www.tse.jus.br",
    "tse.jus.br",
)
_TRUSTED_PHOTO_SOURCES = frozenset({"wikidata", "wikipedia", "tse", "oficial", "manual", "camara", "senado"})
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
_PORTAL_EXACT = {
    "gov.br/cvm/pt-br/assuntos/protecao/alertas",
    "divulgacandcontas.tse.jus.br",
    "querido-diario.ok.org.br",
    "in.gov.br/consulta",
    "in.gov.br/leiturajornal",
    "comunica.pje.jus.br",
    "cnj.jus.br/plataforma-digital-do-poder-judiciario-pdpj",
    "datajud-wiki.cnj.jus.br/api-publica/acesso",
    "venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp",
    "sigef.incra.gov.br",
}


def _parts(url: str) -> tuple[str, str, str]:
    raw = (url or "").strip()
    if not raw.startswith("http"):
        return "", "", ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    query = unquote(parsed.query or "").lower()
    return host, path, query


def is_catalog_portal(url: str) -> bool:
    """Capa de portal (lista vazia, busca, wiki da API) — não é o registro final."""
    host, path, query = _parts(url)
    if not host:
        return False
    if host.endswith("google.com") and path.startswith("/search"):
        return True
    if host.endswith("bing.com") and path.startswith("/search"):
        return True
    hp = f"{host}{path}" if path else host
    if hp.startswith("portaldatransparencia.gov.br/sancoes/consulta"):
        return True
    if hp.startswith("portaldatransparencia.gov.br/busca"):
        return True
    if host == "contas.tcu.gov.br" and "p=1660:3" in query.replace(" ", ""):
        return True
    if hp.startswith("sncr.serpro.gov.br/sncr-web/consultaPublica"):
        return True
    return hp in _PORTAL_EXACT


def is_site_chrome(url: str, title: str = "") -> bool:
    """Logo, favicon, sprite — pedaço de site, não foto do alvo."""
    blob = f"{url or ''} {title or ''}".casefold()
    if any(mark in blob for mark in _CHROME_MARKS):
        return True
    name = (title or "").casefold().strip()
    if name in _CHROME_TITLE or any(token in name for token in ("favicon", "wordmark", "apple-touch")):
        return True
    return False


def is_brand_image(url: str, title: str = "") -> bool:
    """Logo de portal (OpenSanctions, favicon, wordmark) — não é foto da pessoa nem print da matéria."""
    if is_site_chrome(url, title):
        return True
    blob = f"{url or ''} {title or ''}".casefold()
    return any(mark in blob for mark in _BRAND_MARKS)


def is_registry_entity_url(url: str) -> bool:
    host, path, _query = _parts(url)
    if "opensanctions.org" in host:
        return True
    if host.endswith("wikidata.org") and (path.startswith("/wiki/") or path.startswith("/entity/")):
        return True
    return False


def is_real_person_photo(url: str, source: str = "") -> bool:
    """Foto colocada (Wikidata, TSE, Câmara…) — não o logo da fonte."""
    raw = (url or "").strip()
    if not raw.startswith(("http://", "https://", "/app/casos/")):
        return False
    if is_brand_image(raw):
        return False
    if raw.startswith("/app/casos/"):
        return True
    if (source or "").casefold() in _TRUSTED_PHOTO_SOURCES:
        return True
    host = urlparse(raw).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    allowed = {item.removeprefix("www.") for item in _PORTRAIT_HOSTS}
    return host in allowed or any(host.endswith("." + item) for item in allowed)


def looks_like_image_file(url: str) -> bool:
    path = urlparse((url or "").strip()).path.lower()
    return any(path.endswith(ext) for ext in _IMAGE_EXT)


def official_result_url(url: str) -> str:
    text = (url or "").strip()
    if text.startswith("http") and not is_catalog_portal(text):
        return text
    return ""
