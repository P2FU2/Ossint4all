"""Placa de veículo: série pública, portais oficiais e vínculo com proprietário declarado.

Não consulta DETRAN, SINESP nem bases de dono. O nome do proprietário só entra
se o jornalista informar (fonte lícita) ou se aparecer em menção pública.
"""

from __future__ import annotations

import re
from typing import Any

from osint4all.config import Settings
from osint4all.connectors.base import ConnectorResult, ExpandContext, FoundEdge, FoundEntity, FoundEvidence
from osint4all.db.models import Entity
from osint4all.exceptions import SkippedDisabled
from osint4all.identifiers import canonical_key
from osint4all.validators import format_plate, looks_like_plate, normalize_plate, validate_cpf

# Faixas históricas de 1º emplacamento (DENATRAN / Wikipedia). Não é o município atual.
_SERIES: tuple[tuple[str, str, str], ...] = (
    ("AAA", "BEZ", "PR"),
    ("BFA", "GKI", "SP"),
    ("GKJ", "HOK", "MG"),
    ("HOL", "HQE", "MA"),
    ("HQF", "HTW", "MS"),
    ("HTX", "HZA", "CE"),
    ("HZB", "IAP", "SE"),
    ("IAQ", "JDO", "RS"),
    ("JDP", "JKR", "DF"),
    ("JKS", "JSZ", "BA"),
    ("JTA", "JUE", "PR"),
    ("JUF", "JWV", "SC"),
    ("JWX", "JXY", "PI"),
    ("JXZ", "KAU", "GO"),
    ("KAV", "KFC", "PE"),
    ("KFD", "KME", "RJ"),
    ("KMF", "LVE", "SP"),
    ("LVF", "LWQ", "RJ"),
    ("LWR", "MME", "SP"),
    ("MMF", "NEH", "MG"),
    ("NEI", "NFB", "MA"),
    ("NFC", "NGZ", "MS"),
    ("NHA", "NHT", "CE"),
    ("NHU", "NIX", "SE"),
    ("NIY", "NJW", "RS"),
    ("NJX", "NLU", "DF"),
    ("NLV", "NMO", "AL"),
    ("NMP", "NNI", "TO"),
    ("NNJ", "NOH", "AM"),
    ("NOI", "NPB", "RO"),
    ("NPC", "NPQ", "AC"),
    ("NPR", "NQK", "RR"),
    ("NQL", "NRE", "PA"),
    ("NRF", "NSD", "AP"),
    ("NSE", "NTH", "GO"),
    ("NTI", "NUB", "PE"),
    ("NUC", "NUP", "PI"),
    ("NUQ", "NVO", "MA"),
    ("NVP", "NWB", "CE"),
    ("NWC", "NXQ", "MT"),
    ("OIQ", "OJG", "MT"),
    ("OLN", "OMN", "SC"),
    ("OOG", "OOU", "GO"),
    ("OOV", "ORC", "MG"),
    ("ORD", "ORM", "AL"),
    ("ORN", "OSV", "TO"),
    ("OSW", "OTZ", "AM"),
    ("OUA", "OUE", "CE"),
    ("OUF", "OVD", "SE"),
    ("OVE", "OVF", "BA"),
    ("OVG", "OVG", "ES"),
    ("OVH", "OVL", "GO"),
    ("OVM", "OVV", "MA"),
    ("OVW", "OXH", "PA"),
    ("OXI", "OXK", "PI"),
    ("OXL", "OXL", "RO"),
    ("OXM", "OXM", "RR"),
    ("OXN", "OXN", "AP"),
    ("OXO", "OXO", "AL"),
    ("OXP", "OXP", "TO"),
    ("OXQ", "OXQ", "PB"),
    ("OXR", "OXR", "RS"),
    ("OXS", "OXZ", "PR"),
    ("OYA", "OYC", "PE"),
    ("OYD", "OYK", "SE"),
    ("OYL", "OYZ", "BA"),
    ("PAA", "PBZ", "PR"),
    ("PCA", "PDZ", "SP"),
    ("PEA", "PFZ", "MG"),
    ("PGA", "PGZ", "CE"),
    ("PHA", "PHZ", "BA"),
    ("PIA", "PIZ", "RS"),
    ("PJA", "PJZ", "GO"),
    ("PKA", "PKZ", "PE"),
    ("PLA", "PLZ", "RJ"),
    ("PMA", "PMZ", "SC"),
    ("PNA", "PNZ", "PA"),
    ("POA", "POZ", "MA"),
    ("PPA", "PPZ", "MT"),
    ("PQA", "PQZ", "ES"),
    ("PRA", "PRZ", "PB"),
    ("PSA", "PSZ", "RN"),
    ("PTA", "PTZ", "PI"),
    ("PUA", "PUZ", "AL"),
    ("PVA", "PVZ", "MS"),
    ("PWA", "PWZ", "SE"),
    ("PXA", "PXZ", "TO"),
    ("PYA", "PYZ", "AM"),
    ("PZA", "PZZ", "RO"),
    ("QAA", "QAZ", "AC"),
    ("QBA", "QBZ", "RR"),
    ("QCA", "QCZ", "AP"),
    ("QDA", "QDZ", "DF"),
    ("QEA", "QEZ", "ES"),
    ("QFA", "QFZ", "PB"),
    ("QGA", "QGZ", "RN"),
    ("QHA", "QHZ", "SC"),
    ("QIA", "QIZ", "SP"),
    ("QJA", "QJZ", "MG"),
    ("QKA", "QKZ", "PR"),
    ("QLA", "QLZ", "RJ"),
    ("QMA", "QMZ", "BA"),
    ("QNA", "QNZ", "RS"),
    ("QOA", "QOZ", "GO"),
    ("QPA", "QPZ", "PE"),
    ("QQA", "QQZ", "CE"),
    ("QRA", "QRZ", "PA"),
    ("QSA", "QSZ", "MA"),
    ("QTA", "QTZ", "MT"),
    ("QUA", "QUZ", "MS"),
    ("QVA", "QVZ", "PI"),
    ("QWA", "QWZ", "AL"),
    ("QXA", "QXZ", "SE"),
    ("QYA", "QYZ", "TO"),
    ("QZA", "QZZ", "AM"),
    ("RAA", "RAZ", "RO"),
    ("RBA", "RBZ", "AC"),
    ("RCA", "RCZ", "RR"),
    ("RDA", "RDZ", "AP"),
    ("REA", "REZ", "DF"),
)

