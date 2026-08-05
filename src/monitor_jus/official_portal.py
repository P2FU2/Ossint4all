"""Links para consulta pública oficial do processo (portal do tribunal)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from monitor_jus.config import get_settings, load_yaml
from monitor_jus.validators import TribunalResolver, normalize_cnj

# Classes típicas de 2º grau / tribunais superiores estaduais (e-SAJ cposg)
_SECOND_DEGREE_HINTS = (
    "agravo de instrumento",
    "agravo interno",
    "apelação",
    "apelacao",
    "embargos de declaração",
    "embargos de declaracao",
    "embargos infringentes",
    "recurso inominado",
    "mandado de segurança criminal",
    "conflito de competência",
    "conflito de competencia",
    "ação rescisória",
    "acao rescitoria",
    "revisão criminal",
    "revisao criminal",
)

# Família e-SAJ (cpopg/cposg search.do) — placeholders padrão
_ESAJ_1G = (
    "{esaj_host}/cpopg/search.do?conversationId=&cbPesquisa=NUMPROC"
    "&numeroDigitoAnoUnificado={nnnnnnn}-{dd}.{aaaa}"
    "&foroNumeroUnificado={oooo}"
    "&dadosConsulta.valorConsultaNuUnificado={cnj}"
    "&dadosConsulta.tipoNuProcesso=UNIFICADO"
)
_ESAJ_2G = (
    "{esaj_host}/cposg/search.do?conversationId=&paginaConsulta=0"
    "&cbPesquisa=NUMPROC"
    "&numeroDigitoAnoUnificado={nnnnnnn}-{dd}.{aaaa}"
    "&foroNumeroUnificado={oooo}"
    "&dePesquisa={cnj}"
    "&localPesquisa.cdLocal=-1"
    "&tipoNuProcesso=UNIFICADO"
)
# Família eproc — txtNumProcesso pré-preenche a busca pública
_EPROC = (
    "{eproc_host}/externo_controlador.php"
    "?acao=processo_consulta_publica&txtNumProcesso={digits}"
)

# Portais de consulta pública (templates com placeholders CNJ).
_DEFAULT_PORTAIS: dict[str, str] = {
    "stf": (
        "https://portal.stf.jus.br/processos/listProcesso.asp"
        "?numero={digits}"
    ),
    "stj": (
        "https://processo.stj.jus.br/processo/pesquisa/"
        "?tipoPesquisa=tipoPesquisaNumeroUnico&termo={digits}"
    ),
    "tst": (
        "https://consultaprocessual.tst.jus.br/consultaProcessual/consultaTstNumUnica.do"
        "?consulta=1&numeroTst={nnnnnnn}&digitoVerificador={dd}"
        "&anoAjuizamento={aaaa}&orgaoJudiciario=5&tribunal={tr}&varaOrigem={oooo}"
    ),
    "tse": (
        "https://pje.tse.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjsp": _ESAJ_1G.replace("{esaj_host}", "https://esaj.tjsp.jus.br"),
    "tjsp_2g": _ESAJ_2G.replace("{esaj_host}", "https://esaj.tjsp.jus.br"),
    "tjrj": (
        "https://www3.tjrj.jus.br/consultaprocessual/#/consultapublicap"
        "?codigoProcesso={digits}&tipoProcesso=13"
    ),
    "tjmg": (
        "https://www4.tjmg.jus.br/juridico/sf/proc_resultado2.jsp"
        "?tipoPesquisa2=1&txtProcesso={digits}&comrCodigo={oooo}"
        "&tipoPessoa=X&naturezaProcesso=0&situacaoParte=X&numero=20&select=1"
        "&tipoConsulta=1&natureza=0&ativoBaixado=X&listaProcessos={digits}"
    ),
    "tjrs": "https://www.tjrs.jus.br/novo/busca/?return=proc&client=wp_index&q={cnj_q}",
    "tjpr": (
        "https://consulta.tjpr.jus.br/projudi_consulta/"
        "processo/consultaPublica.do?actionType=pesquisar"
        "&numeroProcesso={cnj_q}"
    ),
    "tjsc": _EPROC.replace(
        "{eproc_host}", "https://eprocwebcon.tjsc.jus.br/consulta1g"
    ),
    "tjsc_2g": _EPROC.replace(
        "{eproc_host}", "https://eprocwebcon.tjsc.jus.br/consulta2g"
    ),
    "tjba": (
        "https://projudi.tjba.jus.br/projudi/listagens/DadosProcesso"
        "?numeroProcesso={digits}"
    ),
    "tjce": _ESAJ_1G.replace("{esaj_host}", "https://esaj.tjce.jus.br"),
    "tjgo": (
        "https://projudi.tjgo.jus.br/BuscaProcesso"
        "?PaginaAtual=-1&PassoBusca=2&tipoConsulta=1&ProcessoNumero={cnj_q}"
    ),
    # PJe: sem deep-link confiável — página de busca + CNJ na query (manual)
    "tjdft": (
        "https://pje.tjdft.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjes": (
        "https://sistemas.tjes.jus.br/consultas_processuais/"
        "?numero={digits}"
    ),
    "tjpe": (
        "https://pje.cloud.tjpe.jus.br/1g/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjpb": (
        "https://pje.tjpb.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjrn": (
        "https://pje1g.tjrn.jus.br/consultapublica/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjma": (
        "https://pje.tjma.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjmt": (
        "https://pje.tjmt.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjms": _ESAJ_1G.replace("{esaj_host}", "https://esaj.tjms.jus.br"),
    "tjms_2g": _ESAJ_2G.replace("{esaj_host}", "https://esaj.tjms.jus.br"),
    "tjpa": (
        "https://pje.tjpa.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjpi": (
        "https://www.tjpi.jus.br/themisweb/modules/processo/ConsultaPublica.mtw"
        "?numeroProcesso={cnj_q}"
    ),
    "tjal": _ESAJ_1G.replace("{esaj_host}", "https://www2.tjal.jus.br"),
    "tjam": _ESAJ_1G.replace("{esaj_host}", "https://consultasaj.tjam.jus.br"),
    # TJAC: eproc 1G (há também e-SAJ legado em esaj.tjac.jus.br)
    "tjac": _EPROC.replace("{eproc_host}", "https://eproc1g.tjac.jus.br/eproc"),
    "tjac_2g": _EPROC.replace("{eproc_host}", "https://eproc2g.tjac.jus.br/eproc"),
    "tjap": (
        "https://tucujuris.tjap.jus.br/tucujuris/pages/consultar-processo/"
        "consultar-processo.html?numeroProcesso={cnj_q}"
    ),
    "tjro": (
        "https://pjepg.tjro.jus.br/consulta/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "tjrr": (
        "https://consultaprojudi.tjrr.jus.br/"
        "?numeroProcesso={cnj_q}"
    ),
    "tjse": _EPROC.replace("{eproc_host}", "https://eproc1g.tjse.jus.br/eproc"),
    "tjse_2g": _EPROC.replace("{eproc_host}", "https://eproc2g.tjse.jus.br/eproc"),
    # TJTO usa ação processo_seleciona_publica (consulta_publica clássica 404)
    "tjto": (
        "https://eproc1.tjto.jus.br/eprocV2_prod_1grau/externo_controlador.php"
        "?acao=processo_seleciona_publica&num_processo={digits}"
    ),
    "trf1": (
        "https://processual.trf1.jus.br/consultaProcessual/numeroProcesso.php"
        "?secao=TRF1&proc={cnj_q}"
    ),
    "trf2": _EPROC.replace("{eproc_host}", "https://eproc.trf2.jus.br/eproc"),
    "trf3": (
        "https://web.trf3.jus.br/consultas/Internet/ConsultaProcessual"
        "?numeroProcesso={digits}"
    ),
    "trf3_1g": (
        "https://pje1g.trf3.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "trf3_2g": (
        "https://pje2g.trf3.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "trf4": _EPROC.replace(
        "{eproc_host}", "https://eproc.trf4.jus.br/eproc2trf4"
    ),
    "trf5": (
        "https://pje.trf5.jus.br/pje/ConsultaPublica/listView.seam"
        "?numeroProcesso={cnj_q}"
    ),
    "trf6": _EPROC.replace("{eproc_host}", "https://eproc1g.trf6.jus.br/eproc"),
}

_FALLBACK_HOME: dict[str, str] = {
    "stf": "https://portal.stf.jus.br/processos/",
    "stj": "https://processo.stj.jus.br/processo/pesquisa/",
    "tst": "https://www.tst.jus.br/",
    "trf1": "https://portal.trf1.jus.br/",
    "tjsp": "https://esaj.tjsp.jus.br/cpopg/open.do",
    "tjms": "https://esaj.tjms.jus.br/cpopg/open.do",
    "trf3": "https://web.trf3.jus.br/consultas/Internet/ConsultaProcessual",
}

_SEARCH_PREFILLED_COURTS = {
    "stf",
    "stj",
    "tst",
    "tse",
    "trf1",
    "trf2",
    "trf3",
    "trf4",
    "trf6",
    "tjsp",
    "tjsp_2g",
    "tjmg",
    "tjrj",
    "tjms",
    "tjms_2g",
    "tjce",
    "tjal",
    "tjam",
    "tjsc",
    "tjsc_2g",
    "tjac",
    "tjac_2g",
    "tjse",
    "tjse_2g",
    "tjto",
    "tjgo",
    "tjrs",
    "tjpr",
    "tjba",
    "tjpi",
}

# Marcadores de URL com CNJ embutido (pré-preenchimento / busca)
_PREFILL_MARKERS = (
    "search.do",
    "termo=",
    "proc=",
    "codigoprocesso=",
    "tipoprocesso=",
    "txtnumprocesso=",
    "num_processo=",
    "processonumero=",
    "numerotst=",
    "listaprocesso=",
    "txtprocesso=",
    "numeroprocesso=",
    "numero=",
    "q=",
)


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


def build_tjrj_portal_url(process_number: str) -> str:
    """Deep-link TJRJ que dispara auto-busca na SPA.

    A tela #/consultapublicap só carrega dados se:
    - codigoProcesso = 20 dígitos e tipoProcesso = 13 ou 14 (numeração única), ou
    - codigoProcesso no formato interno TJRJ (NNNNNNN-DD-AAAA.J.TR.OOOO) + tipo 1/2.

    Só o CNJ com pontos (…03.2026.8.19…) abre a página em branco (“Não há”).
    """
    parts = normalize_cnj(process_number)
    if not parts:
        return "https://www3.tjrj.jus.br/consultaprocessual/#/consultapublica"
    digits = parts.numero_digits
    # 13 = numeração única (caminho que a SPA formata e consulta por-numeracao-unica)
    return (
        "https://www3.tjrj.jus.br/consultaprocessual/#/consultapublicap"
        f"?codigoProcesso={digits}&tipoProcesso=13"
    )


def only_digits_safe(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())


def _is_useless_portal_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return True
    low = url.lower().strip().rstrip("/")
    if not low.startswith("http"):
        return True
    if "listview.seam" in low and "proc" not in low and "numero" not in low:
        return True
    if any(m in low for m in ("judit.io", "jusbrasil.com.br")):
        return True
    # DJEN frequentemente devolve só a home do DJE — inútil como portal do processo
    if low in {
        "https://www.dje.tjsp.jus.br",
        "http://www.dje.tjsp.jus.br",
        "https://dje.tjsp.jus.br",
    }:
        return True
    if "dje.tjsp.jus.br" in low and "processo" not in low and "?" not in low:
        return True
    # TJRJ: precisa codigoProcesso + tipoProcesso; senão a SPA abre “Não há”
    if "tjrj.jus.br/consultaprocessual" in low:
        if "codigoprocesso=" not in low:
            return True
        if "tipoprocesso=" not in low:
            return True
        # CNJ com ponto (padrão CNJ) sem dígitos/tipo 13 costuma falhar o auto-load
        if "tipoprocesso=13" not in low and "tipoprocesso=14" not in low:
            # aceita 1/2 se vier com formato interno TJRJ (hífen no ano)
            if re.search(r"codigoprocesso=\d{7}-\d{2}-\d{4}\.", low):
                pass
            elif "codigoprocesso=" in low:
                # ex.: só ?codigoProcesso=0000000-00.0000.8.19.0000
                return True
    # e-SAJ open.do / homepage sem search.do — não leva ao processo
    if re.search(r"esaj\.[^/]+/cpopg/open\.do/?$", low) or re.search(
        r"esaj\.[^/]+/cposg/open\.do/?$", low
    ):
        return True
    if "/cpopg/open.do" in low and "search.do" not in low and "show.do" not in low:
        return True
    # eproc sem número — formulário vazio
    if "externo_controlador.php" in low and (
        "processo_consulta_publica" in low or "processo_seleciona_publica" in low
    ):
        if "txtnumprocesso=" not in low and "num_processo=" not in low:
            return True
    # PDF da comunicação no STJ — não é consulta do processo
    if "justica.web.stj.jus.br/api/pcp/documentos" in low:
        return True
    for home in _FALLBACK_HOME.values():
        if low == home.rstrip("/").lower():
            return True
    return False


def _is_esaj_show_deep_link(url: str) -> bool:
    low = url.lower()
    return "esaj." in low and "show.do" in low and "processo.codigo=" in low


def _payload_url(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[Any] = []
    for key in ("url", "lawsuit_url", "official_url", "link", "public_url", "source_link"):
        candidates.append(payload.get(key))
    # payload aninhado do nosso ingest
    for nest_key in ("djen", "lawsuit", "raw"):
        nested = payload.get(nest_key)
        if isinstance(nested, dict):
            for key in ("link", "url", "official_url"):
                candidates.append(nested.get(key))
    for val in candidates:
        if isinstance(val, str) and val.startswith("http") and not _is_useless_portal_url(val):
            return val
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
        cnj_q=quote(cnj, safe=".-"),
        digits_q=quote(digits),
    )


def _is_second_degree(
    *,
    parts: Any | None,
    classe: str | None,
    grau: str | None,
    situacao: str | None = None,
    has_second_degree: bool = False,
) -> bool:
    if has_second_degree:
        return True
    grau_l = (grau or "").lower()
    if grau_l in {"g2", "2", "2g"} or any(
        x in grau_l for x in ("segundo", "2º", "2o", "turma", "câmara", "camara")
    ):
        return True
    if "2" in grau_l and "g1" not in grau_l:
        return True
    classe_l = (classe or "").lower()
    if any(h in classe_l for h in _SECOND_DEGREE_HINTS):
        return True
    situ_l = (situacao or "").lower()
    if "grau de recurso" in situ_l or situ_l == "julgado":
        return True
    # CNJ com origem 0000 no TJ estadual costuma ser 2º grau / tribunal
    if parts and parts.origem == "0000" and parts.segmento == "8":
        return True
    return False


def _resolve_court_key(numero_cnj: str | None, tribunal: str | None) -> str | None:
    """Resolve chave do portal.

    Preferência: CNJ (fonte da verdade) → sigla explícita do tribunal.
    Evita match por substring frouxo (ex.: tjpr ⊃ tj).
    """
    parts = normalize_cnj(numero_cnj or "")
    settings = get_settings()
    resolver = TribunalResolver(settings.config_path("tribunais.yaml"))
    key = None
    if parts:
        resolved = resolver.resolve_from_cnj(parts.numero_formatado) or {}
        key = (resolved.get("key") or "").lower() or None
        if not key and parts.segmento == "1":
            key = "stf"
    if tribunal:
        t = tribunal.strip().lower().replace(" ", "")
        if t.endswith("_2g"):
            return t
        portais = _portais_map()
        if t in portais or t in _FALLBACK_HOME:
            # Se CNJ e tribunal divergem, prioriza CNJ (já em key); senão usa tribunal
            if not key:
                key = t
        elif not key:
            # match exato por sufixo conhecido apenas
            for candidate in sorted(set(portais) | set(_FALLBACK_HOME), key=len, reverse=True):
                if t == candidate or t.replace("tj", "") == candidate.replace("tj", ""):
                    key = candidate
                    break
    return key


def _classify_link(court_key: str, url: str) -> OfficialLink:
    court = court_key.upper().replace("_2G", "")
    low = url.lower()
    if _is_esaj_show_deep_link(url):
        return OfficialLink(
            url=url,
            court=court if court != "UNKNOWN" else "TJSP",
            link_type="PROCESS_DEEP_LINK",
            confidence="high",
        )
    # PJe listView quase nunca pré-carrega — sempre busca manual
    if "listview.seam" in low:
        return OfficialLink(
            url=url,
            court=court,
            link_type="COURT_SEARCH_PAGE",
            confidence="low",
            requires_manual_search=True,
        )
    has_prefill = any(m in low for m in _PREFILL_MARKERS)
    if court_key in _SEARCH_PREFILLED_COURTS or has_prefill:
        strong = any(
            m in low
            for m in (
                "search.do",
                "termo=",
                "codigoprocesso=",
                "txtnumprocesso=",
                "num_processo=",
                "numerotst=",
                "txtprocesso=",
                "processonumero=",
                "numeroprocesso=",  # numeroProcesso=
                "listaprocesso=",
            )
        )
        return OfficialLink(
            url=url,
            court=court,
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="high" if strong else "medium",
            requires_manual_search=not strong,
        )
    if "?" in url or "#" in url:
        return OfficialLink(
            url=url,
            court=court,
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="medium",
            requires_manual_search=True,
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
    classe: str | None = None,
    grau: str | None = None,
    situacao: str | None = None,
) -> OfficialLink:
    """Resolve link oficial tipado com confiança."""
    court_hint = (tribunal or "").strip().upper()
    if court_hint == "STF" and not normalize_cnj(numero_cnj or "") and lawyer_name:
        return OfficialLink(
            url=build_stf_lawyer_search_url(lawyer_name),
            court="STF",
            link_type="COURT_SEARCH_PAGE",
            confidence="medium",
            requires_manual_search=True,
        )

    # Deep-link e-SAJ já conhecido tem prioridade máxima
    if isinstance(existing, str) and _is_esaj_show_deep_link(existing):
        return _classify_link("tjsp", existing)

    from_payload = _payload_url(payload)
    if from_payload and _is_esaj_show_deep_link(from_payload):
        return _classify_link("tjsp", from_payload)

    if isinstance(existing, str) and existing.startswith("http") and not _is_useless_portal_url(existing):
        # Search.do genérico sem CNJ → descartar e recalcular
        if "search.do" in existing.lower() and not (numero_cnj and only_digits_safe(numero_cnj)[:7] in existing):
            pass
        else:
            key = _resolve_court_key(numero_cnj, tribunal) or "unknown"
            return _classify_link(key, existing)

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

    # Inferir classe/grau do payload DJEN
    if not classe and isinstance(payload, dict):
        djen = payload.get("djen") if isinstance(payload.get("djen"), dict) else {}
        raw_classe = payload.get("nomeClasse") or payload.get("classe") or djen.get("nomeClasse")
        if isinstance(raw_classe, dict):
            classe = raw_classe.get("nome")
        elif isinstance(raw_classe, str):
            classe = raw_classe
    if not grau and isinstance(payload, dict):
        djen = payload.get("djen") if isinstance(payload.get("djen"), dict) else {}
        grau = payload.get("grau") or djen.get("grau")

    has_g2 = False
    if isinstance(payload, dict):
        has_g2 = bool(payload.get("has_second_degree"))
        if not situacao:
            situacao = payload.get("situacao") or (
                (payload.get("datajud") or {}).get("situacao")
                if isinstance(payload.get("datajud"), dict)
                else None
            )
    if key in {"tjsp", "tjms", "tjac", "tjse", "tjsc"} and _is_second_degree(
        parts=parts,
        classe=str(classe) if classe else None,
        grau=str(grau) if grau else None,
        situacao=str(situacao) if situacao else None,
        has_second_degree=has_g2,
    ):
        key = f"{key}_2g"

    if key == "stf" and parts:
        url = build_stf_search_url(parts.numero_formatado)
        return OfficialLink(
            url=url,
            court="STF",
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="high",
        )

    if key == "tjrj" and parts:
        url = build_tjrj_portal_url(parts.numero_formatado)
        return OfficialLink(
            url=url,
            court="TJRJ",
            link_type="PROCESS_SEARCH_PREFILLED",
            confidence="high",
        )

    template = _portais_map().get(key)
    if not template:
        home = _FALLBACK_HOME.get(key.replace("_2g", ""), "")
        return OfficialLink(
            url=home,
            court=key.upper().replace("_2G", ""),
            link_type="COURT_HOMEPAGE" if home else "UNAVAILABLE",
            confidence="low" if home else "none",
            requires_manual_search=True,
        )

    if not parts:
        base = template.split("?")[0]
        return OfficialLink(
            url=base,
            court=key.upper().replace("_2G", ""),
            link_type="COURT_SEARCH_PAGE",
            confidence="low",
            requires_manual_search=True,
        )

    try:
        url = _format_portal(template, parts)
    except (KeyError, ValueError, IndexError):
        home = _FALLBACK_HOME.get(key.replace("_2g", "")) or template.split("?")[0]
        return OfficialLink(
            url=home,
            court=key.upper().replace("_2G", ""),
            link_type="COURT_HOMEPAGE",
            confidence="low",
            requires_manual_search=True,
        )

    if _is_useless_portal_url(url):
        return OfficialLink(
            url=url,
            court=key.upper().replace("_2G", ""),
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
    classe: str | None = None,
    grau: str | None = None,
    situacao: str | None = None,
) -> str | None:
    """Compat: retorna apenas a URL (ou None se unavailable)."""
    result = resolve_official_link_result(
        numero_cnj,
        tribunal=tribunal,
        payload=payload,
        existing=existing,
        classe=classe,
        grau=grau,
        situacao=situacao,
    )
    if result.link_type == "UNAVAILABLE" or not result.url:
        return None
    return result.url
