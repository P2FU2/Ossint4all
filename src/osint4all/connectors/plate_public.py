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
    "Fiat", "Ford", "Volkswagen", "VW", "Chevrolet", "Chevy", "GM", "Honda", "Toyota",
    "Hyundai", "Renault", "Jeep", "Nissan", "Peugeot", "Citroën", "Citroen", "Mitsubishi",
    "Kia", "BMW", "Mercedes", "Mercedes-Benz", "Audi", "Volvo", "Iveco", "Scania",
    "Yamaha", "Suzuki", "Kawasaki", "Chery", "CAOA", "Caoa", "JAC", "BYD", "Ram",
    "Land Rover", "Jaguar", "Porsche", "Mini", "Dodge", "Chrysler", "Subaru",
    "Troller", "Agrale", "Shineray", "Haojue", "Dafra", "Kasinski",
)
_MODELS = (
    "Gol", "Voyage", "Saveiro", "Fox", "Polo", "Virtus", "Golf", "Jetta", "Nivus",
    "T-Cross", "Tcross", "Taos", "Amarok", "Kombi",
    "Onix", "Prisma", "Cruze", "Tracker", "S10", "Spin", "Montana", "Cobalt", "Celta", "Corsa",
    "Civic", "City", "Fit", "HR-V", "HRV", "WR-V", "WRV", "CR-V", "Civic",
    "Corolla", "Yaris", "Hilux", "SW4", "Etios", "RAV4",
    "HB20", "Creta", "Tucson", "i30", "IX35",
    "Kwid", "Sandero", "Logan", "Duster", "Oroch", "Captur", "Stepway",
    "Strada", "Toro", "Argo", "Mobi", "Uno", "Palio", "Siena", "Weekend", "Pulse", "Fastback", "Cronos", "Fiorino",
    "Compass", "Renegade", "Commander", "Wrangler",
    "Kicks", "Versa", "Frontier", "March", "Sentra",
    "Ranger", "Ka", "EcoSport", "Territory", "Maverick", "Fusion",
    "208", "2008", "3008", "Partner",
    "C3", "C4", "Aircross",
    "L200", "Outlander", "ASX", "Pajero",
    "Sportage", "Cerato", "Sorento",
    "Tiggo", "Arrizo",
    "Dolphin", "Yuan", "Song", "Seal",
    "Ranger", "S10",
    "CG", "Biz", "Bros", "Factor", "Fazer", "Titan",
)
_COLORS = (
    "branco", "preto", "prata", "cinza", "vermelho", "azul", "verde", "amarelo",
    "marrom", "vinho", "dourado", "laranja", "bege", "grafite", "chumbo", "rosa",
    "branco gelo", "preto fosco",
)
_BRAND_ALIASES = {
    "vw": "Volkswagen",
    "chevy": "Chevrolet",
    "gm": "Chevrolet",
    "mercedes-benz": "Mercedes-Benz",
}

_OWNER_RE = re.compile(
    r"(?:propriet[aá]rio(?:\(a\))?|em nome de|perten(?:ce|cente) a|de propriedade de)\s+"
    r"([A-ZÁÉÍÓÚÂÊÔÃÕ][A-Za-zÁÉÍÓÚÂÊÔÃÕáéíóúâêôãõç']+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕ][A-Za-zÁÉÍÓÚÂÊÔÃÕáéíóúâêôãõç']+){1,5})",
    re.I,
)
_BRAND_ALT = "|".join(re.escape(b) for b in sorted(_BRANDS, key=len, reverse=True))
_MODEL_ALT = "|".join(re.escape(m) for m in sorted(_MODELS, key=len, reverse=True))
_VEHICLE_RE = re.compile(
    rf"\b({_BRAND_ALT})\s+({_MODEL_ALT})\b(?:\s*(1\.\d|2\.\d))?(?:\s+(?:ano\s+|/?)\s*((?:19|20)\d{{2}}))?",
    re.I,
)
_MODEL_RE = re.compile(
    rf"\b({_MODEL_ALT})\b(?:\s*(1\.\d|2\.\d))?(?:\s+(?:ano\s+|/?)\s*((?:19|20)\d{{2}}))?",
    re.I,
)
_FIELD_RE = re.compile(
    r"\b(marca|modelo|ano(?:\s+modelo)?|cor|vers[aã]o)\s*[:\-]\s*([A-Za-z0-9ÁÉÍÓÚÂÊÔÃÕÇ][A-Za-z0-9ÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç.\-]{0,24})(?=\s+(?:marca|modelo|ano|cor|vers[aã]o|placa)\b|[.,;]|$|\s{2})",
    re.I,
)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})(?:\s*/\s*((?:19|20)\d{2}))?\b")
_COLOR_RE = re.compile(rf"\bcor\s*[:\-]?\s*({'|'.join(re.escape(c) for c in _COLORS)})\b|\b({'|'.join(re.escape(c) for c in _COLORS)})\b", re.I)
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
    card = extract_vehicle_card(text)
    if card.get("label"):
        return [card["label"]]
    return []


def extract_vehicle_card(text: str) -> dict[str, str]:
    """Marca, modelo, ano e cor a partir de anúncio, leilão ou notícia."""
    blob = re.sub(r"\s+", " ", text or "")
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(blob):
        key = match.group(1).casefold()
        value = match.group(2).strip(" .,;")
        if key.startswith("marca"):
            fields["marca"] = _canon_brand(value)
        elif key.startswith("modelo"):
            fields["modelo"] = value.title()
        elif key.startswith("ano"):
            year = _YEAR_RE.search(value)
            if year:
                fields["ano"] = year.group(1)
        elif key.startswith("cor"):
            fields["cor"] = value.casefold()
        elif key.startswith("vers"):
            fields["versao"] = value
    brand_hit = _VEHICLE_RE.search(blob)
    if brand_hit:
        fields.setdefault("marca", _canon_brand(brand_hit.group(1)))
        model = brand_hit.group(2)
        engine = brand_hit.group(3)
        fields.setdefault("modelo", (f"{model} {engine}".strip() if engine else model).title())
        if brand_hit.group(4):
            fields.setdefault("ano", brand_hit.group(4))
    if "modelo" not in fields:
        model_hit = _MODEL_RE.search(blob)
        if model_hit:
            model = model_hit.group(1)
            engine = model_hit.group(2)
            fields["modelo"] = (f"{model} {engine}".strip() if engine else model).title()
            if model_hit.group(3):
                fields.setdefault("ano", model_hit.group(3))
    if "ano" not in fields:
        year = _YEAR_RE.search(blob)
        if year:
            fields["ano"] = year.group(1)
    if "cor" not in fields:
        color = _COLOR_RE.search(blob)
        if color:
            fields["cor"] = (color.group(1) or color.group(2) or "").casefold()
    bits = [fields.get("marca"), fields.get("modelo"), fields.get("ano"), fields.get("cor")]
    label = " ".join(bit for bit in bits if bit)
    if label:
        fields["label"] = label
    return fields


def _canon_brand(value: str) -> str:
    raw = (value or "").strip()
    alias = _BRAND_ALIASES.get(raw.casefold())
    if alias:
        return alias
    for brand in _BRANDS:
        if brand.casefold() == raw.casefold():
            return brand
    return raw.title()


def merge_vehicle_cards(cards: list[dict[str, str]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for card in cards:
        for key, value in card.items():
            if key == "label" or not value:
                continue
            merged.setdefault(key, value)
    bits = [merged.get("marca"), merged.get("modelo"), merged.get("ano"), merged.get("cor")]
    label = " ".join(bit for bit in bits if bit)
    if label:
        merged["label"] = label
    return merged


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
