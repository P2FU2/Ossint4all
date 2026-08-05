"""Links para consulta pública oficial do processo (portal do tribunal)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from monitor_jus.config import get_settings, load_yaml
from monitor_jus.validators import TribunalResolver, normalize_cnj

# Portais de consulta pública conhecidos (templates com placeholders CNJ).
_DEFAULT_PORTAIS: dict[str, str] = {
    "stf": (
        "https://portal.stf.jus.br/processos/listProcesso.asp"
        "?numero={digits}"
    ),
    "stj": (
        "https://processo.stj.jus.br/processo/pesquisa/"
        "?tipoPesquisa=tipoPesquisaNumeroUnico&termo={digits}"
    ),
    "tst": "https://consultaprocessual.tst.jus.br/consultaProcessual/consultaTstNumUnica.do",
    "tse": "https://www.tse.jus.br/servicos-eleitorais/processos/consulta-processual",
    "tjsp": (
        "https://esaj.tjsp.jus.br/cpopg/search.do?conversationId=&cbPesquisa=NUMPROC"
        "&numeroDigitoAnoUnificado={nnnnnnn}-{dd}.{aaaa}"
        "&foroNumeroUnificado={oooo}"
        "&dadosConsulta.valorConsultaNuUnificado={cnj}"
        "&dadosConsulta.tipoNuProcesso=UNIFICADO"
    ),
    "tjrj": "https://www3.tjrj.jus.br/consultaprocessual/#/consultapublica",
    "tjmg": "https://www4.tjmg.jus.br/juridico/sf/proc_resultado.jsp",
    "tjrs": "https://www.tjrs.jus.br/novo/busca/?return=proc&client=wp_index",
    "tjpr": "https://consulta.tjpr.jus.br/projudi_consulta/",
    "tjsc": "https://eproc1g.tjsc.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "tjba": "https://projetos.tjba.jus.br/projudi/",
    "tjce": "https://esaj.tjce.jus.br/cpopg/open.do",
    "tjgo": "https://projudi.tjgo.jus.br/ConsultaPublica",
    "tjdft": "https://pje.tjdft.jus.br/consultapublica/ConsultaPublica/listView.seam",
    "tjes": "https://sistemas.tjes.jus.br/consulta/",
    "tjpe": "https://www.tjpe.jus.br/consultaprocessual/",
    "tjpb": "https://pje.tjpb.jus.br/pje/ConsultaPublica/listView.seam",
    "tjrn": "https://pje1g.tjrn.jus.br/consultapublica/ConsultaPublica/listView.seam",
    "tjma": "https://pje.tjma.jus.br/pje/ConsultaPublica/listView.seam",
    "tjmt": "https://pje.tjmt.jus.br/pje/ConsultaPublica/listView.seam",
    "tjms": "https://esaj.tjms.jus.br/cpopg/open.do",
    "tjpa": "https://pje.tjpa.jus.br/pje/ConsultaPublica/listView.seam",
    "tjpi": "https://www.tjpi.jus.br/themisconsultas/",
    "tjal": "https://www2.tjal.jus.br/cpopg/open.do",
    "tjam": "https://consultasaj.tjam.jus.br/cpopg/open.do",
    "tjac": "https://eproc.tjac.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "tjap": "https://tucujuris.tjap.jus.br/tucujuris/pages/consultar-processo/consultar-processo.html",
    "tjro": "https://www.tjro.jus.br/consultaprocessual/",
    "tjrr": "https://www.tjrr.jus.br/index.php/consultas/processuais",
    "tjse": "https://www.tjse.jus.br/portal/consultas/processuais",
    "tjto": "https://eproc1.tjto.jus.br/eprocV2_prod_1grau/externo_controlador.php?acao=processo_consulta_publica",
    "trf1": (
        "https://processual.trf1.jus.br/consultaProcessual/numeroProcesso.php"
        "?secao=TRF1&proc={cnj_q}"
    ),
    "trf2": "https://eproc.trf2.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "trf3": "https://pje1g.trf3.jus.br/pje/ConsultaPublica/listView.seam",
    "trf4": "https://eproc.trf4.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "trf5": "https://pje.trf5.jus.br/pje/ConsultaPublica/listView.seam",
    "trf6": "https://eproc.trf6.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
}

_FALLBACK_HOME: dict[str, str] = {
    "stf": "https://portal.stf.jus.br/processos/",
    "stj": "https://processo.stj.jus.br/processo/pesquisa/",
    "tst": "https://www.tst.jus.br/",
    "trf1": "https://portal.trf1.jus.br/",
}

# Templates com CNJ preenchido → deep-link ou search prefilled
_DEEP_LINK_COURTS = {"tjsp"}
_SEARCH_PREFILLED_COURTS = {"stf", "stj", "trf1"}


@dataclass(frozen=True)
class OfficialLink:
    url: str
    court: str
    link_type: str
    confidence: str
    requires_manual_search: bool = False


def build_stf_search_url(process_number: str) -> str:
    parts = normalize_cnj(process_number)
    digits = parts.numero_digits if parts else only_digits_safe(process_number)
    return (
        "https://portal.stf.jus.br/processos/listProcesso.asp"
        f"?numero={quote(digits)}"
    )


def build_stf_lawyer_search_url(lawyer_name: str) -> str:
    return (
        "https://portal.stf.jus.br/processos/listProcesso.asp"
        f"?parte={quote((lawyer_name or '').strip())}"
    )


def only_digits_safe(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def _is_useless_portal_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return True
    low = url.lower().strip()
    if not low.startswith("http"):
        return True
    # Homepages / buscas vazias / provedores comerciais
    if "listview.seam" in low and "proc" not in low and "numero" not in low:
        return True
    if any(m in low for m in ("judit.io", "jusbrasil.com.br")):
        return True
    # Homepage pura (path curto sem query de processo)
    for home in _FALLBACK_HOME.values():
        if low.rstrip("/") == home.rstrip("/"):
            return True
    return False


def _payload_url(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("url", "lawsuit_url", "official_url", "link", "public_url"):
        val = payload.get(key)
        if isinstance(val, str) and val.startswith("http") and not _is_useless_portal_url(val):
            return val
    nested = payload.get("lawsuit")
    if isinstance(nested, dict):
        return _payload_url(nested)
    return None


@lru_cache
def _portais_map() -> dict[str, str]:
    settings = get_settings()
    data = load_yaml(settings.config_path("portais_consulta.yaml"))
    merged = dict(_DEFAULT_PORTAIS)
    custom = data.get("portais") if isinstance(data, dict) else None
    if isinstance(custom, dict):
        for k, v in custom.items():
            if isinstance(v, str) and v.strip():
                merged[str(k).lower()] = v.strip()
    return merged


def _format_portal(template: str, parts: Any) -> str:
    digits = parts.numero_digits
    cnj = parts.numero_formatado
    nnnnnnn, dd, aaaa = digits[0:7], digits[7:9], digits[9:13]
    j, tr, oooo = parts.segmento, parts.tribunal, parts.origem
    return template.format(
        cnj=cnj,
        digits=digits,
        nnnnnnn=nnnnnnn,
        dd=dd,
        aaaa=aaaa,
        j=j,
        tr=tr,
        oooo=oooo,
        cnj_q=quote(cnj),
        digits_q=quote(digits),
    )


def _resolve_court_key(numero_cnj: str | None, tribunal: str | None) -> str | None:
    parts = normalize_cnj(numero_cnj or "")
    settings = get_settings()
    resolver = TribunalResolver(settings.config_path("tribunais.yaml"))
    key = None
    if parts:
        resolved = resolver.resolve_from_cnj(parts.numero_formatado) or {}
        key = (resolved.get("key") or "").lower() or None
        if not key and parts.segmento == "1":
            key = "stf"
    if not key and tribunal:
        t = tribunal.strip().lower().replace(" ", "")
        portais = _portais_map()
        if t in portais or t in _FALLBACK_HOME:
            key = t
        else:
            for candidate in set(portais) | set(_FALLBACK_HOME):
                if candidate in t or t in candidate:
                    key = candidate
                    break
    return key


def _classify_link(court_key: str, url: str) -> OfficialLink:
    court = court_key.upper()
    low = url.lower()
    if court_key in _DEEP_LINK_COURTS and "{cnj}" not in low:
        return OfficialLink(
            url=url,
            court=court,
            link_type="PROCESS_DEEP_LINK",
            confidence="high",
        )
    if court_key in _SEARCH_PREFILLED_COURTS:
        return OfficialLink(
            url=url,
            court=court,
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="high",
        )
    if "listview.seam" in low and "proc" not in low and "numero" not in low:
        return OfficialLink(
            url=url,
            court=court,
            link_type="COURT_SEARCH_PAGE",
            confidence="low",
            requires_manual_search=True,
        )
    if "?" in url or "numero" in low or "termo=" in low or "proc=" in low:
        return OfficialLink(
            url=url,
            court=court,
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="medium",
        )
    return OfficialLink(
        url=url,
        court=court,
        link_type="COURT_SEARCH_PAGE",
        confidence="low",
        requires_manual_search=True,
    )


def resolve_official_link_result(
    numero_cnj: str | None,
    *,
    tribunal: str | None = None,
    payload: dict[str, Any] | None = None,
    existing: str | None = None,
    lawyer_name: str | None = None,
) -> OfficialLink:
    """Resolve link oficial tipado com confiança."""
    # STF só com advogado
    court_hint = (tribunal or "").strip().upper()
    if court_hint == "STF" and not normalize_cnj(numero_cnj or "") and lawyer_name:
        return OfficialLink(
            url=build_stf_lawyer_search_url(lawyer_name),
            court="STF",
            link_type="COURT_SEARCH_PAGE",
            confidence="medium",
            requires_manual_search=True,
        )

    if isinstance(existing, str) and existing.startswith("http") and not _is_useless_portal_url(existing):
        key = _resolve_court_key(numero_cnj, tribunal) or "unknown"
        return _classify_link(key, existing)

    from_payload = _payload_url(payload)
    if from_payload:
        key = _resolve_court_key(numero_cnj, tribunal) or "unknown"
        return _classify_link(key, from_payload)

    parts = normalize_cnj(numero_cnj or "")
    key = _resolve_court_key(numero_cnj, tribunal)
    if not key:
        return OfficialLink(
            url="",
            court=(tribunal or "").upper() or "UNKNOWN",
            link_type="UNAVAILABLE",
            confidence="none",
            requires_manual_search=True,
        )

    if key == "stf" and parts:
        url = build_stf_search_url(parts.numero_formatado)
        return OfficialLink(
            url=url,
            court="STF",
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="high",
        )

    template = _portais_map().get(key)
    if not template:
        home = _FALLBACK_HOME.get(key, "")
        return OfficialLink(
            url=home,
            court=key.upper(),
            link_type="COURT_HOMEPAGE" if home else "UNAVAILABLE",
            confidence="low" if home else "none",
            requires_manual_search=True,
        )

    if not parts:
        base = template.split("?")[0]
        return OfficialLink(
            url=base,
            court=key.upper(),
            link_type="COURT_SEARCH_PAGE",
            confidence="low",
            requires_manual_search=True,
        )

    try:
        url = _format_portal(template, parts)
    except (KeyError, ValueError, IndexError):
        home = _FALLBACK_HOME.get(key) or template.split("?")[0]
        return OfficialLink(
            url=home,
            court=key.upper(),
            link_type="COURT_HOMEPAGE",
            confidence="low",
            requires_manual_search=True,
        )

    if _is_useless_portal_url(url):
        return OfficialLink(
            url=url,
            court=key.upper(),
            link_type="COURT_SEARCH_PAGE",
            confidence="low",
            requires_manual_search=True,
        )

    return _classify_link(key, url)


def resolve_official_link(
    numero_cnj: str | None,
    *,
    tribunal: str | None = None,
    payload: dict[str, Any] | None = None,
    existing: str | None = None,
) -> str | None:
    """Compat: retorna apenas a URL (ou None se unavailable/useless)."""
    result = resolve_official_link_result(
        numero_cnj,
        tribunal=tribunal,
        payload=payload,
        existing=existing,
    )
    if result.link_type == "UNAVAILABLE" or not result.url:
        return None
    if result.link_type == "COURT_HOMEPAGE":
        return result.url
    return result.url
