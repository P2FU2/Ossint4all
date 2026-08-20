"""Consultas rápidas — sem abrir um caso. Só fontes públicas."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from osint4all.config import Settings, get_settings
from osint4all.connectors.cnpj_receita import CnpjReceitaConnector, parse_cnpj_payload
from osint4all.connectors.plate_public import (
    _DETRAN_PORTAL,
    describe_plate,
    extract_owner_mentions,
    extract_vehicle_mentions,
    parse_plate_enrichment,
)
from osint4all.connectors.socio_search import SocioSearchConnector
from osint4all.connectors.transparencia import TransparenciaConnector
from osint4all.connectors.username_public import UsernamePublicConnector
from osint4all.connectors.web_search import WebSearchConnector
from osint4all.identifiers import detect_kind, parse_seed
from osint4all.security import only_digits
from osint4all.validators import format_plate, looks_like_plate, validate_cnpj, validate_cpf


# key, label, tip, placeholder
MODES = (
    ("auto", "Detectar", "Reconhece placa, CNPJ, CPF, e-mail, telefone, @user, processo ou nome.", "ABC1D23, @user, e-mail, CPF…"),
    ("PLATE", "Placa", "Série, portais oficiais e menções públicas do veículo/dono. Sem DETRAN de cadastro.", "ABC1D23 ou ABC-1234"),
    ("USERNAME", "Rede social", "URLs públicas (GitHub, X, Telegram…). Sem login.", "@usuario"),
    ("PHONE", "Telefone", "Normaliza e aponta menções públicas. Sem operadora.", "11 99999-0000"),
    ("NAME", "Sócio / nome", "Empresas do quadro societário na base aberta da Receita.", "Nome e sobrenome"),
    ("CNPJ", "CNPJ", "Ficha, QSA e mapa de empresas relacionadas (sócios PJ e outras firmas dos sócios).", "00.000.000/0001-00"),
    ("CPF", "CPF", "Valida, cruza QSA público, sanções e menções. A Receita não devolve o nome por API.", "000.000.000-00"),
    ("EMAIL", "E-mail", "Perfis públicos do local-part em linha do tempo. Sem caixa nem vazamento.", "nome@dominio.com"),
    ("CNJ", "Processo", "Número CNJ. Capa e partes vêm do DataJud ao guardar no grafo.", "0000123-45.2024.8.26.0100"),
    ("massa", "Massa", "Um dado só: deriva correlatos (user, domínio, sócio, menções) e cruza no painel.", "um único identificador"),
)

KIND_LABELS = {
    "PLATE": "Placa",
    "USERNAME": "Rede social",
    "PHONE": "Telefone",
    "NAME": "Sócio / nome",
    "CNPJ": "CNPJ",
    "CPF": "CPF",
    "EMAIL": "E-mail",
    "CNJ": "Processo",
    "URL": "Domínio",
    "massa": "Massa",
}

_UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MG": "Minas Gerais", "MS": "Mato Grosso do Sul", "MT": "Mato Grosso",
    "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí", "PR": "Paraná",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia", "RR": "Roraima",
    "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}


@dataclass
class ConsultHit:
    title: str
    meta: str = ""
    url: str | None = None
    kind: str = "item"
    when: str = ""


@dataclass
class TimelineEvent:
    title: str
    meta: str = ""
    url: str | None = None
    when: str = ""
    kind: str = "event"


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str = "org"
    meta: str = ""


@dataclass
class GraphEdge:
    source: str
    target: str
    label: str = ""


@dataclass
class ConsultGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "nodes": [{"id": n.id, "label": n.label, "kind": n.kind, "meta": n.meta} for n in self.nodes],
            "edges": [{"source": e.source, "target": e.target, "label": e.label} for e in self.edges],
        }


@dataclass
class ConsultResult:
    kind: str
    query: str
    title: str
    summary: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    hits: list[ConsultHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    graph: ConsultGraph | None = None
    ok: bool = True
    error: str | None = None

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind or "Consulta")

    @property
    def graph_payload(self) -> dict[str, Any] | None:
        return self.graph.to_payload() if self.graph and self.graph.nodes else None


def resolve_kind(mode: str, raw: str) -> str | None:
    forced = (mode or "auto").upper()
    if forced in {"", "AUTO"}:
        return detect_kind(raw)
    seed = parse_seed(raw, forced_kind=forced)
    return seed.kind if seed else forced


def _live_ok(settings: Settings, quick: bool) -> bool:
    if quick:
        return False
    if settings.env == "test":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def run_consult(raw: str, *, mode: str = "auto", settings: Settings | None = None, quick: bool = False) -> ConsultResult:
    text = (raw or "").strip()
    if not text:
        return ConsultResult(kind="", query="", title="", summary="", ok=False, error="Digite um identificador.")
    if (mode or "").lower() == "massa":
        from osint4all.tools_suite import run_mass

        mass = run_mass(text, settings=settings, live=not quick)
        if not mass.ok:
            return ConsultResult(kind=mass.kind, query=mass.query, title=mass.title, summary="", ok=False, error=mass.error)
        hits = [ConsultHit(p.title, p.summary, None, p.kind) for p in mass.parts if p.ok]
        return ConsultResult(
            kind="massa",
            query=mass.query,
            title=mass.title,
            summary=mass.summary,
            hits=hits,
            notes=[f"{k}: {v}" for k, v in mass.derived],
        )
    settings = settings or get_settings()
    kind = resolve_kind(mode, text)
    if not kind:
        return ConsultResult(kind="", query=text, title="", summary="", ok=False, error="Não reconheci esse valor. Escolha o tipo à esquerda.")
    try:
        if kind == "PLATE":
            return _consult_plate(text, settings, quick=quick)
        if kind == "USERNAME":
            return _consult_username(text, settings, quick=quick)
        if kind == "PHONE":
            return _consult_phone(text)
        if kind == "CNPJ":
            return _consult_cnpj(text, settings, quick=quick)
        if kind == "CPF":
            return _consult_cpf(text, settings, quick=quick)
        if kind == "EMAIL":
            return _consult_email(text, settings, quick=quick)
        if kind == "NAME":
            return _consult_name(text, settings)
        if kind == "CNJ":
            return _consult_cnj(text)
    except Exception as exc:  # noqa: BLE001
        return ConsultResult(kind=kind, query=text, title=text, summary="", ok=False, error=str(exc))
    return ConsultResult(kind=kind, query=text, title=text, summary="Tipo reconhecido. Abra um caso para expandir o grafo.")


def _consult_plate(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    if not looks_like_plate(raw):
        return ConsultResult(kind="PLATE", query=raw, title=raw, summary="", ok=False, error="Placa inválida. Use ABC1D23 ou ABC-1234.")
    settings = settings or get_settings()
    info = describe_plate(raw)
    pretty = info["placa"]
    compact = info["placa_compacta"]
    parsed = parse_plate_enrichment(raw, origin_key=f"plate:{compact}")
    uf = info.get("serie_uf") or ""
    uf_name = _UF_NAMES.get(uf, "")
    hits = [
        ConsultHit(ev.source_label, ev.snippet or "", ev.url, "fonte")
        for ev in parsed.evidence
    ]
    facts = [
        ("Padrão", info["padrao"]),
        ("Série (1º emplacamento)", f"{uf} · {uf_name}" if uf else "—"),
        ("Placa compacta", compact),
        ("Formato", pretty),
        ("Mercosul", "sim" if compact[4:5].isalpha() else "não (cinza)"),
    ]
    notes = [
        "O DETRAN/SENATRAN não publicam o proprietário só com a placa. Cadastro de dono exige Renavam + gov.br.",
        "Abaixo: série histórica, portais oficiais e menções públicas (leilões, diários, notícias) se existirem.",
    ]
    timeline: list[TimelineEvent] = [
        TimelineEvent("Série DENATRAN", info.get("serie_nota") or info["padrao"], when="histórico", kind="plate"),
    ]
    if uf and uf in _DETRAN_PORTAL:
        timeline.append(
            TimelineEvent(
                f"Portal DETRAN-{uf}",
                "Consulta estadual — exige placa + Renavam",
                _DETRAN_PORTAL[uf],
                when="oficial",
                kind="fonte",
            )
        )

    owners: list[str] = []
    models: list[str] = []
    if _live_ok(settings, quick):
        web = _safe_web_search(
            settings,
            f'"{compact}" OR "{pretty}" (placa OR veículo OR proprietário OR leilão OR "em nome")',
            f"plate:{compact}",
        )
        blob = " ".join(f"{h.title} {h.meta}" for h in web)
        owners = extract_owner_mentions(blob)
        models = extract_vehicle_mentions(blob)
        hits.extend(web[:8])
        for ev in web[:6]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção web", kind="web"))

    if models:
        facts.append(("Modelo (menção pública)", "; ".join(models)))
        timeline.insert(
            1,
            TimelineEvent("Veículo citado", "; ".join(models), when="menção pública", kind="vehicle"),
        )
    if owners:
        facts.append(("Possível dono (menção pública)", "; ".join(owners)))
        for name in owners:
            timeline.append(
                TimelineEvent("Possível proprietário", name, when="menção pública", kind="owner")
            )
        notes.append("Nome de dono veio de texto público, não do cadastro do DETRAN. Confira a fonte.")
    else:
        facts.append(("Proprietário oficial", "não publicado por API — informe o nome se já tiver fonte lícita"))

    graph = ConsultGraph(
        nodes=[GraphNode("plate", pretty, "vehicle", info["padrao"])],
        edges=[],
    )
    for idx, name in enumerate(owners):
        nid = f"owner-{idx}"
        graph.nodes.append(GraphNode(nid, name, "person", "menção pública"))
        graph.edges.append(GraphEdge(nid, "plate", "possível dono"))
    for idx, model in enumerate(models):
        nid = f"model-{idx}"
        graph.nodes.append(GraphNode(nid, model, "vehicle", "modelo citado"))
        graph.edges.append(GraphEdge("plate", nid, "menciona"))

    return ConsultResult(
        kind="PLATE",
        query=pretty,
        title=pretty,
        summary=(
            f"{info['padrao']}. {info['serie_nota']}"
            + (f" Modelo citado: {models[0]}." if models else "")
            + (f" Dono em menção pública: {owners[0]}." if owners else " Sem dono em fonte pública nesta busca.")
        ),
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph if len(graph.nodes) > 1 else None,
    )


def _consult_username(raw: str, settings: Settings, *, quick: bool = False) -> ConsultResult:
    user = raw.strip().lstrip("@").lower()
    conn = UsernamePublicConnector(settings)
    fake = SimpleNamespace(canonical_key=f"username:{user}", display_name=user, entity_type="PROFILE", identifiers=[])
    result = conn.collect(fake, SimpleNamespace(core_only=quick))
    hits = [ConsultHit(e.display_name, e.value, e.value, "perfil") for e in result.entities]
    timeline = [
        TimelineEvent(h.title, h.meta, h.url, when="perfil ativo", kind="social")
        for h in hits
    ]
    graph = ConsultGraph(nodes=[GraphNode("user", f"@{user}", "profile", "semente")], edges=[])
    for idx, hit in enumerate(hits):
        nid = f"net-{idx}"
        graph.nodes.append(GraphNode(nid, hit.title, "profile", hit.meta))
        graph.edges.append(GraphEdge("user", nid, "perfil"))
    return ConsultResult(
        kind="USERNAME",
        query=f"@{user}",
        title=f"@{user}",
        summary=f"{len(hits)} perfil(is) público(s) com HTTP 200. Ausência não prova que a conta não existe.",
        facts=[("Usuário", user), ("Redes checadas", str(len(conn.health()["networks"])))],
        hits=hits,
        timeline=timeline,
        graph=graph if hits else None,
        notes=["Só URLs canônicas públicas. Sem sessionid, sem Instagram privado."],
    )


def _consult_phone(raw: str) -> ConsultResult:
    digits = only_digits(raw)
    if len(digits) < 10:
        return ConsultResult(kind="PHONE", query=raw, title=raw, summary="", ok=False, error="Telefone curto demais.")
    wa = f"https://wa.me/{digits}" if digits.startswith("55") or len(digits) >= 12 else f"https://wa.me/55{digits}"
    return ConsultResult(
        kind="PHONE",
        query=digits,
        title=digits,
        summary="Número normalizado. Não consultamos operadora nem cadastro de assinante.",
        facts=[("Dígitos", digits), ("Tamanho", str(len(digits)))],
        hits=[
            ConsultHit("WhatsApp (link público)", "Abre conversa se o número existir no app", wa, "link"),
            ConsultHit("Truecaller web", "Busca pública de menção", f"https://www.truecaller.com/search/br/{digits}", "link"),
        ],
        notes=["Use só números que já apareceram em fonte pública. Guardar no grafo liga o telefone a um caso."],
    )


def _consult_cnpj(raw: str, settings: Settings, *, quick: bool = False) -> ConsultResult:
    if not validate_cnpj(raw):
        return ConsultResult(kind="CNPJ", query=raw, title=raw, summary="", ok=False, error="CNPJ inválido.")
    digits = only_digits(raw)
    data = CnpjReceitaConnector(settings)._fetch(digits)
    parsed = parse_cnpj_payload(data)
    org = next((e for e in parsed.entities if e.kind == "CNPJ" and only_digits(e.value) == digits), None)
    attrs = org.attrs if org else {}
    partners = [
        e
        for e in parsed.entities
        if not (e.kind == "CNPJ" and only_digits(e.value) == digits)
    ]
    hits = [
        ConsultHit(
            e.display_name,
            " · ".join(
                bit
                for bit in (
                    str(e.attrs.get("papel") or e.kind),
                    only_digits(e.value) if e.kind in {"CNPJ", "CPF"} else "",
                    str(e.attrs.get("entrada") or ""),
                )
                if bit
            ),
            f"https://minhareceita.org/{only_digits(e.value)}" if e.kind == "CNPJ" else None,
            "socio",
            str(e.attrs.get("entrada") or ""),
        )
        for e in partners
    ]
    facts = [
        ("CNPJ", _format_cnpj(digits)),
        ("Razão social", str(attrs.get("razao_social") or "—")),
        ("Fantasia", str(attrs.get("nome_fantasia") or "—")),
        ("Situação", str(attrs.get("situacao") or "—")),
        ("CNAE", str(attrs.get("cnae") or "—")),
        ("Porte", str(attrs.get("porte") or "—")),
        ("Capital", str(attrs.get("capital_social") or "—")),
        ("Natureza", str(attrs.get("natureza_juridica") or "—")),
        ("Início", str(attrs.get("data_inicio") or "—")),
        ("Simples", str(attrs.get("simples"))),
        ("MEI", str(attrs.get("mei"))),
        ("Endereço", str(attrs.get("endereco") or "—")),
        ("Município", f"{attrs.get('municipio') or ''} / {attrs.get('uf') or ''}".strip(" /")),
        ("Telefone", str(attrs.get("telefone") or "—")),
        ("E-mail", str(attrs.get("email") or "—")),
    ]
    graph = _graph_from_cnpj(digits, str(attrs.get("razao_social") or org.display_name if org else digits), partners)
    timeline = [
        TimelineEvent("Abertura", str(attrs.get("data_inicio") or "n/d"), when=str(attrs.get("data_inicio") or "n/d"), kind="org"),
        TimelineEvent("Situação cadastral", str(attrs.get("situacao") or "n/d"), when=str(attrs.get("data_situacao") or "n/d"), kind="org"),
    ]
    for partner in partners:
        timeline.append(
            TimelineEvent(
                partner.display_name,
                str(partner.attrs.get("papel") or partner.kind),
                f"https://minhareceita.org/{only_digits(partner.value)}" if partner.kind == "CNPJ" else None,
                when=str(partner.attrs.get("entrada") or "QSA"),
                kind="socio",
            )
        )

    related_notes: list[str] = []
    if _live_ok(settings, quick):
        extra_hits, extra_nodes, extra_edges = _expand_related_companies(settings, digits, partners)
        hits.extend(extra_hits)
        for node in extra_nodes:
            if node.id not in {n.id for n in graph.nodes}:
                graph.nodes.append(node)
        graph.edges.extend(extra_edges)
        related_count = sum(1 for n in graph.nodes if n.kind == "org" and n.id != f"cnpj-{digits}")
        related_notes.append(f"{related_count} empresa(s) no mapa (QSA + outras firmas dos sócios).")

    hits.append(ConsultHit("Minha Receita", "Ficha oficial", f"https://minhareceita.org/{digits}", "fonte"))
    title = str(attrs.get("nome_fantasia") or attrs.get("razao_social") or (org.display_name if org else digits))
    return ConsultResult(
        kind="CNPJ",
        query=digits,
        title=title,
        summary=f"{attrs.get('situacao') or 'Situação n/d'} · {attrs.get('municipio') or ''} {attrs.get('uf') or ''}".strip(),
        facts=facts,
        hits=hits,
        notes=related_notes,
        timeline=_sort_timeline(timeline),
        graph=graph,
    )


def _consult_cpf(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    if not validate_cpf(raw):
        return ConsultResult(kind="CPF", query=raw, title=raw, summary="", ok=False, error="CPF inválido.")
    settings = settings or get_settings()
    digits = only_digits(raw)
    masked = f"***.***.***-{digits[-2:]}"
    formatted = f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    origin = f"cpf:{digits}"
    hits: list[ConsultHit] = [
        ConsultHit(
            "Situação cadastral (Receita)",
            "Portal oficial — exige os dados do titular",
            "https://servicos.receita.fazenda.gov.br/Servicos/CPF/ConsultaSituacao/ConsultaPublica.asp",
            "fonte",
        ),
        ConsultHit(
            "Portal da Transparência",
            "CEIS / CNEP e demais listas públicas",
            f"https://portaldatransparencia.gov.br/busca?termo={digits}",
            "fonte",
        ),
    ]
    facts = [
        ("CPF", formatted),
        ("Máscara", masked),
        ("Dígitos", "11 · checksum ok"),
    ]
    timeline = [
        TimelineEvent("Número válido", "Dígitos verificadores da Receita batem", when="validação", kind="id"),
    ]
    graph = ConsultGraph(nodes=[GraphNode("cpf", masked, "person", formatted)], edges=[])
    notes = [
        "A Receita não publica o nome pelo CPF em API aberta. O que aparece abaixo veio de bases públicas (QSA, sanções, menções).",
    ]

    companies = 0
    sanctions = 0
    if _live_ok(settings, quick):
        try:
            socio = SocioSearchConnector(settings).collect_by_cpf(digits, origin)
            for entity in socio.entities:
                if entity.entity_type != "ORG":
                    continue
                companies += 1
                cnpj = only_digits(entity.value)
                hits.append(
                    ConsultHit(
                        entity.display_name,
                        " · ".join(
                            bit
                            for bit in (
                                str(entity.attrs.get("situacao") or ""),
                                f"{entity.attrs.get('municipio') or ''}/{entity.attrs.get('uf') or ''}".strip("/"),
                                cnpj,
                            )
                            if bit and bit != "/"
                        ),
                        f"https://minhareceita.org/{cnpj}" if validate_cnpj(cnpj) else None,
                        "empresa",
                    )
                )
                nid = f"cnpj-{cnpj or companies}"
                graph.nodes.append(GraphNode(nid, entity.display_name, "org", cnpj))
                graph.edges.append(GraphEdge("cpf", nid, "sócio"))
                timeline.append(
                    TimelineEvent(
                        entity.display_name,
                        "Empresa no quadro societário público",
                        f"https://minhareceita.org/{cnpj}" if validate_cnpj(cnpj) else None,
                        when="QSA",
                        kind="org",
                    )
                )
        except Exception:
            notes.append("Índice de sócios indisponível neste momento.")

        if settings.transparencia_enable and settings.transparencia_api_key:
            try:
                fake = SimpleNamespace(
                    canonical_key=origin,
                    display_name=masked,
                    entity_type="PERSON",
                    identifiers=[SimpleNamespace(kind="CPF", value=digits)],
                )
                parsed = TransparenciaConnector(settings).collect(fake, SimpleNamespace())
                for ev in parsed.evidence:
                    sanctions += 1
                    hits.append(ConsultHit(ev.source_label, ev.snippet or "", ev.url, "sancao"))
                    timeline.append(TimelineEvent(ev.source_label, ev.snippet or "", ev.url, when="sanção", kind="alert"))
            except Exception:
                pass

        web = _safe_web_search(
            settings,
            f'"{formatted}" OR "{digits}" (CPF OR sócio OR processo OR "portal da transparência")',
            origin,
        )
        hits.extend(web[:8])
        for ev in web[:6]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção web", kind="web"))

    facts.append(("Empresas (QSA público)", str(companies)))
    facts.append(("Sanções / listas", str(sanctions)))
    summary = (
        f"CPF válido. {companies} empresa(s) no quadro societário público"
        + (f", {sanctions} registro(s) em listas oficiais" if sanctions else "")
        + "."
    )
    if not companies and not _live_ok(settings, quick):
        summary = "Número válido. A Receita não publica nome pelo CPF em API aberta."
        notes.append("Para cruzar com empresas, rode a consulta ao vivo ou use o nome do titular.")
    return ConsultResult(
        kind="CPF",
        query=digits,
        title=masked,
        summary=summary,
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph if len(graph.nodes) > 1 else None,
    )


def _consult_email(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    settings = settings or get_settings()
    email = raw.strip().lower()
    local, _, domain = email.partition("@")
    if not local or not domain or "@" not in email:
        return ConsultResult(kind="EMAIL", query=raw, title=raw, summary="", ok=False, error="E-mail inválido.")
    hits: list[ConsultHit] = [
        ConsultHit("Busca literal do e-mail", domain, f"https://www.google.com/search?q=%22{quote(email)}%22", "link"),
    ]
    timeline: list[TimelineEvent] = [
        TimelineEvent("Identificador", email, when="entrada", kind="id"),
        TimelineEvent("Local-part → @user", f"@{local}", when="derivado", kind="id"),
        TimelineEvent("Domínio", domain, when="derivado", kind="id"),
    ]
    facts = [("Local", local), ("Domínio", domain), ("User derivado", f"@{local}")]
    graph = ConsultGraph(nodes=[GraphNode("email", email, "email", domain)], edges=[])
    graph.nodes.append(GraphNode("user", f"@{local}", "profile", "local-part"))
    graph.edges.append(GraphEdge("email", "user", "deriva"))

    gravatar_url = f"https://www.gravatar.com/{hashlib.md5(email.encode('utf-8'), usedforsecurity=False).hexdigest()}"
    hits.append(ConsultHit("Gravatar (hash público)", "Perfil se o dono cadastrou foto/bio", gravatar_url, "perfil"))

    profiles = 0
    if _live_ok(settings, quick) and settings.username_public_enable:
        try:
            social = _consult_username(local, settings, quick=True)
            for hit in social.hits:
                profiles += 1
                hits.append(hit)
                timeline.append(TimelineEvent(hit.title, hit.meta or "HTTP 200", hit.url, when="perfil ativo", kind="social"))
                nid = f"social-{profiles}"
                graph.nodes.append(GraphNode(nid, hit.title, "profile", hit.meta))
                graph.edges.append(GraphEdge("user", nid, "perfil"))
        except Exception:
            pass
        gravatar = _safe_gravatar(email)
        if gravatar:
            hits.insert(1, gravatar)
            timeline.insert(1, TimelineEvent(gravatar.title, gravatar.meta, gravatar.url, when="identidade", kind="social"))
            graph.nodes.append(GraphNode("gravatar", "Gravatar", "profile", gravatar.meta))
            graph.edges.append(GraphEdge("email", "gravatar", "avatar"))
        web = _safe_web_search(settings, f'"{email}"', f"email:{email}")
        hits.extend(web[:6])
        for ev in web[:5]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção web", kind="web"))

    facts.append(("Perfis públicos", str(profiles)))
    notes = [
        "Não acessamos caixas, Holehe de vazamento nem bases privadas.",
        "A linha do tempo junta o @user derivado do e-mail, Gravatar e URLs públicas que responderam 200.",
    ]
    return ConsultResult(
        kind="EMAIL",
        query=email,
        title=email,
        summary=(
            f"E-mail normalizado. {profiles} rede(s) com o @user «{local}»."
            if profiles
            else "E-mail normalizado. Sem perfil público do local-part nesta passagem."
        ),
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph,
    )


def _consult_name(raw: str, settings: Settings) -> ConsultResult:
    if " " not in raw.strip():
        return ConsultResult(kind="NAME", query=raw, title=raw, summary="", ok=False, error="Use nome e sobrenome.")
    conn = SocioSearchConnector(settings)
    fake = SimpleNamespace(canonical_key=f"name:{raw.strip().casefold()}", display_name=raw.strip(), entity_type="PERSON", identifiers=[])
    parsed = conn.collect(fake, SimpleNamespace(investigation=SimpleNamespace(id="consult"), settings=settings))
    orgs = [e for e in parsed.entities if e.entity_type == "ORG"]
    hits = [
        ConsultHit(
            e.display_name,
            " · ".join(
                bit
                for bit in (
                    str(e.attrs.get("situacao") or ""),
                    f"{e.attrs.get('municipio') or ''}/{e.attrs.get('uf') or ''}".strip("/"),
                    only_digits(e.value) if e.kind == "CNPJ" else "",
                )
                if bit and bit != "/"
            ),
            f"https://minhareceita.org/{only_digits(e.value)}" if e.kind == "CNPJ" else None,
            "empresa",
        )
        for e in orgs
    ]
    graph = ConsultGraph(nodes=[GraphNode("person", raw.strip(), "person", "sócio")], edges=[])
    for idx, org in enumerate(orgs):
        nid = f"org-{idx}"
        graph.nodes.append(GraphNode(nid, org.display_name, "org", only_digits(org.value)))
        graph.edges.append(GraphEdge("person", nid, "sócio"))
    return ConsultResult(
        kind="NAME",
        query=raw.strip(),
        title=raw.strip(),
        summary=f"{len(hits)} empresa(s) no quadro societário público." if hits else "Nenhuma empresa nesta consulta pontual.",
        facts=[("Empresas", str(len(hits)))],
        hits=hits,
        notes=parsed.notes + ["Aprofundar no grafo puxa o QSA completo de cada CNPJ (co-sócios, CNAE, mapa)."],
        graph=graph if hits else None,
    )


def _consult_cnj(raw: str) -> ConsultResult:
    seed = parse_seed(raw, forced_kind="CNJ")
    if not seed:
        return ConsultResult(kind="CNJ", query=raw, title=raw, summary="", ok=False, error="Número CNJ inválido.")
    display = seed.display_name
    return ConsultResult(
        kind="CNJ",
        query=display,
        title=display,
        summary="Número de processo reconhecido. A capa e as partes vêm do DataJud ao guardar no grafo.",
        hits=[
            ConsultHit("DataJud (wiki da chave)", "API pública do CNJ", "https://datajud-wiki.cnj.jus.br/api-publica/acesso/", "fonte"),
        ],
        notes=["Guarde no grafo com o conector datajud ligado."],
    )


def result_to_save_payload(result: ConsultResult) -> dict[str, Any]:
    return {"kind": result.kind, "value": result.query}


def _format_cnpj(digits: str) -> str:
    d = only_digits(digits)
    if len(d) != 14:
        return digits
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _graph_from_cnpj(root_digits: str, root_label: str, partners: list[Any]) -> ConsultGraph:
    graph = ConsultGraph(nodes=[GraphNode(f"cnpj-{root_digits}", root_label, "org", _format_cnpj(root_digits))], edges=[])
    for idx, partner in enumerate(partners):
        kind = "org" if partner.kind == "CNPJ" else "person"
        nid = f"p-{idx}-{only_digits(str(partner.value)) or idx}"
        graph.nodes.append(GraphNode(nid, partner.display_name, kind, str(partner.attrs.get("papel") or partner.kind)))
        graph.edges.append(GraphEdge(nid, f"cnpj-{root_digits}", str(partner.attrs.get("papel") or "sócio")))
    return graph


def _expand_related_companies(
    settings: Settings,
    root_digits: str,
    partners: list[Any],
) -> tuple[list[ConsultHit], list[GraphNode], list[GraphEdge]]:
    hits: list[ConsultHit] = []
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    conn = CnpjReceitaConnector(settings)
    seen: set[str] = {root_digits}
    for partner in partners:
        if partner.kind != "CNPJ":
            continue
        other = only_digits(partner.value)
        if not validate_cnpj(other) or other in seen:
            continue
        seen.add(other)
        if len(seen) > 6:
            break
        try:
            data = conn._fetch(other)
            extra = parse_cnpj_payload(data)
        except Exception:
            continue
        org = next((e for e in extra.entities if e.kind == "CNPJ" and only_digits(e.value) == other), None)
        label = str((org.attrs if org else {}).get("razao_social") or partner.display_name)
        nid = f"cnpj-{other}"
        nodes.append(GraphNode(nid, label, "org", _format_cnpj(other)))
        edges.append(GraphEdge(f"cnpj-{root_digits}", nid, "sócio PJ"))
        hits.append(ConsultHit(label, f"Empresa relacionada · {_format_cnpj(other)}", f"https://minhareceita.org/{other}", "relacionada"))

    socio = SocioSearchConnector(settings)
    people = [p for p in partners if p.entity_type == "PERSON" and " " in (p.display_name or "")]
    for person in people[:4]:
        fake = SimpleNamespace(
            canonical_key=f"name:{person.display_name.strip().casefold()}",
            display_name=person.display_name.strip(),
            entity_type="PERSON",
            identifiers=[],
        )
        try:
            found = socio.collect(fake, SimpleNamespace(investigation=SimpleNamespace(id="consult"), settings=settings))
        except Exception:
            continue
        person_id = f"person-{person.display_name.casefold()}"
        if person_id not in {n.id for n in nodes}:
            nodes.append(GraphNode(person_id, person.display_name, "person", "sócio"))
        for entity in found.entities:
            if entity.entity_type != "ORG":
                continue
            cnpj = only_digits(entity.value)
            if not validate_cnpj(cnpj) or cnpj in seen:
                continue
            seen.add(cnpj)
            nid = f"cnpj-{cnpj}"
            nodes.append(GraphNode(nid, entity.display_name, "org", _format_cnpj(cnpj)))
            edges.append(GraphEdge(person_id, nid, "também sócio"))
            hits.append(
                ConsultHit(
                    entity.display_name,
                    f"Outra empresa de {person.display_name}",
                    f"https://minhareceita.org/{cnpj}",
                    "relacionada",
                )
            )
            if len(seen) > 10:
                return hits, nodes, edges
    return hits, nodes, edges


def _safe_web_search(settings: Settings, query: str, origin_key: str) -> list[ConsultHit]:
    if not settings.web_search_enable:
        return []
    if not (settings.brave_search_api_key or (settings.google_cse_api_key and settings.google_cse_cx)):
        return []
    try:
        conn = WebSearchConnector(settings)
        if settings.brave_search_api_key:
            parsed = conn._brave(query, origin_key)
        else:
            parsed = conn._google(query, origin_key)
    except Exception:
        return []
    hits = [
        ConsultHit(e.display_name, str((e.attrs or {}).get("snippet") or ""), e.value, "mencao")
        for e in parsed.entities
        if e.entity_type == "PUBLICATION"
    ]
    if not hits and parsed.evidence:
        hits = [ConsultHit(ev.source_label, ev.snippet or "", ev.url, "mencao") for ev in parsed.evidence[:8]]
    return hits


def _safe_gravatar(email: str) -> ConsultHit | None:
    digest = hashlib.md5(email.encode("utf-8"), usedforsecurity=False).hexdigest()
    avatar = f"https://www.gravatar.com/avatar/{digest}?d=404"
    profile = f"https://gravatar.com/{digest}"
    try:
        from osint4all.http_client import RateLimitedClient

        http = RateLimitedClient(source="gravatar", max_concurrency=1, timeout=8.0, default_headers={"User-Agent": "osint4all/0.1"})
        resp = http.request("GET", avatar, allow_404=True, max_retries=1)
        if resp.status_code == 200:
            return ConsultHit("Gravatar ativo", "Avatar público ligado a este e-mail", profile, "perfil")
    except Exception:
        return None
    return None


def _sort_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    def key(ev: TimelineEvent) -> str:
        when = (ev.when or "").strip()
        if when in {"n/d", "", "QSA", "oficial", "histórico"}:
            return "9999"
        return when

    dated = [e for e in events if key(e) != "9999"]
    other = [e for e in events if key(e) == "9999"]
    dated.sort(key=key)
    return dated + other


# re-export for tests that imported parse helpers via web_search
__all__ = [
    "MODES",
    "KIND_LABELS",
    "ConsultHit",
    "ConsultResult",
    "TimelineEvent",
    "ConsultGraph",
    "run_consult",
    "resolve_kind",
    "result_to_save_payload",
]
