"""Ferramentas embutidas — rodam no painel, sem abrir GitHub ou sites terceiros."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from osint4all.config import Settings, get_settings
from osint4all.connectors.crtsh import CrtshConnector, _DOMAIN_RE
from osint4all.connectors.web_search import WebSearchConnector, web_search_ready
from osint4all.connectors.base import ConnectorResult, FoundEdge, FoundEntity, FoundEvidence
from osint4all.consult import ConsultHit, ConsultResult, run_consult
from osint4all.identifiers import parse_seed, seeds_from_kind_values
from osint4all.security import only_digits


@dataclass(frozen=True)
class EmbeddedTool:
    id: str
    name: str
    summary: str
    kind: str
    placeholder: str
    inspired: str
    upload: bool = False


EMBEDDED_TOOLS: tuple[EmbeddedTool, ...] = (
    EmbeddedTool(
        "massa",
        "Busca em massa",
        "A partir de um único dado, deriva username, domínio, sócio, placa e menções e cruza o que for público.",
        "auto",
        "ABC1D23, @user, nome, e-mail…",
        "SpiderFoot / Mr.Holmes",
    ),
    EmbeddedTool(
        "username",
        "Redes sociais",
        "Checa URLs públicas canônicas (HTTP 200). Equivalente embutido de Sherlock / Maigret / WhatsMyName.",
        "USERNAME",
        "@usuario",
        "Sherlock, Maigret, WhatsMyName, user-scanner",
    ),
    EmbeddedTool("plate", "Placa", "Série, portais e menções públicas do veículo/dono. Sem cadastro DETRAN.", "PLATE", "ABC1D23", "SENATRAN / DENATRAN"),
    EmbeddedTool("phone", "Telefone", "DDD, cidade âncora e menções públicas. Sem operadora.", "PHONE", "11 99999-0000", "PhoneInfoga"),
    EmbeddedTool("name", "Sócio / nome", "Empresas do QSA aberto e menções no Aleph/OCCRP.", "NAME", "Nome e sobrenome", "Receita / Casa dos Dados / Aleph"),
    EmbeddedTool("cnpj", "CNPJ", "Ficha, QSA e mapa de empresas relacionadas.", "CNPJ", "00.000.000/0001-00", "Minha Receita / BrasilAPI"),
    EmbeddedTool("cpf", "CPF", "Valida e cruza QSA público, sanções e menções. Sem nome pela Receita.", "CPF", "000.000.000-00", "Receita / Transparência"),
    EmbeddedTool("email", "E-mail", "Linha do tempo: @user, Keybase, Gravatar e redes. Sem caixa nem leak.", "EMAIL", "nome@dominio.com", "Holehe, Maigret, user-scanner"),
    EmbeddedTool("cnj", "Processos", "Nome, CPF, CNPJ ou CNJ. DataJud, DJEN, PJe e menções públicas.", "PROCESSOS", "nome, CPF ou 0000001-23.2024.8.26.0100", "DataJud / DJEN"),
    EmbeddedTool("negativa", "Negativa", "CEIS, CNEP, TCU, CVM, TSE e menções de condenação em fonte oficial.", "NEGATIVA", "Nome, CPF ou CNPJ", "Transparência / TCU"),
    EmbeddedTool("imovel", "Imóvel", "Leilão Caixa, SNCR, SIGEF e DOU. Sem matrícula de cartório.", "IMOVEL", "Nome, CPF, CNPJ ou endereço", "Caixa / Incra"),
    EmbeddedTool("diario", "Diário oficial", "DOU, Imprensa Nacional, DJEN e diários estaduais públicos.", "DIARIO", "Nome, CPF, CNPJ ou termo", "in.gov.br / Querido Diário"),
    EmbeddedTool(
        "crtsh",
        "Certificados",
        "Nomes em Certificate Transparency (crt.sh). Módulo típico do SpiderFoot.",
        "URL",
        "exemplo.com",
        "crt.sh / SpiderFoot",
    ),
    EmbeddedTool(
        "hosts",
        "Hosts e subdomínios",
        "Índices públicos (Wayback, HackerTarget, urlscan). Estilo theHarvester / Amass / Subfinder, sem varrer porta.",
        "URL",
        "exemplo.com",
        "theHarvester, Amass, Subfinder",
    ),
    EmbeddedTool(
        "hostficha",
        "Ficha de host",
        "Status, título, tecnologia e páginas do domínio já conhecido. Indexa no histórico do caso. Sem varrer porta.",
        "URL",
        "exemplo.com",
        "httpx, Photon, Nuclei informativo, IVRE",
    ),
    EmbeddedTool(
        "web",
        "Menções web",
        "SearXNG público (sem chave), Brave ou Google CSE.",
        "NAME",
        "termo público",
        "SearXNG / Brave / CSE",
    ),
    EmbeddedTool(
        "pdf",
        "Metadados de arquivo",
        "Lê autor, software e datas do PDF/JPEG/PNG que você envia. ExifTool / FOCA, sem varrer a web.",
        "FILE",
        "",
        "ExifTool, FOCA",
        upload=True,
    ),
)


@dataclass
class MassResult:
    query: str
    kind: str
    title: str
    summary: str
    parts: list[ConsultResult] = field(default_factory=list)
    derived: list[tuple[str, str]] = field(default_factory=list)
    ok: bool = True
    error: str | None = None

    @property
    def kind_label(self) -> str:
        return "Busca em massa"


TOOL_GRAPH_KINDS: dict[str, tuple[str, ...]] = {
    "massa": ("NAME", "CPF", "CNPJ", "EMAIL", "PHONE", "USERNAME", "PLATE", "CNJ"),
    "username": ("USERNAME",),
    "plate": ("PLATE",),
    "phone": ("PHONE",),
    "name": ("NAME",),
    "cnpj": ("CNPJ",),
    "cpf": ("CPF",),
    "email": ("EMAIL",),
    "cnj": ("CNJ", "NAME", "CPF", "CNPJ"),
    "negativa": ("NAME", "CPF", "CNPJ"),
    "imovel": ("NAME", "CPF", "CNPJ"),
    "diario": ("NAME", "CPF", "CNPJ"),
    "crtsh": ("URL",),
    "hosts": ("URL",),
    "hostficha": ("URL",),
    "web": ("NAME",),
}

_STRONG_HIT_KINDS = frozenset({"CPF", "CNPJ", "EMAIL", "PHONE", "USERNAME", "PLATE", "CNJ", "URL"})
_AUTO_CHECK_TOOLS = frozenset({"username", "plate", "phone", "cnpj", "cpf", "email", "cnj", "crtsh", "hosts", "hostficha"})
_MAX_TOOL_VALUES = 4
_MAX_OUTCOME_ENTITIES = 40


def tool_id_for_kind(kind: str) -> str:
    return {
        "USERNAME": "username",
        "PLATE": "plate",
        "PHONE": "phone",
        "NAME": "name",
        "CNPJ": "cnpj",
        "CPF": "cpf",
        "EMAIL": "email",
        "CNJ": "cnj",
        "PROCESSOS": "cnj",
        "NEGATIVA": "negativa",
        "IMOVEL": "imovel",
        "DIARIO": "diario",
        "URL": "crtsh",
        "MASSA": "massa",
        "massa": "massa",
    }.get((kind or "").upper() if (kind or "") != "massa" else "massa", "massa")


def graph_tools_plan(dossier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ferramentas embutidas cruzadas com o que já está no grafo."""
    by_kind: dict[str, list[str]] = {}
    for item in dossier or []:
        kind = str(item.get("kind") or "").upper()
        value = str(item.get("value") or "").strip()
        if kind and value:
            by_kind.setdefault(kind, []).append(value)
    plan: list[dict[str, Any]] = []
    for tool in EMBEDDED_TOOLS:
        kinds = TOOL_GRAPH_KINDS.get(tool.id)
        if not kinds:
            continue
        values: list[str] = []
        seen: set[str] = set()
        for kind in kinds:
            for value in by_kind.get(kind, []):
                key = f"{kind}:{value.casefold()}"
                if key in seen:
                    continue
                seen.add(key)
                values.append(value)
                if len(values) >= _MAX_TOOL_VALUES:
                    break
            if len(values) >= _MAX_TOOL_VALUES:
                break
        auto = bool(values) and tool.id in _AUTO_CHECK_TOOLS
        if tool.id == "cnj":
            auto = bool(by_kind.get("CNJ"))
        plan.append(
            {
                "id": tool.id,
                "name": tool.name,
                "summary": tool.summary,
                "values": values,
                "ready": bool(values),
                "checked": auto,
                "hint": ", ".join(values[:2]) if values else "sem este dado no grafo",
            }
        )
    return plan


