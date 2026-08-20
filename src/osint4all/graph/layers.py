"""Camadas do alvo: cada campo novo destrava a busca seguinte, sem fundir homônimo."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from osint4all.config import Settings, get_settings
from osint4all.connectors.cnpj_receita import CnpjReceitaConnector, parse_cnpj_payload
from osint4all.connectors.socio_search import SocioSearchConnector
from osint4all.consult import ConsultResult, run_consult
from osint4all.graph.identity import is_weak_name, names_match
from osint4all.graph.match import infer_place, score_identity, snap_from_fields
from osint4all.identifiers import dedupe_seeds, parse_seed
from osint4all.security import only_digits
from osint4all.validators import validate_cnpj


ALVO_GROUPS = (
    ("identidade", "Identidade", (("NAME", "Nome completo"), ("CPF", "CPF"))),
    ("contato", "Contato", (("EMAIL", "E-mail"), ("PHONE", "Telefone"))),
    ("digital", "Digital", (("USERNAME", "Rede social / @user"),)),
    ("patrimonio", "Patrimônio", (("PLATE", "Placa"), ("CNPJ", "CNPJ da empresa do alvo"))),
    ("processo", "Processo", (("CNJ", "Número CNJ"),)),
)

ALVO_KINDS = tuple(kind for _g, _l, fields in ALVO_GROUPS for kind, _ in fields)


@dataclass
class AlvoHit:
    kind: str
    value: str
    title: str
    summary: str
    confirmed: bool
    reason: str
    url: str | None = None
    match: int | None = None


@dataclass
class AlvoLayerResult:
    fields: dict[str, str]
    added_kind: str
    added_value: str
    consult: ConsultResult | None = None
    confirmed: list[AlvoHit] = field(default_factory=list)
    candidates: list[AlvoHit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    qsa_match: bool = False
    ok: bool = True
    error: str | None = None


def qsa_confirms_name(cnpj: str, name: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    digits = only_digits(cnpj)
    target = (name or "").strip()
    if not target or not validate_cnpj(digits):
        return False
    try:
        parsed = parse_cnpj_payload(CnpjReceitaConnector(settings)._fetch(digits))
    except Exception:
        return False
    return any(e.entity_type == "PERSON" and names_match(e.display_name, target) for e in parsed.entities)


def confirmed_seeds(fields: dict[str, str], *, qsa_match: bool = False) -> list:
    person_anchors = {"CPF", "EMAIL", "PHONE", "USERNAME", "PLATE", "CNJ"}
    name_ok = bool(qsa_match or any(fields.get(k) for k in person_anchors))
    seeds = []
    for kind, value in fields.items():
        if kind == "NAME" and not name_ok:
            continue
        seeds.append(parse_seed(value, forced_kind=kind))
    return dedupe_seeds(seeds)


def run_alvo_layer(
    fields: dict[str, str],
    *,
    kind: str,
    value: str,
    settings: Settings | None = None,
    live: bool = True,
) -> AlvoLayerResult:
    settings = settings or get_settings()
    merged = {k: v for k, v in fields.items() if (v or "").strip()}
    text = (value or "").strip()
    kind = (kind or "").upper()
    if not text or kind not in ALVO_KINDS:
        return AlvoLayerResult(fields=merged, added_kind=kind, added_value=text, ok=False, error="Informe um campo válido.")
    merged[kind] = text
    consult = run_consult(text, mode=kind, settings=settings, quick=not live)
    out = AlvoLayerResult(fields=merged, added_kind=kind, added_value=text, consult=consult, ok=consult.ok, error=consult.error)
    if consult.ok:
        out.confirmed.append(
            AlvoHit(kind, consult.query, consult.title, consult.summary, True, "Você digitou este valor no alvo.")
        )
        if kind == "EMAIL" and "@" in text:
            local = text.split("@", 1)[0].strip().lstrip("@")
            if local and not merged.get("USERNAME"):
                merged["USERNAME"] = local
                out.confirmed.append(
                    AlvoHit(
                        "USERNAME",
                        local,
                        f"@{local}",
                        "Local-part do e-mail, testado como @user em redes públicas.",
                        True,
                        "Derivado do e-mail que você digitou.",
                    )
                )
    if kind == "CNPJ" and live:
        _layer_cnpj_qsa(out, settings, merged.get("NAME") or "")
    elif kind == "NAME":
        if any(merged.get(k) for k in ("CPF", "EMAIL", "PHONE")):
            out.notes.append(
                "O alvo já tem CPF ou contato. A busca só pelo nome fica desligada para não misturar homônimo."
            )
        elif live:
            _layer_name_candidates(out, settings, text)
    elif kind == "CPF" and live and " " in (merged.get("NAME") or ""):
        out.notes.append("CPF âncora. Empresas pelo nome só entram se o QSA bater com este alvo.")
    return out


def _layer_cnpj_qsa(out: AlvoLayerResult, settings: Settings, target_name: str) -> None:
    digits = only_digits(out.added_value)
    if not validate_cnpj(digits):
        return
    try:
        data = CnpjReceitaConnector(settings)._fetch(digits)
        parsed = parse_cnpj_payload(data)
    except Exception as exc:  # noqa: BLE001
        out.notes.append(f"QSA indisponível: {exc}")
        return
    partners = [e for e in parsed.entities if e.kind in {"NAME", "CPF", "CNPJ"} and not (e.kind == "CNPJ" and only_digits(e.value) == digits)]
    matched = [p for p in partners if target_name and names_match(p.display_name, target_name)]
    if target_name and matched:
        out.qsa_match = True
        person = matched[0]
        out.confirmed.append(
            AlvoHit(
                "NAME",
                person.display_name,
                person.display_name,
                "Nome no QSA oficial desta empresa.",
                True,
                f"QSA do CNPJ {digits}",
                f"https://minhareceita.org/{digits}",
            )
        )
        out.notes.append("O nome do alvo consta no quadro societário. Coligadas usam este sócio confirmado.")
        if not is_weak_name(target_name):
            _layer_coligadas(out, settings, target_name, digits)
        else:
            out.notes.append("Nome com menos de três termos: coligadas ficam como candidatas para você confirmar.")
            _layer_coligadas(out, settings, target_name, digits, as_candidates=True)
    elif target_name:
        out.notes.append("O nome do alvo não aparece neste QSA. A empresa não foi ligada automaticamente.")
        for partner in partners:
            if partner.entity_type != "PERSON":
                continue
            out.candidates.append(
                AlvoHit(
                    "NAME",
                    partner.display_name,
                    partner.display_name,
                    str((partner.attrs or {}).get("papel") or "sócio"),
                    False,
                    "Homônimo possível no QSA — confirme se for a mesma pessoa.",
                )
            )
    else:
        out.notes.append("Sem nome no alvo, o QSA entra só como ficha da empresa. Preencha o nome para cruzar sócios.")


def _layer_name_candidates(out: AlvoLayerResult, settings: Settings, name: str) -> None:
    if is_weak_name(name):
        out.notes.append("Nome curto (dois termos ou menos): tudo que vier por nome fica candidato até CPF ou CNPJ âncora.")
    fake = SimpleNamespace(
        canonical_key=f"name:{name.strip().casefold()}",
        display_name=name.strip(),
        entity_type="PERSON",
        identifiers=[],
    )
    try:
        found = SocioSearchConnector(settings).collect(
            fake, SimpleNamespace(investigation=SimpleNamespace(id="alvo"), settings=settings)
        )
    except Exception as exc:  # noqa: BLE001
        out.notes.append(str(exc))
        return
    for entity in found.entities:
        if entity.entity_type != "ORG":
            continue
        cnpj = only_digits(entity.value)
        attrs = entity.attrs or {}
        place = infer_place(
            municipio=str(attrs.get("municipio") or ""),
            uf=str(attrs.get("uf") or ""),
            role="empresa",
            source=entity.display_name,
        )
        scored = score_identity(
            snap_from_fields(out.fields),
            snap_from_fields({"NAME": name}, places=[place] if place else [], companies=[entity.display_name]),
        )
        out.candidates.append(
            AlvoHit(
                "CNPJ",
                cnpj,
                entity.display_name,
                " · ".join(
                    bit
                    for bit in (
                        str(attrs.get("situacao") or ""),
                        f"{attrs.get('municipio') or ''}/{attrs.get('uf') or ''}".strip("/"),
                    )
                    if bit and bit != "/"
                ),
                False,
                "Empresa pelo nome do sócio. Confirme ou informe o CNPJ para validar no QSA.",
                f"https://minhareceita.org/{cnpj}" if cnpj else None,
                scored.identity_match,
            )
        )
    out.notes.extend(found.notes)


def _layer_coligadas(
    out: AlvoLayerResult,
    settings: Settings,
    name: str,
    origin_cnpj: str,
    *,
    as_candidates: bool = False,
) -> None:
    fake = SimpleNamespace(
        canonical_key=f"name:{name.strip().casefold()}",
        display_name=name.strip(),
        entity_type="PERSON",
        identifiers=[],
    )
    try:
        found = SocioSearchConnector(settings).collect(
            fake, SimpleNamespace(investigation=SimpleNamespace(id="alvo"), settings=settings)
        )
    except Exception:
        return
    conn = CnpjReceitaConnector(settings)
    seen = {origin_cnpj}
    for entity in found.entities:
        if entity.entity_type != "ORG":
            continue
        cnpj = only_digits(entity.value)
        if not validate_cnpj(cnpj) or cnpj in seen:
            continue
        seen.add(cnpj)
        qsa_ok = False
        try:
            parsed = parse_cnpj_payload(conn._fetch(cnpj))
            qsa_ok = any(names_match(e.display_name, name) for e in parsed.entities if e.entity_type == "PERSON")
        except Exception:
            qsa_ok = False
        hit = AlvoHit(
            "CNPJ",
            cnpj,
            entity.display_name,
            "Coligada: mesmo nome no QSA oficial." if qsa_ok else "Mesmo nome no índice de sócios — QSA não confirmou.",
            qsa_ok and not as_candidates,
            "QSA oficial com o nome do alvo." if qsa_ok else "Não ligar sem você confirmar.",
            f"https://minhareceita.org/{cnpj}",
        )
        (out.confirmed if hit.confirmed else out.candidates).append(hit)
        if len(seen) > 8:
            break