_DETRAN_PORTAL = {
    "AC": "https://www.detran.ac.gov.br/",
    "AL": "https://detran.al.gov.br/",
    "AM": "https://www.detran.am.gov.br/",
    "AP": "https://www.detran.ap.gov.br/",
    "BA": "https://www.detran.ba.gov.br/",
    "CE": "https://www.detran.ce.gov.br/",
    "DF": "https://www.detran.df.gov.br/",
    "ES": "https://detran.es.gov.br/",
    "GO": "https://www.detran.go.gov.br/",
    "MA": "https://www.detran.ma.gov.br/",
    "MG": "https://www.detran.mg.gov.br/",
    "MS": "https://www.detran.ms.gov.br/",
    "MT": "https://www.detran.mt.gov.br/",
    "PA": "https://www.detran.pa.gov.br/",
    "PB": "https://detran.pb.gov.br/",
    "PE": "https://www.detran.pe.gov.br/",
    "PI": "https://www.detran.pi.gov.br/",
    "PR": "https://www.detran.pr.gov.br/",
    "RJ": "https://www.detran.rj.gov.br/",
    "RN": "https://www.detran.rn.gov.br/",
    "RO": "https://www.detran.ro.gov.br/",
    "RR": "https://www.detran.rr.gov.br/",
    "RS": "https://www.detran.rs.gov.br/",
    "SC": "https://www.detran.sc.gov.br/",
    "SE": "https://www.detran.se.gov.br/",
    "SP": "https://www.detran.sp.gov.br/",
    "TO": "https://www.detran.to.gov.br/",
}