def outcome_parts(outcome: ConsultResult | MassResult) -> list[ConsultResult]:
    if isinstance(outcome, MassResult):
        return [part for part in outcome.parts if part]
    return [outcome]


def outcome_to_connector(outcome: ConsultResult | MassResult, origin_key: str) -> ConnectorResult:
    """Converte o resultado da ferramenta em nós/vínculos novos, sem apagar o grafo."""
    result = ConnectorResult()
    seen: set[str] = set()
    for part in outcome_parts(outcome):
        if not part or not part.ok:
            if part and part.error:
                result.notes.append(part.error)
            continue
        _ingest_consult_part(result, part, origin_key, seen)
        if len(result.entities) >= _MAX_OUTCOME_ENTITIES:
            break
    return result


def _ingest_consult_part(result: ConnectorResult, part: ConsultResult, origin_key: str, seen: set[str]) -> None:
    query_seed = parse_seed(part.query, forced_kind=part.kind if part.kind not in {"", "auto", "massa", "FILE", "PROCESSOS"} else None)
    if part.kind == "PROCESSOS":
        query_seed = parse_seed(part.query, forced_kind="CNJ") or query_seed
    if query_seed:
        _add_found(result, query_seed, seen, attrs={"tool_query": True})
    graph = getattr(part, "graph", None)
    if graph and getattr(graph, "nodes", None):
        id_to_key: dict[str, str] = {}
        for node in graph.nodes:
            seed = _seed_from_graph_node(node)
            if not seed:
                continue
            _add_found(result, seed, seen, attrs={"from_tool_graph": True, "papel": getattr(node, "meta", "") or ""})
            id_to_key[node.id] = seed.canonical_key
        for edge in getattr(graph, "edges", []) or []:
            src = id_to_key.get(edge.source)
            dst = id_to_key.get(edge.target)
            if src and dst and src != dst:
                result.edges.append(FoundEdge(src, dst, _rel_from_label(getattr(edge, "label", "")), 0.7, {"fonte": "ferramenta"}))
    for hit in part.hits or []:
        if len(result.entities) >= _MAX_OUTCOME_ENTITIES:
            break
        url = str(getattr(hit, "url", "") or "").strip()
        title = str(getattr(hit, "title", "") or "").strip()
        if url:
            url_seed = parse_seed(url, forced_kind="URL")
            if url_seed:
                _add_found(result, url_seed, seen, display=title or url_seed.display_name, attrs={"snippet": getattr(hit, "meta", "") or ""})
                if origin_key and origin_key != url_seed.canonical_key:
                    result.edges.append(FoundEdge(origin_key, url_seed.canonical_key, "MENCAO", 0.55, {"fonte": "ferramenta"}))
                result.evidence.append(
                    FoundEvidence(
                        source_label=title or "menção pública",
                        url=url,
                        snippet=str(getattr(hit, "meta", "") or "")[:400] or None,
                        entity_ref=url_seed.canonical_key,
                    )
                )
                continue
        hit_seed = parse_seed(title)
        if hit_seed and hit_seed.kind in _STRONG_HIT_KINDS:
            _add_found(result, hit_seed, seen)
            if origin_key and origin_key != hit_seed.canonical_key:
                result.edges.append(FoundEdge(origin_key, hit_seed.canonical_key, "RELACIONADO", 0.5, {"fonte": "ferramenta"}))
    for note in part.notes or []:
        result.notes.append(str(note))


