"""Telefone público — estilo PhoneInfoga: DDD, tipo e menção. Sem operadora."""

from __future__ import annotations

from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.security import only_digits

# DDD brasileiro → cidade âncora e UF (ANATEL). Sem operadora.
_DDD_BR: dict[str, tuple[str, str]] = {
    "11": ("São Paulo", "SP"),
    "12": ("São José dos Campos", "SP"),
    "13": ("Santos", "SP"),
    "14": ("Bauru", "SP"),
    "15": ("Sorocaba", "SP"),
    "16": ("Ribeirão Preto", "SP"),
    "17": ("São José do Rio Preto", "SP"),
    "18": ("Presidente Prudente", "SP"),
    "19": ("Campinas", "SP"),
    "21": ("Rio de Janeiro", "RJ"),
    "22": ("Campos dos Goytacazes", "RJ"),
    "24": ("Petrópolis", "RJ"),
    "27": ("Vitória", "ES"),
    "28": ("Cachoeiro de Itapemirim", "ES"),
    "31": ("Belo Horizonte", "MG"),
    "32": ("Juiz de Fora", "MG"),
    "33": ("Governador Valadares", "MG"),
    "34": ("Uberlândia", "MG"),
    "35": ("Varginha", "MG"),
    "37": ("Divinópolis", "MG"),
    "38": ("Montes Claros", "MG"),
    "41": ("Curitiba", "PR"),
    "42": ("Ponta Grossa", "PR"),
    "43": ("Londrina", "PR"),
    "44": ("Maringá", "PR"),
    "45": ("Foz do Iguaçu", "PR"),
    "46": ("Francisco Beltrão", "PR"),
    "47": ("Joinville", "SC"),
    "48": ("Florianópolis", "SC"),
    "49": ("Chapecó", "SC"),
    "51": ("Porto Alegre", "RS"),
    "53": ("Pelotas", "RS"),
    "54": ("Caxias do Sul", "RS"),
    "55": ("Santa Maria", "RS"),
    "61": ("Brasília", "DF"),
    "62": ("Goiânia", "GO"),
    "63": ("Palmas", "TO"),
    "64": ("Rio Verde", "GO"),
    "65": ("Cuiabá", "MT"),
    "66": ("Rondonópolis", "MT"),
    "67": ("Campo Grande", "MS"),
    "68": ("Rio Branco", "AC"),
    "69": ("Porto Velho", "RO"),
    "71": ("Salvador", "BA"),
    "73": ("Ilhéus", "BA"),
    "74": ("Juazeiro", "BA"),
    "75": ("Feira de Santana", "BA"),
    "77": ("Vitória da Conquista", "BA"),
    "79": ("Aracaju", "SE"),
    "81": ("Recife", "PE"),
    "82": ("Maceió", "AL"),
    "83": ("João Pessoa", "PB"),
    "84": ("Natal", "RN"),
    "85": ("Fortaleza", "CE"),
    "86": ("Teresina", "PI"),
    "87": ("Petrolina", "PE"),
    "88": ("Juazeiro do Norte", "CE"),
    "89": ("Picos", "PI"),
    "91": ("Belém", "PA"),
    "92": ("Manaus", "AM"),
    "93": ("Santarém", "PA"),
    "94": ("Marabá", "PA"),
    "95": ("Boa Vista", "RR"),
    "96": ("Macapá", "AP"),
    "97": ("Tefé", "AM"),
    "98": ("São Luís", "MA"),
    "99": ("Imperatriz", "MA"),
}


def phone_from_entity(entity: Entity) -> str | None:
    if str(getattr(entity, "canonical_key", "")).startswith("phone:"):
        digits = only_digits(entity.canonical_key.split(":", 1)[1])
        return digits if len(digits) >= 10 else None
    for ident in getattr(entity, "identifiers", None) or []:
        if ident.kind == "PHONE":
            digits = only_digits(ident.value or "")
            if len(digits) >= 10:
                return digits
    raw = only_digits(str((entity.attrs or {}).get("telefone") or entity.display_name or ""))
    return raw if len(raw) >= 10 else None


def describe_phone(raw: str) -> dict[str, str]:
    digits = only_digits(raw)
    out: dict[str, str] = {"digits": digits, "tamanho": str(len(digits))}
    national = digits
    if digits.startswith("55") and len(digits) in {12, 13}:
        out["pais"] = "Brasil"
        national = digits[2:]
    elif 10 <= len(digits) <= 11:
        out["pais"] = "Brasil"
    else:
        out["pais"] = "internacional"
        out["tipo"] = "número longo"
        return out
    ddd = national[:2]
    rest = national[2:]
    out["ddd"] = ddd
    city, uf = _DDD_BR.get(ddd, ("", ""))
    if city:
        out["cidade"] = city
        out["uf"] = uf
    if len(rest) == 9 and rest.startswith("9"):
        out["tipo"] = "celular"
    elif len(rest) == 8:
        out["tipo"] = "fixo"
    else:
        out["tipo"] = "indefinido"
    return out


def facts_from_phone(info: dict[str, str]) -> list[tuple[str, str]]:
    order = ("Dígitos", "Tamanho", "País", "DDD", "Cidade", "UF", "Tipo")
    raw = {
        "Dígitos": info.get("digits") or "",
        "Tamanho": info.get("tamanho") or "",
        "País": info.get("pais") or "",
        "DDD": info.get("ddd") or "",
        "Cidade": info.get("cidade") or "",
        "UF": info.get("uf") or "",
        "Tipo": info.get("tipo") or "",
    }
    return [(label, raw[label]) for label in order if raw[label]]


class PhonePublicConnector:
    name = "phone_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        return {"source": self.name, "enabled": self.settings.phone_public_enable, "via": "DDD ANATEL (sem operadora)"}

    def accepts(self, entity: Entity) -> bool:
        return phone_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.phone_public_enable:
            raise SkippedDisabled("Telefone público desabilitado")
        digits = phone_from_entity(entity)
        if not digits:
            return ConnectorResult()
        info = describe_phone(digits)
        place = " / ".join(part for part in (info.get("cidade"), info.get("uf")) if part)
        snippet = " · ".join(
            part
            for part in (
                f"DDD {info['ddd']}" if info.get("ddd") else "",
                place,
                info.get("tipo") or "",
            )
            if part
        )
        out = ConnectorResult()
        out.evidence.append(
            FoundEvidence(
                source_label="Telefone · DDD público",
                url=None,
                snippet=snippet or f"{len(digits)} dígitos",
                payload=info,
                entity_ref=entity.canonical_key,
            )
        )
        return out
