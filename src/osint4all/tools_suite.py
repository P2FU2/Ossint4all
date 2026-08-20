"""Ferramentas embutidas — rodam no painel, sem abrir GitHub ou sites terceiros."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from osint4all.config import Settings, get_settings
from osint4all.connectors.crtsh import CrtshConnector, _DOMAIN_RE
from osint4all.connectors.web_search import WebSearchConnector, web_search_ready
from osint4all.consult import ConsultHit, ConsultResult, run_consult
from osint4all.identifiers import parse_seed
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
        "Checa URLs públicas canônicas (HTTP 200). Equivalente embutido de Sherlock / WhatsMyName / user-scanner.",
        "USERNAME",
        "@usuario",
        "Sherlock, WhatsMyName, user-scanner",
    ),
    EmbeddedTool("plate", "Placa", "Série, portais e menções públicas do veículo/dono. Sem cadastro DETRAN.", "PLATE", "ABC1D23", "SENATRAN / DENATRAN"),
    EmbeddedTool("phone", "Telefone", "Normaliza o número e aponta menções públicas. Sem operadora.", "PHONE", "11 99999-0000", "Mr.Holmes"),
    EmbeddedTool("name", "Sócio / nome", "Empresas do quadro societário na base aberta da Receita.", "NAME", "Nome e sobrenome", "Receita / Casa dos Dados"),
    EmbeddedTool("cnpj", "CNPJ", "Ficha, QSA e mapa de empresas relacionadas.", "CNPJ", "00.000.000/0001-00", "Minha Receita / BrasilAPI"),
    EmbeddedTool("cpf", "CPF", "Valida e cruza QSA público, sanções e menções. Sem nome pela Receita.", "CPF", "000.000.000-00", "Receita / Transparência"),
    EmbeddedTool("email", "E-mail", "Linha do tempo: @user, Gravatar e redes públicas. Sem caixa nem vazamento.", "EMAIL", "nome@dominio.com", "user-scanner"),
    EmbeddedTool("cnj", "Processo", "Reconhece o número CNJ. Capa no DataJud ao guardar no grafo.", "CNJ", "0000001-23.2024.8.26.0100", "DataJud / CNJ"),
    EmbeddedTool(
        "crtsh",
        "Certificados",
        "Nomes em Certificate Transparency (crt.sh). Módulo típico do SpiderFoot.",
        "URL",
        "exemplo.com",
        "crt.sh / SpiderFoot",
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
        "Metadados de PDF",
        "Lê autor, software e datas do arquivo que você envia. Equivalente embutido da FOCA, sem varrer a web.",
        "FILE",
        "",
        "FOCA",
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
    seeds = []
    seen: set[str] = set()
    for part in parts:
        if not part.ok or not part.query or part.kind in {"", "FILE"}:
            continue
        seed = parse_seed(part.query, forced_kind=part.kind or None)
        if seed and seed.canonical_key not in seen:
            seen.add(seed.canonical_key)
            seeds.append(seed)
    return seeds


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
    if kind == "URL":
        return _consult_domain(value, settings, live=True)
    if kind == "USERNAME":
        return run_consult(value, mode="USERNAME", settings=settings, quick=quick)
    if kind == "NAME" and " " in value.strip():
        return run_consult(value, mode="NAME", settings=settings)
    if kind == "NAME":
        return _consult_web(value, settings, live=True)
    return run_consult(value, mode=kind, settings=settings)


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
    return ConsultResult(
        kind="URL",
        query=host,
        title=host,
        summary=f"{len(hits)} nome(s) em certificados públicos." if hits else "Nenhum nome extra neste momento.",
        facts=[("Domínio", host)],
        hits=hits,
        notes=list(parsed.notes) + ["Fonte: crt.sh JSON, consultado pelo servidor."],
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