def _add_found(
    result: ConnectorResult,
    seed,
    seen: set[str],
    *,
    display: str = "",
    attrs: dict[str, Any] | None = None,
) -> None:
    if seed.canonical_key in seen:
        return
    seen.add(seed.canonical_key)
    result.entities.append(
        FoundEntity(
            entity_type=seed.entity_type,
            kind=seed.kind,
            value=seed.value,
            display_name=display or seed.display_name,
            attrs=dict(attrs or {}),
            confidence=0.72 if seed.kind in _STRONG_HIT_KINDS else 0.5,
        )
    )


def _seed_from_graph_node(node) -> Any:
    nid = str(getattr(node, "id", "") or "")
    label = str(getattr(node, "label", "") or "").strip()
    meta = str(getattr(node, "meta", "") or "").strip()
    kind = str(getattr(node, "kind", "") or "").casefold()
    if nid.startswith("cnpj-"):
        return parse_seed(nid.split("-", 1)[1], forced_kind="CNPJ") or parse_seed(meta, forced_kind="CNPJ")
    if nid.startswith("cpf-"):
        return parse_seed(nid.split("-", 1)[1], forced_kind="CPF") or parse_seed(meta, forced_kind="CPF")
    for raw in (meta, label):
        seed = parse_seed(raw)
        if seed and seed.kind in _STRONG_HIT_KINDS:
            return seed
    forced = {"org": "CNPJ", "person": "NAME", "owner": "NAME", "profile": "USERNAME", "email": "EMAIL", "vehicle": "PLATE", "case": "CNJ"}.get(kind)
    if forced == "CNPJ":
        return parse_seed(meta, forced_kind="CNPJ") or parse_seed(label, forced_kind="NAME")
    if forced == "NAME" and label.count(" ") >= 1:
        return parse_seed(label, forced_kind="NAME")
    if forced and forced != "NAME":
        return parse_seed(label, forced_kind=forced) or parse_seed(meta, forced_kind=forced)
    return None


