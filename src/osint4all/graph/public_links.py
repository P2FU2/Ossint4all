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


def looks_like_image_file(url: str) -> bool:
    path = urlparse((url or "").strip()).path.lower()
    return any(path.endswith(ext) for ext in _IMAGE_EXT)


def official_result_url(url: str) -> str:
    text = (url or "").strip()
    if text.startswith("http") and not is_catalog_portal(text):
        return text
    return ""
