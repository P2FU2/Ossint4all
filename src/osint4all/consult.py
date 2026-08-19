"""Consultas rápidas — sem abrir um caso. Só fontes públicas."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from osint4all.config import Settings, get_settings
from osint4all.connectors.cnpj_receita import CnpjReceitaConnector, parse_cnpj_payload
from osint4all.connectors.plate_public import describe_plate, parse_plate_enrichment
from osint4all.connectors.socio_search import SocioSearchConnector
from osint4all.connectors.username_public import UsernamePublicConnector
from osint4all.identifiers import detect_kind, parse_seed
from osint4all.security import only_digits
from osint4all.validators import format_plate, looks_like_plate, validate_cnpj, validate_cpf


# key, label, tip, placeholder
MODES = (
    ("auto", "Detectar", "Reconhece placa, CNPJ, CPF, e-mail, telefone, @user, processo ou nome.", "ABC1D23, @jornalista, nome do sócio…"),
    ("PLATE", "Placa", "Série histórica e portais oficiais. Sem dono no DETRAN.", "ABC1D23 ou ABC-1234"),
    ("USERNAME", "Rede social", "URLs públicas (GitHub, X, Telegram…). Sem login.", "@usuario"),
    ("PHONE", "Telefone", "Normaliza e aponta menções públicas. Sem operadora.", "11 99999-0000"),
    ("NAME", "Sócio / nome", "Empresas do quadro societário na base aberta da Receita.", "Nome e sobrenome"),
    ("CNPJ", "CNPJ", "Ficha cadastral e QSA oficiais (Minha Receita / BrasilAPI).", "00.000.000/0001-00"),
    ("CPF", "CPF", "Valida o número e aponta a consulta pública da Receita.", "000.000.000-00"),
    ("EMAIL", "E-mail", "Normaliza e sugere buscas públicas. Sem caixa de entrada.", "nome@dominio.com"),
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


@dataclass
class ConsultHit:
    title: str
    meta: str = ""
    url: str | None = None
    kind: str = "item"


@dataclass
class ConsultResult:
    kind: str
    query: str
    title: str
    summary: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    hits: list[ConsultHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = True
    error: str | None = None

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind or "Consulta")


def resolve_kind(mode: str, raw: str) -> str | None:
    forced = (mode or "auto").upper()
    if forced in {"", "AUTO"}:
        return detect_kind(raw)
    seed = parse_seed(raw, forced_kind=forced)
    return seed.kind if seed else forced


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
            return _consult_plate(text)
        if kind == "USERNAME":
            return _consult_username(text, settings, quick=quick)
        if kind == "PHONE":
            return _consult_phone(text)
        if kind == "CNPJ":
            return _consult_cnpj(text, settings)
        if kind == "CPF":
            return _consult_cpf(text)
        if kind == "EMAIL":
            return _consult_email(text)
        if kind == "NAME":
            return _consult_name(text, settings)
        if kind == "CNJ":
            return _consult_cnj(text)
    except Exception as exc:  # noqa: BLE001
        return ConsultResult(kind=kind, query=text, title=text, summary="", ok=False, error=str(exc))
    return ConsultResult(kind=kind, query=text, title=text, summary="Tipo reconhecido. Abra um caso para expandir o grafo.")


def _consult_plate(raw: str) -> ConsultResult:
    if not looks_like_plate(raw):
        return ConsultResult(kind="PLATE", query=raw, title=raw, summary="", ok=False, error="Placa inválida. Use ABC1D23 ou ABC-1234.")
    info = describe_plate(raw)
    pretty = info["placa"]
    parsed = parse_plate_enrichment(raw, origin_key=f"plate:{info['placa_compacta']}")
    hits = [
        ConsultHit(ev.source_label, ev.snippet or "", ev.url, "fonte")
        for ev in parsed.evidence
    ]
    return ConsultResult(
        kind="PLATE",
        query=pretty,
        title=pretty,
        summary=f"{info['padrao']}. {info['serie_nota']}",
        facts=[
            ("Padrão", info["padrao"]),
            ("Série (1º emplacamento)", info.get("serie_uf") or "—"),
            ("Placa compacta", info["placa_compacta"]),
        ],
        hits=hits,
        notes=["O DETRAN não publica o proprietário só com a placa. Para ligar um dono, use Guardar no grafo e informe o nome."],
    )


def _consult_username(raw: str, settings: Settings, *, quick: bool = False) -> ConsultResult:
    user = raw.strip().lstrip("@").lower()
    conn = UsernamePublicConnector(settings)
    fake = SimpleNamespace(canonical_key=f"username:{user}", display_name=user, entity_type="PROFILE", identifiers=[])
    result = conn.collect(fake, SimpleNamespace(core_only=quick))
    hits = [ConsultHit(e.display_name, e.value, e.value, "perfil") for e in result.entities]
    return ConsultResult(
        kind="USERNAME",
        query=f"@{user}",
        title=f"@{user}",
        summary=f"{len(hits)} perfil(is) público(s) com HTTP 200. Ausência não prova que a conta não existe.",
        facts=[("Usuário", user), ("Redes checadas", str(len(conn.health()["networks"])))],
        hits=hits,
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


def _consult_cnpj(raw: str, settings: Settings) -> ConsultResult:
    if not validate_cnpj(raw):
        return ConsultResult(kind="CNPJ", query=raw, title=raw, summary="", ok=False, error="CNPJ inválido.")
    digits = only_digits(raw)
    data = CnpjReceitaConnector(settings)._fetch(digits)
    parsed = parse_cnpj_payload(data)
    org = next((e for e in parsed.entities if e.kind == "CNPJ"), None)
    attrs = org.attrs if org else {}
    hits = [
        ConsultHit(e.display_name, str(e.attrs.get("papel") or e.kind), None, "socio")
        for e in parsed.entities
        if not (e.kind == "CNPJ" and only_digits(e.value) == digits)
    ]
    return ConsultResult(
        kind="CNPJ",
        query=digits,
        title=str(attrs.get("razao_social") or org.display_name if org else digits),
        summary=f"{attrs.get('situacao') or 'Situação n/d'} · {attrs.get('municipio') or ''} {attrs.get('uf') or ''}".strip(),
        facts=[
            ("CNPJ", digits),
            ("CNAE", str(attrs.get("cnae") or "—")),
            ("Porte", str(attrs.get("porte") or "—")),
            ("Simples", str(attrs.get("simples"))),
            ("MEI", str(attrs.get("mei"))),
            ("Endereço", str(attrs.get("endereco") or "—")),
        ],
        hits=hits
        + [
            ConsultHit("Minha Receita", "Ficha oficial", f"https://minhareceita.org/{digits}", "fonte"),
        ],
    )


def _consult_cpf(raw: str) -> ConsultResult:
    if not validate_cpf(raw):
        return ConsultResult(kind="CPF", query=raw, title=raw, summary="", ok=False, error="CPF inválido.")
    digits = only_digits(raw)
    return ConsultResult(
        kind="CPF",
        query=digits,
        title=f"***.***.***-{digits[-2:]}",
        summary="Número válido. A Receita não publica nome pelo CPF em API aberta.",
        facts=[("Dígitos", "11"), ("Máscara", f"***.***.***-{digits[-2:]}")],
        hits=[
            ConsultHit(
                "Situação cadastral (Receita)",
                "Portal oficial — exige os dados do titular",
                "https://servicos.receita.fazenda.gov.br/Servicos/CPF/ConsultaSituacao/ConsultaPublica.asp",
                "fonte",
            )
        ],
        notes=["Para cruzar com empresas, use o nome do titular na consulta de sócio."],
    )


def _consult_email(raw: str) -> ConsultResult:
    email = raw.strip().lower()
    local, _, domain = email.partition("@")
    hits = [
        ConsultHit("Hunter / e-mail no domínio", domain, f"https://www.google.com/search?q=%22{email}%22", "link"),
    ]
    if local:
        hits.append(ConsultHit("Mesmo identificador como @user", f"@{local}", None, "dica"))
    return ConsultResult(
        kind="EMAIL",
        query=email,
        title=email,
        summary="E-mail normalizado. Não acessamos caixas nem vazamentos.",
        facts=[("Local", local), ("Domínio", domain)],
        hits=hits,
        notes=["Guarde no grafo para cruzar com username e menções web."],
    )


def _consult_name(raw: str, settings: Settings) -> ConsultResult:
    if " " not in raw.strip():
        return ConsultResult(kind="NAME", query=raw, title=raw, summary="", ok=False, error="Use nome e sobrenome.")
    conn = SocioSearchConnector(settings)
    fake = SimpleNamespace(canonical_key=f"name:{raw.strip().casefold()}", display_name=raw.strip(), entity_type="PERSON", identifiers=[])
    parsed = conn.collect(fake, SimpleNamespace(investigation=SimpleNamespace(id="consult"), settings=settings))
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
        for e in parsed.entities
        if e.entity_type == "ORG"
    ]
    return ConsultResult(
        kind="NAME",
        query=raw.strip(),
        title=raw.strip(),
        summary=f"{len(hits)} empresa(s) no quadro societário público." if hits else "Nenhuma empresa nesta consulta pontual.",
        facts=[("Empresas", str(len(hits)))],
        hits=hits,
        notes=parsed.notes
        + ["Aprofundar no grafo puxa o QSA completo de cada CNPJ (co-sócios, CNAE, mapa)."],
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