def _rel_from_label(label: str) -> str:
    text = (label or "").casefold()
    if "sóci" in text or "soci" in text:
        return "SOCIO"
    if "admin" in text:
        return "ADMIN"
    if "propriet" in text:
        return "PROPRIETARIO"
    if "parte" in text:
        return "PARTE"
    return "RELACIONADO"


def list_tools(query: str = "") -> list[EmbeddedTool]:
    needle = (query or "").casefold().strip()
    if not needle:
        return list(EMBEDDED_TOOLS)
    return [
        tool
        for tool in EMBEDDED_TOOLS
        if needle in tool.name.casefold()
        or needle in tool.summary.casefold()
        or needle in tool.inspired.casefold()
        or needle in tool.id
        or needle in tool.kind.casefold()
    ]


def get_tool(tool_id: str) -> EmbeddedTool | None:
    key = (tool_id or "").strip().lower()
    return next((t for t in EMBEDDED_TOOLS if t.id == key), None)


def run_embedded_tool(tool_id: str, raw: str, *, settings: Settings | None = None, live: bool = True) -> ConsultResult | MassResult:
    tool = get_tool(tool_id)
    if not tool:
        return ConsultResult(kind="", query=raw, title="", summary="", ok=False, error="Ferramenta desconhecida.")
    if tool.id == "massa":
        return run_mass(raw, settings=settings, live=live)
    if tool.id == "pdf":
        return ConsultResult(
            kind="FILE",
            query=raw,
            title="PDF",
            summary="Envie o arquivo no formulário — a leitura acontece no servidor, no caso escolhido.",
            ok=True,
            notes=["Equivalente FOCA: só o PDF que você manda. Sem varrer a web."],
        )
    if tool.id == "crtsh":
        return _consult_domain(raw, settings or get_settings(), live=live)
    if tool.id == "hosts":
        return _consult_hosts(raw, settings or get_settings(), live=live)
    if tool.id == "hostficha":
        return _consult_host_fiche(raw, settings or get_settings(), live=live)
    if tool.id == "web":
        return _consult_web(raw, settings or get_settings(), live=live)
    return run_consult(raw, mode=tool.kind, settings=settings)