_BRANDS = (
    "Fiat", "Ford", "Volkswagen", "VW", "Chevrolet", "Honda", "Toyota", "Hyundai",
    "Renault", "Jeep", "Nissan", "Peugeot", "Citroën", "Citroen", "Mitsubishi",
    "Kia", "BMW", "Mercedes", "Audi", "Volvo", "Iveco", "Scania", "Yamaha",
    "Suzuki", "Kawasaki", "Chery", "CAOA", "Caoa", "JAC", "BYD", "Ram",
)

_OWNER_RE = re.compile(
    r"(?:propriet[aá]rio(?:\(a\))?|em nome de|perten(?:ce|cente) a|de propriedade de)\s+"
    r"([A-ZÁÉÍÓÚÂÊÔÃÕ][A-Za-zÁÉÍÓÚÂÊÔÃÕáéíóúâêôãõç']+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕ][A-Za-zÁÉÍÓÚÂÊÔÃÕáéíóúâêôãõç']+){1,5})",
    re.I,
)
_VEHICLE_RE = re.compile(
    rf"\b((?:{'|'.join(_BRANDS)})\s+[A-Za-z0-9][A-Za-z0-9\- ]{{1,24}}?)(?:\s+(?:ano\s+)?((?:19|20)\d{{2}}))?",
    re.I,
)
_STOP_NAMES = {
    "sao paulo", "rio de janeiro", "minas gerais", "estado", "prefeitura",
    "detran", "senatran", "veiculo", "veículo", "motocicleta",
}


def plate_from_entity(entity: Entity) -> str | None:
    if entity.canonical_key.startswith("plate:"):
        return entity.canonical_key.split(":", 1)[1]
    raw = (entity.display_name or "").strip()
    if looks_like_plate(raw):
        return normalize_plate(raw)
    return None


def uf_from_plate_series(plate: str) -> str | None:
    prefix = normalize_plate(plate)[:3]
    if len(prefix) != 3:
        return None
    for start, end, uf in _SERIES:
        if start <= prefix <= end:
            return uf
    return None


def describe_plate(plate: str) -> dict[str, Any]:
    compact = normalize_plate(plate)
    pretty = format_plate(compact)
    mercosul = len(compact) == 7 and compact[4].isalpha()
    uf = uf_from_plate_series(compact)
    return {
        "placa": pretty,
        "placa_compacta": compact,
        "padrao": "Mercosul" if mercosul else "cinza (pré-Mercosul)",
        "serie_uf": uf,
        "serie_nota": (
            f"Série histórica de 1º emplacamento: {uf}. Não confirma UF atual nem o dono."
            if uf
            else "Série fora da tabela histórica conhecida."
        ),
    }


def extract_owner_mentions(text: str) -> list[str]:
    names: list[str] = []
    for match in _OWNER_RE.finditer(text or ""):
        name = re.sub(r"\s+", " ", match.group(1)).strip(" .,;")
        if name.casefold() in _STOP_NAMES or len(name.split()) < 2:
            continue
        if name not in names:
            names.append(name)
    return names[:3]


def extract_vehicle_mentions(text: str) -> list[str]:
    found: list[str] = []
    for match in _VEHICLE_RE.finditer(text or ""):
        model = re.sub(r"\s+", " ", match.group(1)).strip(" .,;-")
        year = match.group(2)
        label = f"{model} {year}".strip() if year else model
        if 3 < len(label) < 40 and label not in found:
            found.append(label)
    return found[:3]


