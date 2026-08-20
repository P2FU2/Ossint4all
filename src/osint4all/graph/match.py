"""Matching explicável: evidência positiva, neutra e contradição. Sem fundir sozinho."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from osint4all.graph.identity import (
    TargetProfile,
    collapse_name,
    entity_status,
    is_weak_name,
    name_tokens,
    names_match,
    names_same_person,
)
from osint4all.security import only_digits

DOSSIER_MATCH_MIN = 75

PLACE_KINDS = ("residence", "associated", "historical")
PLACE_ROLES = ("trabalho", "processo", "imovel", "veiculo", "empresa", "evento", "residencia")

SOURCE_RELIABILITY = (
    (("receita", "minhareceita", "diario oficial", "diário oficial", "datajud", "cnj", "tse"), 0.95),
    (("institucional", "gov.br", ".jus.br", "prefeitura"), 0.90),
    (("linkedin", "github", "orcid"), 0.75),
    (("rede social", "twitter", "instagram", "facebook"), 0.60),
    (("blog", "medium"), 0.45),
    (("forum", "fórum", "reddit"), 0.30),
)

QUEUE_BUCKETS = (
    ("confirmed", "Confirmado"),
    ("probable", "Provável"),
    ("unconfirmed", "Revisar"),
    ("false", "Descartado"),
)


@dataclass
class Place:
    kind: str
    municipio: str = ""
    uf: str = ""
    start: str = ""
    end: str = ""
    source: str = ""
    role: str = ""
    confidence: float = 0.5

    def label(self) -> str:
        city = "/".join(p for p in (self.municipio, self.uf) if p)
        return city or self.source or self.role or self.kind


@dataclass
class PersonSnap:
    name: str = ""
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    usernames: set[str] = field(default_factory=set)
    birth: str = ""
    companies: set[str] = field(default_factory=set)
    cargo: str = ""
    places: list[Place] = field(default_factory=list)
    relatives: set[str] = field(default_factory=set)
    sources: list[str] = field(default_factory=list)
    independent_origins: int = 0


@dataclass
class MatchSignal:
    key: str
    points: float
    why: str
    polarity: str


@dataclass
class MatchResult:
    identity_match: int
    source_reliability: float
    claim_confidence: float
    band: str
    suggested_status: str
    reasons: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    neutrals: list[str] = field(default_factory=list)
    signals: list[MatchSignal] = field(default_factory=list)


def band_for_score(score: int) -> str:
    if score < 60:
        return "descartado"
    if score < 75:
        return "revisar"
    if score < 90:
        return "provavel"
    return "forte"


def suggested_status(score: int, *, contradictions: int = 0) -> str:
    if score < 60 and contradictions:
        return "false"
    if score < 75:
        return "unconfirmed"
    return "probable"


def source_reliability(label: str) -> float:
    text = collapse_name(label)
    if not text:
        return 0.55
    for needles, weight in SOURCE_RELIABILITY:
        if any(n in text for n in needles):
            return weight
    return 0.55


def claim_confidence(*, independent: int, contradictions: int) -> float:
    if independent >= 3:
        score = 0.90
    elif independent >= 2:
        score = 0.75
    elif independent == 1:
        score = 0.55
    else:
        score = 0.35
    if contradictions:
        score = min(score, 0.40)
    return round(score, 2)


def username_rarity(value: str) -> float:
    raw = (value or "").strip().lstrip("@").casefold()
    if len(raw) < 4:
        return 0.25
    digits = sum(ch.isdigit() for ch in raw)
    if raw.endswith("123") or raw in {"admin", "user", "teste"}:
        return 0.2
    if len(raw) >= 8 and digits <= 2:
        return 1.0
    if len(raw) >= 6:
        return 0.6
    return 0.35


def _year(value: str) -> int | None:
    match = re.search(r"(19|20)\d{2}", value or "")
    return int(match.group(0)) if match else None


def _norm_uf(value: str) -> str:
    text = collapse_name(value).upper().replace(" ", "")
    return text[:2] if len(text) >= 2 else text


def _norm_city(value: str) -> str:
    return collapse_name(value)


def periods_overlap(left: Place, right: Place) -> bool:
    a0, a1 = _year(left.start), _year(left.end) or _year(left.start)
    b0, b1 = _year(right.start), _year(right.end) or _year(right.start)
    if a0 is None or b0 is None:
        return False
    a1 = a1 or a0
    b1 = b1 or b0
    return not (a1 < b0 or b1 < a0)


def place_from_dict(raw: dict[str, Any] | None) -> Place | None:
    if not raw:
        return None
    kind = str(raw.get("kind") or "associated").strip().lower()
    if kind not in PLACE_KINDS:
        kind = "associated"
    municipio = str(raw.get("municipio") or raw.get("city") or "").strip()
    uf = _norm_uf(str(raw.get("uf") or raw.get("estado") or ""))
    if not municipio and not uf:
        return None
    return Place(
        kind=kind,
        municipio=municipio,
        uf=uf,
        start=str(raw.get("start") or raw.get("de") or ""),
        end=str(raw.get("end") or raw.get("ate") or ""),
        source=str(raw.get("source") or ""),
        role=str(raw.get("role") or ""),
        confidence=float(raw.get("confidence") or 0.5),
    )


def places_from_attrs(attrs: dict[str, Any] | None) -> list[Place]:
    out: list[Place] = []
    seen: set[tuple[str, str, str, str]] = set()
    bag = attrs or {}
    for raw in bag.get("places") or []:
        if not isinstance(raw, dict):
            continue
        place = place_from_dict(raw)
        if place is None:
            continue
        key = (place.kind, _norm_city(place.municipio), place.uf, place.role)
        if key in seen:
            continue
        seen.add(key)
        out.append(place)
    kind = str(bag.get("place_kind") or "").strip().lower()
    inferred = place_from_dict(
        {
            "kind": kind if kind in PLACE_KINDS else "associated",
            "municipio": bag.get("municipio"),
            "uf": bag.get("uf"),
            "role": bag.get("place_role") or "",
            "source": bag.get("place_source") or "",
        }
    )
    if inferred is not None:
        key = (inferred.kind, _norm_city(inferred.municipio), inferred.uf, inferred.role)
        if key not in seen:
            out.append(inferred)
    return out


def infer_place(*, municipio: str = "", uf: str = "", role: str, source: str = "", kind: str = "associated") -> Place | None:
    return place_from_dict(
        {"kind": kind, "municipio": municipio, "uf": uf, "role": role, "source": source}
    )


def residences(places: Iterable[Place]) -> list[Place]:
    return [p for p in places if p.kind == "residence"]


def residence_conflict(left: Iterable[Place], right: Iterable[Place]) -> Place | None:
    for a in residences(left):
        for b in residences(right):
            if a.uf and b.uf and a.uf != b.uf and periods_overlap(a, b):
                return b
    return None


def snap_from_fields(fields: dict[str, str] | None, *, places: list[Place] | None = None, companies: Iterable[str] = ()) -> PersonSnap:
    bag = {str(k).upper(): str(v or "").strip() for k, v in (fields or {}).items() if str(v or "").strip()}
    emails = {bag["EMAIL"].lower()} if bag.get("EMAIL") else set()
    phone = only_digits(bag.get("PHONE") or "")
    user = (bag.get("USERNAME") or "").lstrip("@").casefold()
    return PersonSnap(
        name=bag.get("NAME") or "",
        emails=emails,
        phones={phone} if len(phone) >= 8 else set(),
        usernames={user} if user else set(),
        birth=bag.get("BIRTHDATE") or bag.get("NASCIMENTO") or "",
        companies={collapse_name(c) for c in companies if collapse_name(c)},
        cargo=bag.get("CARGO") or "",
        places=list(places or []),
        relatives={collapse_name(bag[k]) for k in ("FATHER", "MOTHER") if bag.get(k)},
    )


def snap_from_profile(profile: TargetProfile, **kwargs: Any) -> PersonSnap:
    base = snap_from_fields(
        {
            "NAME": profile.name,
            "EMAIL": next(iter(profile.emails), ""),
            "PHONE": next(iter(profile.phones), ""),
            "BIRTHDATE": profile.birth,
        },
        **kwargs,
    )
    return base


def _phone_tail(value: str) -> str:
    digits = only_digits(value)
    return digits[-8:] if len(digits) >= 8 else digits


def score_identity(target: PersonSnap, candidate: PersonSnap) -> MatchResult:
    signals: list[MatchSignal] = []

    def add(key: str, points: float, why: str, polarity: str = "plus") -> None:
        signals.append(MatchSignal(key=key, points=points, why=why, polarity=polarity))

    if names_match(target.name, candidate.name) and target.name:
        weight = 8 if is_weak_name(target.name) else 25
        add("nome", weight, "Nome completo coincide (normalizado).")
    elif names_same_person(target.name, candidate.name) and target.name:
        add("nome_parcial", 15, "Nome cabe no outro (três ou mais termos).")
    elif target.name and candidate.name and name_tokens(target.name) and name_tokens(candidate.name):
        add("nome_fraco", 2, "Só o nome se parece — pouco poder discriminatório.")

    shared_mail = target.emails & {e.lower() for e in candidate.emails}
    if shared_mail:
        add("email", 60, f"Mesmo e-mail ({next(iter(shared_mail))}).")

    target_phones = {_phone_tail(p) for p in target.phones if _phone_tail(p)}
    cand_phones = {_phone_tail(p) for p in candidate.phones if _phone_tail(p)}
    if target_phones & cand_phones:
        add("telefone", 60, "Mesmo telefone completo.")

    shared_user = {u.lstrip("@").casefold() for u in target.usernames} & {
        u.lstrip("@").casefold() for u in candidate.usernames
    }
    if shared_user:
        user = next(iter(shared_user))
        rarity = username_rarity(user)
        add("username", round(45 * rarity, 1), f"Mesmo @user ({user}).")

    shared_co = {collapse_name(c) for c in target.companies} & {collapse_name(c) for c in candidate.companies}
    if shared_co:
        add("empresa", 25, f"Mesma empresa ({next(iter(shared_co))}).")

    if target.cargo and candidate.cargo and collapse_name(target.cargo) == collapse_name(candidate.cargo):
        add("cargo", 15, "Mesmo cargo.")

    ty, cy = _year(target.birth), _year(candidate.birth)
    if ty and cy:
        if abs(ty - cy) >= 8:
            add("nascimento", -40, f"Ano de nascimento incompatível ({ty} vs {cy}).", "minus")
        elif abs(ty - cy) <= 1:
            add("idade", 8, "Mesma faixa etária.")

    shared_rel = {collapse_name(r) for r in target.relatives} & {collapse_name(r) for r in candidate.relatives}
    if shared_rel:
        add("parente", 15, "Parente ou associado em comum.")

    conflict = residence_conflict(target.places, candidate.places)
    if conflict:
        add(
            "residencia",
            -20,
            f"Duas residências permanentes em UFs diferentes no mesmo período ({conflict.label()}).",
            "minus",
        )
    else:
        t_res = residences(target.places)
        c_res = residences(candidate.places)
        if t_res and c_res and any(
            _norm_city(a.municipio) and _norm_city(a.municipio) == _norm_city(b.municipio)
            for a in t_res
            for b in c_res
        ):
            add("residencia", 15, "Mesma residência atual.")
        elif t_res and c_res and any(a.uf and a.uf == b.uf for a in t_res for b in c_res):
            add("residencia_uf", 8, "Mesma UF de residência (histórico compatível).")

        assoc_roles = {"processo", "imovel", "veiculo", "evento", "empresa"}
        for place in candidate.places:
            if place.kind == "residence":
                continue
            if place.role in assoc_roles or place.kind in {"associated", "historical"}:
                add(
                    "lugar_associado",
                    0,
                    f"{place.role or place.kind} em {place.label()} — associação, não residência.",
                    "zero",
                )

    raw = sum(s.points for s in signals)
    identity = int(max(0, min(100, round(raw))))
    labels = [*target.sources, *candidate.sources]
    reliability = round(
        sum(source_reliability(item) for item in labels) / len(labels), 2
    ) if labels else 0.55
    cons = [s.why for s in signals if s.polarity == "minus"]
    claim = claim_confidence(independent=max(target.independent_origins, candidate.independent_origins), contradictions=len(cons))
    return MatchResult(
        identity_match=identity,
        source_reliability=reliability,
        claim_confidence=claim,
        band=band_for_score(identity),
        suggested_status=suggested_status(identity, contradictions=len(cons)),
        reasons=[s.why for s in signals if s.polarity == "plus"],
        contradictions=cons,
        neutrals=[s.why for s in signals if s.polarity == "zero"],
        signals=signals,
    )


def apply_match_attrs(entity: Any, result: MatchResult, places: list[Place] | None = None) -> None:
    attrs = dict(getattr(entity, "attrs", None) or {})
    attrs["identity_match"] = result.identity_match
    attrs["source_reliability"] = result.source_reliability
    attrs["claim_confidence"] = result.claim_confidence
    attrs["match_reasons"] = result.reasons[:8]
    attrs["match_contradictions"] = result.contradictions[:8]
    attrs["match_neutrals"] = result.neutrals[:8]
    attrs["match_band"] = result.band
    if places is not None:
        attrs["places"] = [asdict(item) for item in places]
    explicit = str(attrs.get("status") or "").strip().lower()
    if getattr(entity, "is_seed", False) or explicit in {"confirmed", "false", "contested"}:
        entity.attrs = attrs
        return
    status = result.suggested_status
    if explicit == "unconfirmed" and status == "false" and not result.contradictions:
        status = "unconfirmed"
    attrs["status"] = status
    if result.suggested_status == "unconfirmed":
        attrs.setdefault("motivo", "Score abaixo do limiar do dossiê; revisar.")
    elif result.suggested_status == "false":
        attrs.setdefault("motivo", "Correspondência fraca — possível homônimo.")
    elif result.suggested_status == "probable":
        attrs.setdefault("motivo", "Correspondência provável; o analista confirma.")
    entity.attrs = attrs
    entity.confidence = max(0.05, min(0.89, result.identity_match / 100))


def can_absorb_by_name(extra: Any) -> bool:
    """Nome igual não funde. Só ID forte compartilhado (CPF) autoriza absorb."""
    status = entity_status(extra)
    if status in {"unconfirmed", "false", "contested"}:
        return False
    match = extra.attrs.get("identity_match") if getattr(extra, "attrs", None) else None
    if match is None:
        return False
    return int(match) >= DOSSIER_MATCH_MIN and status in {"confirmed", "probable"}


def identity_queue_rows(entities: Iterable[Any]) -> list[dict[str, Any]]:
    buckets = {key: {"key": key, "label": label, "rows": []} for key, label in QUEUE_BUCKETS}
    for entity in entities:
        if getattr(entity, "entity_type", "") != "PERSON":
            continue
        status = entity_status(entity)
        if status == "contested":
            status = "unconfirmed"
        if status not in buckets:
            status = "unconfirmed" if not getattr(entity, "is_seed", False) else "confirmed"
        if getattr(entity, "is_seed", False) and status not in {"false", "contested"}:
            status = "confirmed"
        attrs = getattr(entity, "attrs", None) or {}
        buckets[status]["rows"].append(
            {
                "id": entity.id,
                "name": entity.display_name,
                "match": int(attrs.get("identity_match") or 0),
                "reasons": list(attrs.get("match_reasons") or [])[:3],
                "contradictions": list(attrs.get("match_contradictions") or [])[:2],
                "status": status,
                "seed": bool(getattr(entity, "is_seed", False)),
            }
        )
    for bucket in buckets.values():
        bucket["rows"].sort(key=lambda row: (-int(row["match"]), row["name"]))
    return list(buckets.values())


def geo_profile(places: Iterable[Place]) -> list[dict[str, Any]]:
    by_uf: dict[str, dict[str, Any]] = {}
    for place in places:
        uf = place.uf or "?"
        row = by_uf.setdefault(uf, {"uf": uf, "weight": 0, "items": []})
        bump = 12 if place.kind == "residence" else 6 if place.kind == "historical" else 4
        row["weight"] += bump
        row["items"].append(place)
    ranked = sorted(by_uf.values(), key=lambda row: -row["weight"])
    total = sum(row["weight"] for row in ranked) or 1
    for row in ranked:
        row["share"] = round(100 * row["weight"] / total)
        row["items"] = [asdict(item) if isinstance(item, Place) else item for item in row["items"]]
    return ranked