def run_mass(raw: str, *, mode: str = "auto", settings: Settings | None = None, live: bool = True) -> MassResult:
    settings = settings or get_settings()
    try:
        primary = run_consult(raw, mode=mode, settings=settings, quick=not live)
    except Exception as exc:  # noqa: BLE001
        return MassResult(query=raw, kind="", title=raw, summary="", ok=False, error=str(exc) or "Falha na consulta principal.")
    if not primary.ok:
        return MassResult(query=raw, kind=primary.kind, title=raw, summary="", parts=[primary], ok=False, error=primary.error)
    derived = _derive(primary)
    parts = [primary]
    if live:
        for kind, value in derived:
            try:
                extra = _run_derived(kind, value, settings, quick=True)
            except Exception as exc:  # noqa: BLE001
                extra = ConsultResult(
                    kind=kind,
                    query=value,
                    title=value,
                    summary="",
                    ok=False,
                    error=f"Correlato {kind} falhou: {exc}",
                )
            if extra:
                parts.append(extra)
    summary = f"{len(parts)} consulta(s) a partir de {primary.kind_label}. {len(derived)} correlato(s) derivado(s)."
    return MassResult(
        query=primary.query,
        kind=primary.kind,
        title=primary.title,
        summary=summary,
        parts=parts,
        derived=derived,
        ok=True,
    )


def seeds_from_results(parts: list[ConsultResult]) -> list:
    return seeds_from_kind_values(
        (part.kind, part.query)
        for part in parts
        if part.ok and part.query and part.kind not in {"", "FILE"}
    )


def _derive(primary: ConsultResult) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if primary.kind == "EMAIL":
        _local, _, domain = primary.query.partition("@")
        if domain:
            out.append(("URL", domain))
    elif primary.kind == "USERNAME":
        user = primary.query.lstrip("@")
        out.append(("NAME", user.replace(".", " ").replace("_", " ")))
    elif primary.kind == "NAME":
        slug = "".join(ch for ch in primary.query.casefold() if ch.isalnum() or ch.isspace())
        parts = slug.split()
        if parts:
            out.append(("USERNAME", "".join(parts)[:32]))
            if len(parts) >= 2:
                out.append(("USERNAME", f"{parts[0]}.{parts[-1]}"[:32]))
    elif primary.kind == "CNPJ":
        for hit in primary.hits:
            if hit.kind == "socio" and hit.title and " " in hit.title:
                out.append(("NAME", hit.title))
    elif primary.kind == "PHONE":
        digits = only_digits(primary.query)
        if digits:
            out.append(("USERNAME", digits[-8:]))
    return out[:8]


def _run_derived(kind: str, value: str, settings: Settings, *, quick: bool = True) -> ConsultResult | None:
    live = not quick
    if kind == "URL":
        return _consult_domain(value, settings, live=live)
    if kind == "USERNAME":
        return run_consult(value, mode="USERNAME", settings=settings, quick=quick)
    if kind == "NAME" and " " in value.strip():
        return run_consult(value, mode="NAME", settings=settings, quick=quick)
    if kind == "NAME":
        return _consult_web(value, settings, live=live)
    return run_consult(value, mode=kind, settings=settings, quick=quick)