def parse_plate_enrichment(
    plate: str,
    *,
    origin_key: str,
    owner_name: str = "",
    owner_cpf: str = "",
    mentions: list[str] | None = None,
) -> ConnectorResult:
    info = describe_plate(plate)
    pretty = info["placa"]
    out = ConnectorResult()
    out.entities.append(
        FoundEntity(
            entity_type="VEHICLE",
            kind="PLATE",
            value=pretty,
            display_name=pretty,
            attrs={k: v for k, v in info.items() if v},
            confidence=0.95,
        )
    )
    snippet = f"{pretty} · {info['padrao']}"
    if info.get("serie_uf"):
        snippet += f" · série {info['serie_uf']}"
    out.evidence.append(
        FoundEvidence(
            source_label="Placa pública (série DENATRAN)",
            url="https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran/consultas",
            snippet=snippet,
            payload=info,
            entity_ref=origin_key,
        )
    )
    out.evidence.append(
        FoundEvidence(
            source_label="SENATRAN · recalls e consultas",
            url="https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran/recalls",
            snippet="Portal oficial. A consulta de dono exige Renavam/gov.br e não é API pública.",
            payload={"portal": "senatran"},
            entity_ref=origin_key,
        )
    )
    uf = info.get("serie_uf")
    if uf and uf in _DETRAN_PORTAL:
        out.evidence.append(
            FoundEvidence(
                source_label=f"DETRAN-{uf} (portal oficial)",
                url=_DETRAN_PORTAL[uf],
                snippet=f"Consulta estadual. Exige placa + Renavam; não devolve o dono por API.",
                payload={"uf": uf},
                entity_ref=origin_key,
            )
        )
    out.merge(parse_declared_owner(origin_key, owner_name=owner_name, owner_cpf=owner_cpf, source="declarado"))
    for mention in mentions or []:
        out.merge(parse_declared_owner(origin_key, owner_name=mention, source="mencao_publica", confidence=0.32))
    return out


def parse_declared_owner(
    plate_key: str,
    *,
    owner_name: str = "",
    owner_cpf: str = "",
    source: str = "declarado",
    confidence: float = 0.85,
) -> ConnectorResult:
    out = ConnectorResult()
    person: FoundEntity | None = None
    if owner_cpf and validate_cpf(owner_cpf):
        person = FoundEntity(
            entity_type="PERSON",
            kind="CPF",
            value=owner_cpf,
            display_name=owner_name.strip() or owner_cpf,
            attrs={"role": "proprietario", "from_plate": True, "source": source},
            confidence=confidence,
        )
    elif owner_name and " " in owner_name.strip():
        person = FoundEntity(
            entity_type="PERSON",
            kind="NAME",
            value=owner_name.strip(),
            display_name=owner_name.strip(),
            attrs={"role": "proprietario", "from_plate": True, "source": source},
            confidence=min(confidence, 0.7),
        )
    if not person:
        return out
    out.entities.append(person)
    person_key = canonical_key(person.kind, person.value)
    out.edges.append(
        FoundEdge(
            from_ref=person_key,
            to_ref=plate_key,
            rel_type="PROPRIETARIO",
            confidence=person.confidence,
            attrs={"fonte": source},
        )
    )
    out.evidence.append(
        FoundEvidence(
            source_label="Proprietário do veículo",
            snippet=f"{person.display_name} · {source}",
            payload={"nome": person.display_name, "fonte": source},
            entity_ref=person_key,
        )
    )
    return out


class PlatePublicConnector:
    name = "plate_public"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health(self) -> dict[str, Any]:
        return {
            "source": self.name,
            "enabled": self.settings.plate_public_enable,
            "owner_api": False,
            "note": "sem consulta DETRAN; dono só se declarado ou mencionado em fonte pública",
        }

    def accepts(self, entity: Entity) -> bool:
        return plate_from_entity(entity) is not None

    def collect(self, entity: Entity, ctx: ExpandContext) -> ConnectorResult:
        if not self.settings.plate_public_enable:
            raise SkippedDisabled("placa pública desabilitada")
        plate = plate_from_entity(entity)
        if not plate:
            return ConnectorResult()
        attrs = dict(entity.attrs or {})
        mentions = extract_owner_mentions(" ".join(str(v) for v in attrs.values() if v))
        return parse_plate_enrichment(
            plate,
            origin_key=entity.canonical_key,
            owner_name=str(attrs.get("owner_name") or ""),
            owner_cpf=str(attrs.get("owner_cpf") or ""),
            mentions=mentions,
        )
