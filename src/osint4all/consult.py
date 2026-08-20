"""Consultas rápidas — sem abrir um caso. Só fontes públicas."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from osint4all.config import Settings, get_settings
from osint4all.connectors.cnpj_receita import CnpjReceitaConnector, parse_cnpj_payload
from osint4all.connectors.plate_public import (
    _DETRAN_PORTAL,
    describe_plate,
    extract_owner_mentions,
    extract_vehicle_card,
    merge_vehicle_cards,
    parse_plate_enrichment,
)
from osint4all.connectors.datajud import DatajudConnector
from osint4all.connectors.djen import DjenConnector
from osint4all.connectors.socio_search import SocioSearchConnector
from osint4all.connectors.transparencia import TransparenciaConnector
from osint4all.connectors.username_public import UsernamePublicConnector
from osint4all.connectors.web_search import WebSearchConnector, web_search_ready
from osint4all.identifiers import detect_kind, parse_seed
from osint4all.security import only_digits
from osint4all.validators import format_plate, looks_like_plate, normalize_cnj, validate_cnpj, validate_cpf


# key, label, tip, placeholder
MODES = (
    ("auto", "Detectar", "Reconhece placa, CNPJ, CPF, e-mail, telefone, @user, processo ou nome.", "ABC1D23, @user, e-mail, CPF…"),
    ("PLATE", "Placa", "Série, portais oficiais e menções públicas do veículo/dono. Sem DETRAN de cadastro.", "ABC1D23 ou ABC-1234"),
    ("USERNAME", "Rede social", "URLs públicas (GitHub, X, Telegram…). Sem login.", "@usuario"),
    ("PHONE", "Telefone", "DDD, cidade e menções públicas. Sem operadora.", "11 99999-0000"),
    ("NAME", "Sócio / nome", "Empresas do quadro societário na base aberta da Receita.", "Nome e sobrenome"),
    ("PROCESSOS", "Processos", "Nome, CPF, CNPJ ou número CNJ. DataJud, DJEN, PJe e menções públicas. Sem tribunal fechado.", "nome ou 0000123-45.2024.8.26.0100"),
    ("CNPJ", "CNPJ", "Ficha, QSA e mapa de empresas relacionadas (sócios PJ e outras firmas dos sócios).", "00.000.000/0001-00"),
    ("CPF", "CPF", "Valida, cruza QSA público, sanções e menções. A Receita não devolve o nome por API.", "000.000.000-00"),
    ("EMAIL", "E-mail", "Local-part, Keybase, Gravatar e redes públicas. Sem caixa nem leak.", "nome@dominio.com"),
    ("NEGATIVA", "Negativa", "CEIS, CNEP, TCU, CVM, TSE e menções de condenação em fonte oficial.", "Nome, CPF ou CNPJ"),
    ("IMOVEL", "Imóvel", "Leilão Caixa, SNCR, DOU. Sem matrícula de cartório nem IPTU autenticado.", "Nome, CPF, CNPJ ou endereço"),
    ("DIARIO", "Diário", "DOU, Imprensa Nacional, DJEN e diários estaduais públicos.", "Nome, CPF, CNPJ ou termo"),
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
    "CNJ": "Processos",
    "PROCESSOS": "Processos",
    "NEGATIVA": "Negativa",
    "IMOVEL": "Imóvel",
    "DIARIO": "Diário oficial",
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


def _consult_stamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _year_of(value: str) -> str:
    match = re.search(r"(19|20)\d{2}", value or "")
    return match.group(0) if match else ""


def _org_card_facts(attrs: dict[str, Any] | None, *, consulted_at: str = "") -> list[tuple[str, str]]:
    data = attrs or {}
    pairs: list[tuple[str, str]] = []
    if consulted_at:
        pairs.append(("data da consulta", consulted_at))
    abertura = str(data.get("data_inicio") or "").strip()
    if abertura:
        pairs.append(("abertura", abertura))
        year = _year_of(abertura)
        if year:
            pairs.append(("ano de abertura", year))
    skip = {label for label, _ in pairs}
    mapping = (
        ("capital social", "capital_social"),
        ("e-mail de contato", "email"),
        ("telefone", "telefone"),
        ("situação", "situacao"),
        ("CNAE", "cnae"),
        ("porte", "porte"),
        ("natureza", "natureza_juridica"),
        ("endereço", "endereco"),
        ("razão social", "razao_social"),
    )
    for label, key in mapping:
        value = str(data.get(key) or "").strip()
        if value and label not in skip:
            pairs.append((label, value))
            skip.add(label)
    city = str(data.get("municipio") or "").strip()
    uf = str(data.get("uf") or "").strip()
    if city or uf:
        pairs.append(("município", f"{city} / {uf}".strip(" /")))
    return pairs


def ficha_from_cnpj_result(parsed: Any, *, consulted_at: str = "") -> dict[str, Any]:
    org = next((e for e in parsed.entities if e.kind == "CNPJ"), None)
    org_digits = only_digits(org.value) if org else ""
    partners = [e for e in parsed.entities if not (e.kind == "CNPJ" and only_digits(e.value) == org_digits)]
    attrs = (org.attrs if org else {}) or {}
    stamp = consulted_at or _consult_stamp()
    facts = _org_card_facts(attrs, consulted_at=stamp)
    if org:
        facts.insert(1, ("CNPJ", _format_cnpj(org.value)))
    socios = [
        " · ".join(
            bit
            for bit in (
                e.display_name,
                str((e.attrs or {}).get("papel") or e.kind),
                _format_cnpj(e.value) if e.kind == "CNPJ" else "",
            )
            if bit
        )
        for e in partners
    ]
    participacoes = [e.display_name for e in partners if e.kind == "CNPJ"]
    if socios:
        facts.append(("sócios / QSA", f"{len(socios)} registro(s)"))
    if participacoes:
        facts.append(("participações (sócio PJ)", f"{len(participacoes)} empresa(s)"))
    return {
        "ok": True,
        "title": (org.display_name if org else "") or str(attrs.get("razao_social") or "empresa"),
        "kind": "empresa",
        "meta": str(attrs.get("situacao") or attrs.get("cnae") or "Ficha pública da Receita."),
        "facts": facts,
        "socios": socios,
        "participacoes": participacoes,
    }


def public_ficha(raw: str, *, mode: str = "auto", settings: Settings | None = None, quick: bool = False) -> dict[str, Any]:
    settings = settings or get_settings()
    text = (raw or "").strip()
    stamp = _consult_stamp()
    if not text:
        return {"ok": False, "title": "", "facts": [], "socios": [], "participacoes": [], "error": "Informe um identificador."}
    forced = (mode or "auto").upper()
    seed = parse_seed(text, forced_kind=None if forced in {"", "AUTO"} else forced)
    kind = seed.kind if seed else forced
    if kind != "CNPJ" or not seed:
        return {
            "ok": True,
            "title": text,
            "kind": "node",
            "facts": [("data da consulta", stamp), ("identificador", text)],
            "socios": [],
            "participacoes": [],
        }
    digits = only_digits(seed.value)
    if not _live_ok(settings, quick):
        return {
            "ok": True,
            "title": _format_cnpj(digits),
            "kind": "empresa",
            "facts": [("data da consulta", stamp), ("CNPJ", _format_cnpj(digits))],
            "socios": [],
            "participacoes": [],
            "meta": "Ficha completa da Receita só ao vivo.",
        }
    try:
        parsed = parse_cnpj_payload(CnpjReceitaConnector(settings)._fetch(digits))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "title": _format_cnpj(digits),
            "facts": [("data da consulta", stamp), ("CNPJ", _format_cnpj(digits))],
            "socios": [],
            "participacoes": [],
            "error": str(exc),
        }
    return ficha_from_cnpj_result(parsed, consulted_at=stamp)


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str = "org"
    meta: str = ""
    facts: list[tuple[str, str]] = field(default_factory=list)
    socios: list[str] = field(default_factory=list)
    participacoes: list[str] = field(default_factory=list)


@dataclass
class GraphEdge:
    source: str
    target: str
    label: str = ""
    explain: str = ""


@dataclass
class ConsultGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    caption: str = ""
    consulted_at: str = field(default_factory=_consult_stamp)

    def to_payload(self) -> dict[str, Any]:
        return {
            "caption": self.caption,
            "consulted_at": self.consulted_at,
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "kind": n.kind,
                    "meta": n.meta,
                    "facts": list(n.facts),
                    "socios": list(n.socios),
                    "participacoes": list(n.participacoes),
                }
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "label": e.label, "explain": e.explain} for e in self.edges
            ],
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

    def assignable_pairs(self) -> list[tuple[str, str]]:
        """Nome consultado + CNPJs da árvore/hits, para gravar no caso."""
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []

        def add(kind: str, value: str) -> None:
            kind = (kind or "").upper()
            value = (value or "").strip()
            if not value or kind in {"", "FILE", "MASSA"}:
                return
            key = (kind, value)
            if key in seen:
                return
            seen.add(key)
            out.append(key)

        add(self.kind, self.query)
        if self.graph:
            for node in self.graph.nodes:
                digits = only_digits(getattr(node, "meta", "") or "")
                if validate_cnpj(digits):
                    add("CNPJ", digits)
        for hit in self.hits:
            if hit.kind not in {"empresa", "cnpj", "org"}:
                continue
            digits = only_digits(hit.meta or "")
            if validate_cnpj(digits):
                add("CNPJ", digits)
                continue
            url = (hit.url or "").rstrip("/")
            tail = only_digits(url.rsplit("/", 1)[-1]) if url else ""
            if validate_cnpj(tail):
                add("CNPJ", tail)
        return out


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
    forced = (mode or "").upper()
    if forced == "PROCESSOS":
        return _consult_processos(text, settings, quick=quick)
    if forced == "NEGATIVA":
        return _consult_negativa(text, settings, quick=quick)
    if forced == "IMOVEL":
        return _consult_imovel(text, settings, quick=quick)
    if forced == "DIARIO":
        return _consult_diario(text, settings, quick=quick)
    kind = resolve_kind(mode, text)
    if not kind:
        return ConsultResult(kind="", query=text, title="", summary="", ok=False, error="Não reconheci esse valor. Escolha o tipo à esquerda.")
    try:
        if kind == "PLATE":
            return _consult_plate(text, settings, quick=quick)
        if kind == "USERNAME":
            return _consult_username(text, settings, quick=quick)
        if kind == "PHONE":
            return _consult_phone(text, settings, quick=quick)
        if kind == "CNPJ":
            return _consult_cnpj(text, settings, quick=quick)
        if kind == "CPF":
            return _consult_cpf(text, settings, quick=quick)
        if kind == "EMAIL":
            return _consult_email(text, settings, quick=quick)
        if kind == "NAME":
            return _consult_name(text, settings, quick=quick)
        if kind == "CNJ":
            return _consult_processos(text, settings, quick=quick)
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
    notes = [
        "Modelo, cor e ano vêm de menção pública (leilão, diário, classificado, notícia). Não há API aberta do DETRAN só com a placa.",
        "O cadastro de dono oficial exige Renavam + gov.br.",
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
    vehicle = {}
    if _live_ok(settings, quick):
        vehicle, owners, web = _lookup_plate_vehicle(settings, compact, pretty)
        hits.extend(web[:10])
        for ev in web[:8]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção web", kind="web"))

    facts = [
        ("Modelo", vehicle.get("modelo") or vehicle.get("label") or "não citado em fonte pública nesta busca"),
        ("Marca", vehicle.get("marca") or "—"),
        ("Ano", vehicle.get("ano") or "—"),
        ("Cor", vehicle.get("cor") or "—"),
        ("Padrão", info["padrao"]),
        ("Série (1º emplacamento)", f"{uf} · {uf_name}" if uf else "—"),
        ("Placa compacta", compact),
        ("Mercosul", "sim" if compact[4:5].isalpha() else "não (cinza)"),
    ]
    models = [vehicle["label"]] if vehicle.get("label") else []
    if models:
        timeline.insert(
            1,
            TimelineEvent("Veículo citado", vehicle["label"], when="menção pública", kind="vehicle"),
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
        caption="Árvore da placa: série histórica no centro. Modelo e possível dono só entram se o texto público citar explicitamente.",
    )
    for idx, name in enumerate(owners):
        nid = f"owner-{idx}"
        graph.nodes.append(GraphNode(nid, name, "person", "citado em texto público"))
        graph.edges.append(
            GraphEdge(nid, "plate", "possível dono", "Nome extraído de menção pública — não é o cadastro do DETRAN.")
        )
    for idx, model in enumerate(models):
        nid = f"model-{idx}"
        graph.nodes.append(GraphNode(nid, model, "vehicle", "modelo citado na web"))
        graph.edges.append(GraphEdge("plate", nid, "modelo", "Marca/modelo encontrados no mesmo trecho que a placa."))

    return ConsultResult(
        kind="PLATE",
        query=pretty,
        title=pretty,
        summary=(
            (f"{vehicle['label']}. " if vehicle.get("label") else "Modelo não apareceu em fonte pública. ")
            + f"{info['padrao']}. {info['serie_nota']}"
            + (f" Dono em menção pública: {owners[0]}." if owners else "")
        ),
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph if len(graph.nodes) > 1 else None,
    )


def _consult_username(raw: str, settings: Settings, *, quick: bool = False, core_only: bool | None = None) -> ConsultResult:
    user = raw.strip().lstrip("@").lower()
    conn = UsernamePublicConnector(settings)
    hits: list[ConsultHit] = []
    if _live_ok(settings, quick) and settings.username_public_enable:
        fake = SimpleNamespace(canonical_key=f"username:{user}", display_name=user, entity_type="PROFILE", identifiers=[])
        result = conn.collect(fake, SimpleNamespace(core_only=quick if core_only is None else core_only))
        hits = [ConsultHit(e.display_name, e.value, e.value, "perfil") for e in result.entities]
    timeline = [
        TimelineEvent(h.title, h.meta, h.url, when="perfil ativo", kind="social")
        for h in hits
    ]
    graph = ConsultGraph(
        nodes=[GraphNode("user", f"@{user}", "profile", "username consultado")],
        edges=[],
        caption="Árvore do @user: cada caixa é uma URL canônica pública que respondeu HTTP 200. Ausência não prova que a conta não existe.",
    )
    for idx, hit in enumerate(hits):
        nid = f"net-{idx}"
        graph.nodes.append(GraphNode(nid, hit.title, "profile", hit.meta or "HTTP 200"))
        graph.edges.append(
            GraphEdge("user", nid, "perfil público", f"GET em URL canônica de {hit.title} devolveu HTTP 200.")
        )
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


def _consult_phone(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    from osint4all.connectors.phone_public import describe_phone, facts_from_phone

    settings = settings or get_settings()
    digits = only_digits(raw)
    if len(digits) < 10:
        return ConsultResult(kind="PHONE", query=raw, title=raw, summary="", ok=False, error="Telefone curto demais.")
    info = describe_phone(digits)
    wa = f"https://wa.me/{digits}" if digits.startswith("55") or len(digits) >= 12 else f"https://wa.me/55{digits}"
    hits = [
        ConsultHit("WhatsApp (link público)", "Abre conversa se o número existir no app", wa, "link"),
        ConsultHit("Truecaller web", "Busca pública de menção — sem login", f"https://www.truecaller.com/search/br/{digits}", "link"),
    ]
    notes = [
        "DDD e cidade vêm da tabela pública da ANATEL (estilo PhoneInfoga). Sem operadora, sem IMEI, sem cadastro de assinante.",
        "Use só números que já apareceram em fonte pública. Guardar no grafo liga o telefone a um caso.",
    ]
    if _live_ok(settings, quick):
        quoted = info.get("digits") or digits
        hits.extend(_safe_web_search(settings, f'"{quoted}" telefone OR whatsapp', f"phone:{quoted}")[:5])
    place = " / ".join(part for part in (info.get("cidade"), info.get("uf")) if part)
    summary = (
        f"Número normalizado. {info.get('tipo') or 'tipo indefinido'}"
        + (f" · DDD {info['ddd']} ({place})" if info.get("ddd") and place else ".")
        + " Sem operadora."
    )
    return ConsultResult(
        kind="PHONE",
        query=digits,
        title=digits,
        summary=summary,
        facts=facts_from_phone(info),
        hits=hits,
        notes=notes,
    )


def _consult_cnpj(raw: str, settings: Settings, *, quick: bool = False) -> ConsultResult:
    if not validate_cnpj(raw):
        return ConsultResult(kind="CNPJ", query=raw, title=raw, summary="", ok=False, error="CNPJ inválido.")
    digits = only_digits(raw)
    if not _live_ok(settings, quick):
        formatted = _format_cnpj(digits)
        return ConsultResult(
            kind="CNPJ",
            query=digits,
            title=formatted,
            summary="CNPJ válido. A ficha, o QSA e o mapa de relacionadas vêm da Minha Receita / BrasilAPI ao consultar ao vivo.",
            facts=[("CNPJ", formatted)],
            hits=[ConsultHit("Minha Receita", "Ficha oficial", f"https://minhareceita.org/{digits}", "fonte")],
            notes=["Fora de teste, esta consulta puxa razão social, sócios e empresas ligadas."],
        )
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
    graph = _graph_from_cnpj(
        digits,
        str(attrs.get("razao_social") or org.display_name if org else digits),
        partners,
        attrs,
    )
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
    graph = ConsultGraph(
        nodes=[GraphNode("cpf", masked, "person", formatted)],
        edges=[],
        caption="Árvore do CPF: o documento no topo; abaixo, empresas do quadro societário público (Receita / Casa dos Dados).",
    )
    notes = [
        "A Receita não publica o nome pelo CPF em API aberta. O que aparece abaixo veio de bases públicas (QSA, sanções, menções).",
    ]

    companies = 0
    sanctions = 0
    if _live_ok(settings, quick):
        try:
            socio = SocioSearchConnector(settings).collect_by_cpf(digits, origin)
            notes.extend(note for note in socio.notes if note not in notes)
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
                graph.nodes.append(
                    GraphNode(
                        nid,
                        entity.display_name,
                        "org",
                        cnpj or "CNPJ",
                        facts=_org_card_facts(entity.attrs, consulted_at=graph.consulted_at),
                    )
                )
                graph.edges.append(
                    GraphEdge("cpf", nid, "sócio no QSA", "Este CPF aparece no quadro societário público desta empresa.")
                )
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
    graph = ConsultGraph(
        nodes=[GraphNode("email", email, "email", f"domínio {domain}")],
        edges=[],
        caption="Árvore do e-mail: o endereço no topo; o @user vem do local-part; cada rede é uma URL pública com HTTP 200. Sem caixa e sem vazamento.",
    )
    graph.nodes.append(GraphNode("user", f"@{local}", "profile", "local-part usado como username"))
    graph.edges.append(
        GraphEdge("email", "user", "deriva @user", "A parte antes do @ foi testada como identificador em redes públicas.")
    )

    gravatar_url = f"https://www.gravatar.com/{hashlib.md5(email.encode('utf-8'), usedforsecurity=False).hexdigest()}"
    hits.append(ConsultHit("Gravatar (hash público)", "Perfil se o dono cadastrou foto/bio", gravatar_url, "perfil"))
    hits.append(ConsultHit("Keybase lookup", "Conta pública ligada a este e-mail, se existir", f"https://keybase.io/_/api/1.0/user/lookup.json?email={quote(email)}", "link"))

    profiles = 0
    if _live_ok(settings, quick) and settings.username_public_enable:
        try:
            social = _consult_username(local, settings, quick=quick, core_only=True)
            for hit in social.hits:
                profiles += 1
                hits.append(hit)
                timeline.append(TimelineEvent(hit.title, hit.meta or "HTTP 200", hit.url, when="perfil ativo", kind="social"))
                nid = f"social-{profiles}"
                graph.nodes.append(GraphNode(nid, hit.title, "profile", hit.meta or "HTTP 200"))
                graph.edges.append(
                    GraphEdge("user", nid, "perfil público", f"URL canônica de {hit.title} respondeu HTTP 200 para @{local}.")
                )
        except Exception:
            pass
        gravatar = _safe_gravatar(email)
        if gravatar:
            hits.insert(1, gravatar)
            timeline.insert(1, TimelineEvent(gravatar.title, gravatar.meta, gravatar.url, when="identidade", kind="social"))
            graph.nodes.append(GraphNode("gravatar", "Gravatar", "profile", gravatar.meta or "avatar público"))
            graph.edges.append(
                GraphEdge("email", "gravatar", "identidade", "O hash MD5 do e-mail tem avatar público no Gravatar.")
            )
        web = _safe_web_search(settings, f'"{email}"', f"email:{email}")
        hits.extend(web[:6])
        for ev in web[:5]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção web", kind="web"))
        if settings.email_public_enable:
            from osint4all.connectors.email_public import EmailPublicConnector

            fake = SimpleNamespace(
                canonical_key=f"email:{email}",
                display_name=email,
                entity_type="PERSON",
                identifiers=[],
                attrs={"email": email},
            )
            try:
                extra = EmailPublicConnector(settings).collect(fake, SimpleNamespace(investigation=SimpleNamespace(id="consult"), settings=settings))
            except Exception:
                extra = None
            if extra:
                for ev in extra.evidence[:4]:
                    hits.append(ConsultHit(ev.source_label, ev.snippet or "", ev.url, "perfil"))
                    timeline.append(TimelineEvent(ev.source_label, ev.snippet or "", ev.url, when="serviço público", kind="social"))
                    nid = f"svc-{ev.source_label.lower()}"
                    graph.nodes.append(GraphNode(nid, ev.source_label, "profile", ev.snippet or "lookup público"))
                    graph.edges.append(GraphEdge("email", nid, "serviço público", ev.snippet or "Keybase/Gravatar"))

    facts.append(("Perfis públicos", str(profiles)))
    notes = [
        "Keybase e Gravatar são lookup público (estilo Holehe). Não acessamos caixa, HIBP nem lista de contas vazadas.",
        "A linha do tempo junta o @user derivado do e-mail, serviços públicos e URLs que responderam 200.",
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


def _consult_name(raw: str, settings: Settings, *, quick: bool = False) -> ConsultResult:
    if " " not in raw.strip():
        return ConsultResult(kind="NAME", query=raw, title=raw, summary="", ok=False, error="Use nome e sobrenome.")
    if not _live_ok(settings, quick):
        return ConsultResult(
            kind="NAME",
            query=raw.strip(),
            title=raw.strip(),
            summary="Nome reconhecido. O cruzamento com o QSA público roda ao vivo.",
            facts=[("Nome", raw.strip())],
            notes=["Fora de teste, busca empresas em que este nome aparece no quadro societário aberto."],
        )
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
    stamp = _consult_stamp()
    participacoes = [e.display_name for e in orgs]
    graph = ConsultGraph(
        nodes=[
            GraphNode(
                "person",
                raw.strip(),
                "person",
                "nome consultado",
                facts=[("data da consulta", stamp), ("participações", f"{len(orgs)} empresa(s)")],
                participacoes=participacoes,
            )
        ],
        edges=[],
        caption="Árvore do sócio: o nome no topo; abaixo, empresas em que esse nome aparece no QSA público.",
        consulted_at=stamp,
    )
    for idx, org in enumerate(orgs):
        nid = f"org-{idx}"
        graph.nodes.append(
            GraphNode(
                nid,
                org.display_name,
                "org",
                only_digits(org.value),
                facts=_org_card_facts(org.attrs, consulted_at=stamp),
                participacoes=[org.display_name],
            )
        )
        graph.edges.append(
            GraphEdge("person", nid, "sócio no QSA", "Nome encontrado no quadro societário público desta empresa.")
        )
    hits.append(
        ConsultHit(
            "Aleph / OCCRP",
            "Pessoas e documentos em datasets investigativos públicos",
            f"https://aleph.occrp.org/search?q={quote(raw.strip())}",
            "fonte",
        )
    )
    if settings.aleph_public_enable:
        from osint4all.connectors.aleph_public import AlephPublicConnector

        try:
            aleph = AlephPublicConnector(settings).collect(
                fake, SimpleNamespace(investigation=SimpleNamespace(id="consult"), settings=settings)
            )
        except Exception:
            aleph = None
        if aleph:
            for ev in aleph.evidence[:5]:
                hits.append(ConsultHit(ev.source_label, ev.snippet or "", ev.url, "mencao"))
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


_CNJ_SEGMENTO = {
    "1": "STF",
    "2": "CNJ",
    "3": "STJ",
    "4": "Justiça Federal",
    "5": "Justiça do Trabalho",
    "6": "Justiça Eleitoral",
    "7": "Justiça Militar",
    "8": "Justiça Estadual",
    "9": "Justiça Militar estadual",
}


def _query_subject(raw: str) -> tuple[str, str, str]:
    text = (raw or "").strip()
    parts = normalize_cnj(text)
    if parts:
        return "CNJ", parts.numero_formatado, f"cnj:{parts.numero_digits}"
    if validate_cnpj(text):
        digits = only_digits(text)
        return "CNPJ", _format_cnpj(digits), f"cnpj:{digits}"
    if validate_cpf(text):
        digits = only_digits(text)
        return "CPF", f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}", f"cpf:{digits}"
    collapsed = re.sub(r"\s+", " ", text)
    return "NAME", collapsed, f"name:{collapsed.casefold()}"


def _extend_unique(hits: list[ConsultHit], extra: list[ConsultHit], *, limit: int = 12) -> None:
    seen = {(h.url or h.title) for h in hits}
    for hit in extra[:limit]:
        key = hit.url or hit.title
        if key in seen:
            continue
        seen.add(key)
        hits.append(hit)


def _hits_from_connector(parsed: Any, *, hit_kind: str, when: str) -> tuple[list[ConsultHit], list[TimelineEvent], list[tuple[str, str]]]:
    hits: list[ConsultHit] = []
    timeline: list[TimelineEvent] = []
    facts: list[tuple[str, str]] = []
    if not parsed:
        return hits, timeline, facts
    for ev in list(getattr(parsed, "evidence", None) or [])[:12]:
        hits.append(ConsultHit(ev.source_label, ev.snippet or "", ev.url, hit_kind))
        timeline.append(TimelineEvent(ev.source_label, ev.snippet or "", ev.url, when=when, kind=hit_kind))
    for entity in list(getattr(parsed, "entities", None) or []):
        if entity.kind == "CNJ":
            facts.append(("Processo", entity.display_name))
        elif entity.kind == "NAME" and entity.display_name:
            facts.append((str((entity.attrs or {}).get("polo") or entity.entity_type or "Nome"), entity.display_name))
    return hits, timeline, facts


def _try_datajud(settings: Settings, origin: str, display: str) -> Any | None:
    if not (settings.datajud_enable and settings.datajud_api_key):
        return None
    digits = origin.split(":", 1)[-1]
    fake = SimpleNamespace(
        canonical_key=origin,
        display_name=display,
        entity_type="CASE",
        identifiers=[SimpleNamespace(kind="CNJ", value=digits)],
    )
    try:
        return DatajudConnector(settings).collect(fake, SimpleNamespace())
    except Exception:
        return None


def _try_djen(settings: Settings, origin: str, display: str, entity_type: str) -> Any | None:
    if not settings.djen_enable:
        return None
    fake = SimpleNamespace(
        canonical_key=origin,
        display_name=display,
        entity_type=entity_type,
        identifiers=[],
    )
    try:
        return DjenConnector(settings).collect(fake, SimpleNamespace())
    except Exception:
        return None


def _try_transparencia(settings: Settings, origin: str, display: str, id_kind: str) -> Any | None:
    if id_kind not in {"CPF", "CNPJ"}:
        return None
    if not (settings.transparencia_enable and settings.transparencia_api_key):
        return None
    digits = origin.split(":", 1)[-1]
    fake = SimpleNamespace(
        canonical_key=origin,
        display_name=display,
        entity_type="ORG" if id_kind == "CNPJ" else "PERSON",
        identifiers=[SimpleNamespace(kind=id_kind, value=digits)],
    )
    try:
        return TransparenciaConnector(settings).collect(fake, SimpleNamespace())
    except Exception:
        return None


def _consult_processos(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    settings = settings or get_settings()
    id_kind, display, origin = _query_subject(raw)
    result_kind = "CNJ" if id_kind == "CNJ" else "PROCESSOS"
    hits = [
        ConsultHit("DJEN / Comunica", "Diário de Justiça eletrônico e comunicações", "https://comunica.pje.jus.br/", "fonte"),
        ConsultHit("Consulta processual CNJ", "Painel público unificado (PJe)", "https://www.cnj.jus.br/plataforma-digital-do-poder-judiciario-pdpj/", "fonte"),
        ConsultHit("DataJud (wiki da chave)", "API pública de capa e partes — exige chave do CNJ", "https://datajud-wiki.cnj.jus.br/api-publica/acesso/", "fonte"),
    ]
    facts: list[tuple[str, str]] = [("Consulta", display), ("Tipo do valor", KIND_LABELS.get(id_kind, id_kind))]
    notes = [
        "Capa, polo e andamento oficiais só saem de DataJud/DJEN ou do tribunal. Sem login em PJe fechado.",
        "Nome sozinho não prova que a parte é a mesma pessoa.",
    ]
    timeline = [TimelineEvent("Portais oficiais", "DJEN, PJe e DataJud — ficha interna, sem sair do painel", when="fonte", kind="fonte")]
    graph = ConsultGraph(
        nodes=[GraphNode("q", display, "org" if id_kind in {"CNPJ", "CNJ"} else "person", result_kind)],
        edges=[],
        caption="Árvore processual: o valor consultado no topo; abaixo, comunicações DJEN e capas DataJud quando a API responde.",
    )
    if id_kind == "CNJ":
        parts = normalize_cnj(raw)
        if parts:
            facts.append(("Número CNJ", parts.numero_formatado))
            facts.append(("Ano", parts.ano))
            facts.append(("Segmento", _CNJ_SEGMENTO.get(parts.segmento, parts.segmento)))
            facts.append(("Tribunal", parts.tribunal))
            timeline.append(TimelineEvent(parts.numero_formatado, f"Segmento {parts.segmento} · tribunal {parts.tribunal}", when="CNJ", kind="id"))

    found = 0
    if _live_ok(settings, quick):
        if id_kind == "CNJ":
            parsed = _try_datajud(settings, origin, display)
            extra, events, extra_facts = _hits_from_connector(parsed, hit_kind="processo", when="DataJud")
            _extend_unique(hits, extra)
            timeline.extend(events)
            facts.extend(extra_facts[:8])
            found += len(extra)
            for entity in list(getattr(parsed, "entities", None) or []):
                if entity.entity_type == "PERSON" and entity.display_name:
                    nid = f"parte-{entity.display_name.casefold()}"
                    if nid not in {n.id for n in graph.nodes}:
                        graph.nodes.append(GraphNode(nid, entity.display_name, "person", str(entity.attrs.get("polo") or "parte")))
                        graph.edges.append(GraphEdge("q", nid, "parte", "Nome extraído da capa DataJud."))
        entity_type = "CASE" if id_kind == "CNJ" else ("ORG" if id_kind == "CNPJ" else "PERSON")
        parsed = _try_djen(settings, origin, display, entity_type)
        extra, events, extra_facts = _hits_from_connector(parsed, hit_kind="processo", when="DJEN")
        _extend_unique(hits, extra)
        timeline.extend(events)
        facts.extend(extra_facts[:8])
        found += len(extra)
        for entity in list(getattr(parsed, "entities", None) or []):
            if entity.kind == "CNJ":
                nid = f"cnj-{only_digits(entity.value)}"
                if nid not in {n.id for n in graph.nodes}:
                    graph.nodes.append(GraphNode(nid, entity.display_name, "org", "processo"))
                    graph.edges.append(GraphEdge("q", nid, "mencionado", "Número CNJ citado no DJEN."))
        quoted = f'"{display}"'
        web = _safe_web_search(
            settings,
            f"{quoted} (processo OR reclamatória OR \"número CNJ\" OR ação OR sentença) (site:jus.br OR site:pje.jus.br OR site:cnj.jus.br OR site:in.gov.br)",
            origin,
        )
        _extend_unique(hits, web, limit=8)
        for ev in web[:6]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção web", kind="web"))
            found += 1

    if found:
        summary = f"{found} menção(ões) processual(is) pública(s) para {display}."
    elif not _live_ok(settings, quick):
        summary = "Consulta processual reconhecida. DataJud, DJEN e menções em jus.br rodam ao vivo."
        notes.append("Fora de teste, busca comunicações no DJEN e capa no DataJud (se a chave do CNJ estiver configurada).")
    else:
        summary = "Nenhuma comunicação ou capa nesta rodada. Use os portais oficiais na ficha."
    return ConsultResult(
        kind=result_kind,
        query=display,
        title=display,
        summary=summary,
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph,
    )


def _consult_negativa(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    settings = settings or get_settings()
    id_kind, display, origin = _query_subject(raw)
    termo = only_digits(raw) if id_kind in {"CPF", "CNPJ"} else display
    hits = [
        ConsultHit("CEIS — empresas inidôneas", "Cadastro de Empresas Inidôneas e Suspensas", "https://portaldatransparencia.gov.br/sancoes/consulta?cadastro=1", "fonte"),
        ConsultHit("CNEP — punições a pessoas jurídicas", "Cadastro Nacional de Empresas Punidas", "https://portaldatransparencia.gov.br/sancoes/consulta?cadastro=2", "fonte"),
        ConsultHit("Portal da Transparência", "Busca nas listas oficiais da CGU", f"https://portaldatransparencia.gov.br/busca?termo={termo}", "fonte"),
        ConsultHit("TCU — inabilitados e inidôneos", "Lista pública do Tribunal de Contas da União", "https://contas.tcu.gov.br/ords/f?p=1660:3", "fonte"),
        ConsultHit("CVM — alertas e processos", "Regulados e punições da Comissão de Valores Mobiliários", "https://www.gov.br/cvm/pt-br/assuntos/protecao/alertas", "fonte"),
        ConsultHit("TSE — divulgação de candidaturas", "Contas e condicionalidades eleitorais públicas", "https://divulgacandcontas.tse.jus.br/", "fonte"),
    ]
    facts = [("Consulta", display), ("Documento", KIND_LABELS.get(id_kind, id_kind))]
    notes = [
        "Sanção oficial só vale se o documento (CPF/CNPJ) bater na lista. Nome sozinho é menção.",
        "Não consulta certidão de antecedentes nem base policial fechada.",
    ]
    timeline = [TimelineEvent("Listas oficiais", "CEIS, CNEP, TCU, CVM e TSE — só o que é público", when="fonte", kind="fonte")]
    graph = ConsultGraph(
        nodes=[GraphNode("q", display, "org" if id_kind == "CNPJ" else "person", "negativa")],
        edges=[],
        caption="Árvore de negativa: o alvo no topo; abaixo, registros CEIS/CNEP ou menções oficiais de condenação.",
    )
    found = 0
    if _live_ok(settings, quick):
        parsed = _try_transparencia(settings, origin, display, id_kind)
        extra, events, extra_facts = _hits_from_connector(parsed, hit_kind="sancao", when="CEIS/CNEP")
        _extend_unique(hits, extra)
        timeline.extend(events)
        facts.extend(extra_facts[:6])
        found += len(extra)
        for ev in extra:
            nid = f"s-{len(graph.nodes)}"
            graph.nodes.append(GraphNode(nid, ev.title, "org", "sanção"))
            graph.edges.append(GraphEdge("q", nid, "lista oficial", "Registro em CEIS, CNEP ou lista da Transparência."))
        quoted = f'"{display}"'
        web = _safe_web_search(
            settings,
            f"{quoted} (condenação OR condenado OR CEIS OR CNEP OR inidoneidade OR improbidade OR inelegível OR \"pena de\" OR TCU) (site:gov.br OR site:tcu.gov.br OR site:tse.jus.br OR site:in.gov.br)",
            origin,
        )
        _extend_unique(hits, web, limit=8)
        for ev in web[:6]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção oficial", kind="alert"))
            found += 1
    facts.append(("Registros ao vivo", str(found)))
    if found:
        summary = f"{found} registro(s) ou menção(ões) negativa(s) pública(s) para {display}."
    elif not _live_ok(settings, quick):
        summary = "Listas oficiais apontadas. CEIS/CNEP e menções em gov.br rodam ao vivo (chave da Transparência, se houver)."
        notes.append("Com TRANSPARENCIA_API_KEY e CPF/CNPJ, a consulta pergunta CEIS e CNEP direto.")
    else:
        summary = "Nada nas listas desta rodada. Abra CEIS, CNEP, TCU ou TSE na ficha."
    return ConsultResult(
        kind="NEGATIVA",
        query=display,
        title=display,
        summary=summary,
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph,
    )


def _consult_imovel(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    settings = settings or get_settings()
    id_kind, display, origin = _query_subject(raw)
    hits = [
        ConsultHit("Caixa — leilão de imóveis", "Oferta pública de imóveis da Caixa", "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp", "fonte"),
        ConsultHit("SNCR / Incra", "Consulta pública do cadastro rural", "https://sncr.serpro.gov.br/sncr-web/consultaPublica.jsf", "fonte"),
        ConsultHit("SIGEF", "Parcelário rural georreferenciado (Incra)", "https://sigef.incra.gov.br/", "fonte"),
        ConsultHit("DOU — Imprensa Nacional", "Editais de hasta, desapropriação e averbação publicados", "https://www.in.gov.br/consulta", "fonte"),
    ]
    facts = [("Consulta", display), ("Tipo do valor", KIND_LABELS.get(id_kind, id_kind))]
    notes = [
        "Não há API aberta de matrícula de cartório nem IPTU autenticado. O que aparece é menção pública (leilão, DOU, SNCR).",
        "Endereço ou nome em edital não prova propriedade.",
    ]
    timeline = [TimelineEvent("Portais de imóvel público", "Caixa, SNCR, SIGEF e DOU", when="fonte", kind="fonte")]
    graph = ConsultGraph(
        nodes=[GraphNode("q", display, "org" if id_kind == "CNPJ" else "person", "imóvel")],
        edges=[],
        caption="Árvore de imóvel: o alvo no topo; abaixo, leilões Caixa, cadastro rural e menções no DOU.",
    )
    found = 0
    if _live_ok(settings, quick):
        quoted = f'"{display}"'
        web = _safe_web_search(
            settings,
            f"{quoted} (imóvel OR imóvel OR matrícula OR leilão OR \"hasta pública\" OR IPTU OR SNCR OR SIGEF OR \"registro de imóveis\") (site:gov.br OR site:caixa.gov.br OR site:in.gov.br OR site:incra.gov.br)",
            origin,
        )
        _extend_unique(hits, web, limit=10)
        for ev in web[:8]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="menção pública", kind="web"))
            nid = f"imv-{len(graph.nodes)}"
            graph.nodes.append(GraphNode(nid, ev.title, "org", "menção"))
            graph.edges.append(GraphEdge("q", nid, "mencionado", "Menção pública a imóvel, leilão ou cadastro rural."))
            found += 1
    if found:
        summary = f"{found} menção(ões) pública(s) de imóvel, leilão ou cadastro rural para {display}."
    elif not _live_ok(settings, quick):
        summary = "Portais de leilão e cadastro rural apontados. Menções no DOU e Caixa rodam ao vivo."
    else:
        summary = "Nenhuma menção pública nesta rodada. Consulte Caixa, SNCR ou o DOU na ficha."
    return ConsultResult(
        kind="IMOVEL",
        query=display,
        title=display,
        summary=summary,
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph,
    )


def _consult_diario(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    settings = settings or get_settings()
    id_kind, display, origin = _query_subject(raw)
    hits = [
        ConsultHit("DOU — consulta", "Diário Oficial da União (Imprensa Nacional)", "https://www.in.gov.br/consulta", "fonte"),
        ConsultHit("Leitura do jornal", "Edições do DOU em texto corrido", "https://www.in.gov.br/leiturajornal", "fonte"),
        ConsultHit("Querido Diário", "Diários municipais e estaduais indexados (OK.br)", "https://querido-diario.ok.org.br/", "fonte"),
        ConsultHit("DJEN / Comunica", "Publicações do Poder Judiciário", "https://comunica.pje.jus.br/", "fonte"),
    ]
    facts = [("Consulta", display), ("Tipo do valor", KIND_LABELS.get(id_kind, id_kind))]
    notes = [
        "Diário oficial publica ato, edital e comunicação. Não substitui certidão do cartório ou do tribunal.",
    ]
    timeline = [TimelineEvent("Diários públicos", "DOU, Querido Diário e DJEN", when="fonte", kind="fonte")]
    graph = ConsultGraph(
        nodes=[GraphNode("q", display, "org" if id_kind in {"CNPJ", "CNJ"} else "person", "diário")],
        edges=[],
        caption="Árvore de diário: o termo no topo; abaixo, publicações do DOU, DJEN e diários locais.",
    )
    found = 0
    if _live_ok(settings, quick):
        entity_type = "CASE" if id_kind == "CNJ" else ("ORG" if id_kind == "CNPJ" else "PERSON")
        parsed = _try_djen(settings, origin, display, entity_type)
        extra, events, extra_facts = _hits_from_connector(parsed, hit_kind="diario", when="DJEN")
        _extend_unique(hits, extra)
        timeline.extend(events)
        facts.extend(extra_facts[:6])
        found += len(extra)
        quoted = f'"{display}"'
        web = _safe_web_search(
            settings,
            f"{quoted} (site:in.gov.br OR \"diário oficial\" OR \"querido diário\" OR DJE OR DJEN OR \"imprensa nacional\")",
            origin,
        )
        _extend_unique(hits, web, limit=8)
        for ev in web[:6]:
            timeline.append(TimelineEvent(ev.title, ev.meta, ev.url, when="diário", kind="web"))
            nid = f"dou-{len(graph.nodes)}"
            graph.nodes.append(GraphNode(nid, ev.title, "org", "publicação"))
            graph.edges.append(GraphEdge("q", nid, "publicado", "Menção em diário oficial ou índice público."))
            found += 1
    if found:
        summary = f"{found} publicação(ões) em diário oficial ou DJEN para {display}."
    elif not _live_ok(settings, quick):
        summary = "DOU, Querido Diário e DJEN apontados. A busca em in.gov.br e comunicações rodam ao vivo."
    else:
        summary = "Nenhuma publicação nesta rodada. Consulte o DOU ou o Querido Diário na ficha."
    return ConsultResult(
        kind="DIARIO",
        query=display,
        title=display,
        summary=summary,
        facts=facts,
        hits=hits,
        notes=notes,
        timeline=timeline,
        graph=graph,
    )


def _consult_cnj(raw: str, settings: Settings | None = None, *, quick: bool = False) -> ConsultResult:
    return _consult_processos(raw, settings, quick=quick)


def result_to_save_payload(result: ConsultResult) -> dict[str, Any]:
    return {"kind": result.kind, "value": result.query}


def _format_cnpj(digits: str) -> str:
    d = only_digits(digits)
    if len(d) != 14:
        return digits
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _graph_from_cnpj(root_digits: str, root_label: str, partners: list[Any], attrs: dict[str, Any] | None = None) -> ConsultGraph:
    stamp = _consult_stamp()
    socios = [
        " · ".join(
            bit
            for bit in (p.display_name, str((p.attrs or {}).get("papel") or p.kind))
            if bit
        )
        for p in partners
    ]
    participacoes = [p.display_name for p in partners if p.kind == "CNPJ"]
    graph = ConsultGraph(
        nodes=[
            GraphNode(
                f"cnpj-{root_digits}",
                root_label,
                "org",
                _format_cnpj(root_digits),
                facts=_org_card_facts(attrs, consulted_at=stamp),
                socios=socios,
                participacoes=participacoes,
            )
        ],
        edges=[],
        caption="Árvore societária: a empresa consultada na raiz; sócios PF/PJ no primeiro nível; outras firmas dos mesmos sócios mais abaixo.",
        consulted_at=stamp,
    )
    for idx, partner in enumerate(partners):
        kind = "org" if partner.kind == "CNPJ" else "person"
        nid = f"p-{idx}-{only_digits(str(partner.value)) or idx}"
        papel = str(partner.attrs.get("papel") or "sócio")
        graph.nodes.append(
            GraphNode(
                nid,
                partner.display_name,
                kind,
                papel,
                facts=[("data da consulta", stamp), ("papel no QSA", papel)],
                participacoes=[root_label],
            )
        )
        graph.edges.append(
            GraphEdge(nid, f"cnpj-{root_digits}", papel, f"{papel} no QSA oficial da Receita (Minha Receita / BrasilAPI).")
        )
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
        edges.append(
            GraphEdge(f"cnpj-{root_digits}", nid, "sócio PJ", "Esta empresa figura como sócia pessoa jurídica no QSA.")
        )
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
            edges.append(
                GraphEdge(person_id, nid, "também sócio", f"{person.display_name} também consta no QSA desta outra empresa.")
            )
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


def _lookup_plate_vehicle(settings: Settings, compact: str, pretty: str) -> tuple[dict[str, str], list[str], list[ConsultHit]]:
    queries = (
        f'"{pretty}" OR "{compact}" (modelo OR marca OR veículo OR carro OR moto OR leilão)',
        f'"{pretty}" placa (Gol OR Onix OR Civic OR Corolla OR HB20 OR Strada OR Polo OR Argo)',
        f'"{compact}" (fipe OR "ano modelo" OR prata OR branco OR preto)',
    )
    web: list[ConsultHit] = []
    seen_urls: set[str] = set()
    cards: list[dict[str, str]] = []
    owners: list[str] = []
    for query in queries:
        for hit in _safe_web_search(settings, query, f"plate:{compact}"):
            if hit.url and hit.url in seen_urls:
                continue
            if hit.url:
                seen_urls.add(hit.url)
            web.append(hit)
            blob = f"{hit.title} {hit.meta}"
            card = extract_vehicle_card(blob)
            if card:
                cards.append(card)
            for name in extract_owner_mentions(blob):
                if name not in owners:
                    owners.append(name)
    for hit in web[:3]:
        if not hit.url:
            continue
        page = _fetch_public_snippet(hit.url, compact)
        if not page:
            continue
        card = extract_vehicle_card(page)
        if card:
            cards.append(card)
        for name in extract_owner_mentions(page):
            if name not in owners:
                owners.append(name)
    return merge_vehicle_cards(cards), owners[:3], web


def _fetch_public_snippet(url: str, plate: str) -> str:
    host = (url or "").lower()
    if any(skip in host for skip in ("detran.", "gov.br/login", "facebook.com", "instagram.com", "whatsapp.com")):
        return ""
    try:
        from osint4all.http_client import RateLimitedClient

        http = RateLimitedClient(
            source="plate_page",
            max_concurrency=1,
            timeout=6.0,
            default_headers={"User-Agent": "osint4all/0.1 (public mention)"},
        )
        resp = http.request("GET", url, allow_404=True, max_retries=1)
        if resp.status_code >= 400:
            return ""
        raw = (resp.text or "")[:12000]
    except Exception:
        return ""
    text = re.sub(r"(?is)<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", raw)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    needle = plate.replace("-", "")
    idx = text.upper().find(needle[:3])
    if idx < 0:
        return text[:800]
    return text[max(0, idx - 220) : idx + 420]


def _safe_web_search(settings: Settings, query: str, origin_key: str) -> list[ConsultHit]:
    if not web_search_ready(settings):
        return []
    try:
        parsed = WebSearchConnector(settings).search(query, origin_key)
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
    "public_ficha",
    "ficha_from_cnpj_result",
]