def _consult_domain(raw: str, settings: Settings, *, live: bool) -> ConsultResult:
    host = (raw or "").strip().lower()
    host = host.replace("https://", "").replace("http://", "").split("/")[0].lstrip("www.")
    if not _DOMAIN_RE.match(host):
        return ConsultResult(kind="URL", query=raw, title=raw, summary="", ok=False, error="Informe um domínio (exemplo.com).")
    if not live or not settings.crtsh_enable:
        return ConsultResult(
            kind="URL",
            query=host,
            title=host,
            summary="Domínio reconhecido. crt.sh consulta os certificados ao rodar ao vivo.",
            facts=[("Domínio", host)],
            notes=["Módulo embutido no estilo SpiderFoot. Sem abrir crt.sh no navegador."],
        )
    conn = CrtshConnector(settings)
    fake = SimpleNamespace(
        canonical_key=f"url:https://{host}",
        display_name=host,
        entity_type="ORG",
        identifiers=[SimpleNamespace(kind="NAME", value=host)],
    )
    try:
        parsed = conn.collect(fake, SimpleNamespace())
    except Exception as exc:  # noqa: BLE001
        return ConsultResult(
            kind="URL",
            query=host,
            title=host,
            summary="crt.sh indisponível neste momento.",
            facts=[("Domínio", host)],
            notes=[str(exc)],
        )
    hits = [ConsultHit(e.display_name, str((e.attrs or {}).get("issuer") or "certificado"), e.value, "host") for e in parsed.entities]
    extra_notes = list(parsed.notes)
    if live and settings.host_public_enable:
        extra = _collect_hosts(host, settings)
        hits.extend(extra[0])
        extra_notes.extend(extra[1])
    return ConsultResult(
        kind="URL",
        query=host,
        title=host,
        summary=f"{len(hits)} nome(s) público(s)." if hits else "Nenhum nome extra neste momento.",
        facts=[("Domínio", host)],
        hits=hits,
        notes=extra_notes + ["crt.sh (certificado). Hosts extras: índices passivos, sem probe."],
    )


def _collect_hosts(host: str, settings: Settings) -> tuple[list[ConsultHit], list[str]]:
    from osint4all.connectors.host_public import HostPublicConnector

    fake = SimpleNamespace(
        canonical_key=f"url:https://{host}",
        display_name=host,
        entity_type="ORG",
        identifiers=[SimpleNamespace(kind="NAME", value=host)],
    )
    try:
        parsed = HostPublicConnector(settings).collect(fake, SimpleNamespace())
    except Exception as exc:  # noqa: BLE001
        return [], [str(exc)]
    hits = [
        ConsultHit(e.display_name, str((e.attrs or {}).get("fonte") or "host"), e.value, "host")
        for e in parsed.entities
    ]
    return hits, list(parsed.notes)


def _consult_hosts(raw: str, settings: Settings, *, live: bool) -> ConsultResult:
    host = (raw or "").strip().lower()
    host = host.replace("https://", "").replace("http://", "").split("/")[0].lstrip("www.")
    if not _DOMAIN_RE.match(host):
        return ConsultResult(kind="URL", query=raw, title=raw, summary="", ok=False, error="Informe um domínio (exemplo.com).")
    if not live or not settings.host_public_enable:
        return ConsultResult(
            kind="URL",
            query=host,
            title=host,
            summary="Domínio reconhecido. Índices públicos (Wayback / HackerTarget / urlscan) rodam ao vivo.",
            facts=[("Domínio", host)],
            notes=["Estilo theHarvester. Sem brute de DNS e sem varrer porta."],
        )
    hits, notes = _collect_hosts(host, settings)
    return ConsultResult(
        kind="URL",
        query=host,
        title=host,
        summary=f"{len(hits)} host(s) ou e-mail(s) em índices públicos." if hits else "Nenhum host extra nesta passagem.",
        facts=[("Domínio", host)],
        hits=hits,
        notes=notes + ["Fontes passivas. Complementa crt.sh; não substitui o banco do Shodan."],
    )


