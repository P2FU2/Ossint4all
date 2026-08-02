"""Links para consulta pública oficial do processo (portal do tribunal)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import quote

from monitor_jus.config import get_settings, load_yaml
from monitor_jus.validators import TribunalResolver, normalize_cnj

# Portais de consulta pública conhecidos (templates com placeholders CNJ).
# Placeholders: {cnj} {digits} {nnnnnnn} {dd} {aaaa} {j} {tr} {oooo} {cnj_q} {digits_q}
_DEFAULT_PORTAIS: dict[str, str] = {
    "stf": "https://portal.stf.jus.br/processos/listProcesso.asp",
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
    "trf1": "https://pje1g.trf1.jus.br/consultapublica/ConsultaPublica/listView.seam",
    "trf2": "https://eproc.trf2.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "trf3": "https://pje1g.trf3.jus.br/pje/ConsultaPublica/listView.seam",
    "trf4": "https://eproc.trf4.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "trf5": "https://pje.trf5.jus.br/pje/ConsultaPublica/listView.seam",
    "trf6": "https://eproc.trf6.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
}

# Homes oficiais quando não há deep-link confiável
_FALLBACK_HOME: dict[str, str] = {
    "stf": "https://portal.stf.jus.br/processos/",
    "stj": "https://processo.stj.jus.br/processo/pesquisa/",
    "tst": "https://www.tst.jus.br/",
}


def _payload_url(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("url", "lawsuit_url", "official_url", "link", "public_url"):
        val = payload.get(key)
        if isinstance(val, str) and val.startswith("http"):
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


def resolve_official_link(
    numero_cnj: str | None,
    *,
    tribunal: str | None = None,
    payload: dict[str, Any] | None = None,
    existing: str | None = None,
) -> str | None:
    """Resolve link oficial: URL da fonte > portal do tribunal > None."""
    if isinstance(existing, str) and existing.startswith("http"):
        return existing
    from_payload = _payload_url(payload)
    if from_payload:
        return from_payload

    parts = normalize_cnj(numero_cnj or "")
    if not parts:
        return None

    settings = get_settings()
    resolver = TribunalResolver(settings.config_path("tribunais.yaml"))
    resolved = resolver.resolve_from_cnj(parts.numero_formatado) or {}
    key = (resolved.get("key") or "").lower() or None

    # fallback por acrônimo textual (STJ, TJSP, …)
    if not key and tribunal:
        t = tribunal.strip().lower().replace(" ", "")
        portais = _portais_map()
        if t in portais:
            key = t
        else:
            for candidate in portais:
                if candidate in t or t in candidate:
                    key = candidate
                    break

    if not key:
        return None

    template = _portais_map().get(key)
    if not template:
        return _FALLBACK_HOME.get(key)

    try:
        return _format_portal(template, parts)
    except (KeyError, ValueError, IndexError):
        return _FALLBACK_HOME.get(key) or template.split("?")[0]