def _consult_host_fiche(raw: str, settings: Settings, *, live: bool) -> ConsultResult:
    from osint4all.intel.hosts import is_public_hostname, normalize_host

    host = normalize_host(raw) or ""
    if not host or not is_public_hostname(host):
        return ConsultResult(kind="URL", query=raw, title=raw, summary="", ok=False, error="Informe um domínio público já conhecido (exemplo.com). Sem IP.")
    notes = [
        "httpx parcial: um GET HTTPS no host do dossiê (status, título, Server).",
        "Photon raso: links da homepage, mesmo domínio.",
        "Nuclei só informativo: security.txt e sitemap.",
        "IVRE local: o caso indexa e correlaciona essas fichas. Não inicia scan.",
    ]
    if not live or not settings.host_observe_enable:
        return ConsultResult(
            kind="URL",
            query=host,
            title=host,
            summary="Domínio reconhecido. A ficha HTTP roda ao vivo no host que você já tem.",
            facts=[("Domínio", host)],
            notes=notes,
        )
    from osint4all.connectors.host_observe import HostObserveConnector

    fake = SimpleNamespace(
        canonical_key=f"url:https://{host}",
        display_name=host,
        entity_type="ORG",
        identifiers=[SimpleNamespace(kind="URL", value=f"https://{host}")],
        attrs={"host": host},
    )
    try:
        parsed = HostObserveConnector(settings).collect(fake, SimpleNamespace())
    except Exception as exc:  # noqa: BLE001
        return ConsultResult(kind="URL", query=host, title=host, summary="Ficha indisponível neste momento.", facts=[("Domínio", host)], notes=[str(exc), *notes])
    hits = [ConsultHit(e.display_name, str((e.attrs or {}).get("fonte") or "host"), e.value, "host") for e in parsed.entities]
    hits.extend(ConsultHit(ev.source_label, ev.snippet or "", ev.url, "ficha") for ev in parsed.evidence[:6])
    facts = [("Domínio", host)]
    return ConsultResult(
        kind="URL",
        query=host,
        title=host,
        summary=f"Ficha do host conhecido: {len(hits)} evidência(s)." if hits else "Host conhecido; a homepage não respondeu nesta passagem.",
        facts=facts,
        hits=hits,
        notes=list(parsed.notes) + notes,
    )


def _consult_web(raw: str, settings: Settings, *, live: bool) -> ConsultResult:
    text = (raw or "").strip()
    if not text:
        return ConsultResult(kind="NAME", query="", title="", summary="", ok=False, error="Digite o termo.")
    if not live or not settings.web_search_enable:
        return ConsultResult(
            kind="NAME",
            query=text,
            title=text,
            summary="Menções web: SearXNG público, ou Brave / Google CSE se configurados.",
            notes=["A busca roda no servidor. Sem abrir o Google no navegador."],
        )
    if not web_search_ready(settings):
        return ConsultResult(
            kind="NAME",
            query=text,
            title=text,
            summary="Nenhum backend de busca ativo.",
            notes=["SEARXNG_URL, BRAVE_SEARCH_API_KEY ou GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX."],
        )
    conn = WebSearchConnector(settings)
    fake = SimpleNamespace(
        canonical_key=f"name:{text.casefold()}",
        display_name=text,
        entity_type="PERSON",
        identifiers=[],
    )
    try:
        parsed = conn.collect(fake, SimpleNamespace())
    except Exception as exc:  # noqa: BLE001
        return ConsultResult(
            kind="NAME",
            query=text,
            title=text,
            summary="Busca web indisponível neste momento.",
            notes=[str(exc)],
        )
    hits = [ConsultHit(e.display_name, str((e.attrs or {}).get("snippet") or ""), e.value, "mencao") for e in parsed.entities]
    return ConsultResult(
        kind="NAME",
        query=text,
        title=text,
        summary=f"{len(hits)} menção(ões) públicas." if hits else "Nenhuma menção nesta busca.",
        hits=hits,
        notes=list(parsed.notes),
    )


def as_dict(tool: EmbeddedTool) -> dict[str, Any]:
    return {
        "id": tool.id,
        "name": tool.name,
        "summary": tool.summary,
        "kind": tool.kind,
        "placeholder": tool.placeholder,
        "inspired": tool.inspired,
        "upload": tool.upload,
        "internal": True,
        "url": f"/app/ferramentas?tool={tool.id}",
    }
