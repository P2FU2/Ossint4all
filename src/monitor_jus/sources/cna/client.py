"""Stub CNA SOAP — validação local contra critérios na v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from monitor_jus.canonical_oab import CanonicalOab
from monitor_jus.config import Settings, get_settings, load_monitoramentos
from monitor_jus.matching import MatchStatus, MonitoredCriterion, _name_is_full_match


@dataclass(frozen=True)
class LawyerValidation:
    status: str
    detail: str | None = None


def _criteria_from_yaml(settings: Settings) -> list[MonitoredCriterion]:
    cfg = load_monitoramentos(settings)
    mon = cfg.get("monitoramentos") or {}
    out: list[MonitoredCriterion] = []
    for oab in mon.get("oabs") or []:
        if oab.get("ativo") is False:
            continue
        sec = str(oab.get("seccional", "")).upper()
        numero = str(oab.get("numero", ""))
        sufixo = oab.get("sufixo")
        if sufixo:
            numero = f"{numero}{sufixo}"
        out.append(
            MonitoredCriterion(
                criterion_type="OAB",
                value=f"{sec}:{numero}",
                label=oab.get("responsavel"),
                meta={"seccional": sec, "numero": numero},
            )
        )
    for nome in mon.get("nomes") or []:
        if isinstance(nome, dict):
            if nome.get("ativo") is False:
                continue
            text = str(nome.get("nome", "")).strip()
            req = bool(nome.get("requires_secondary_evidence", True))
        else:
            text = str(nome).strip()
            req = True
        if text:
            out.append(
                MonitoredCriterion(
                    criterion_type="NOME",
                    value=text,
                    label=text,
                    requires_secondary_evidence=req,
                )
            )
    return out


def local_exact_oab_match(
    oab: CanonicalOab,
    criteria: list[MonitoredCriterion],
) -> bool:
    for crit in criteria:
        crit_oab = crit.oab
        if crit_oab and oab.matches_criterion(crit_oab):
            return True
    return False


async def validate_lawyer(
    oab: CanonicalOab | None,
    lawyer_name: str | None,
    monitored_criteria: list[MonitoredCriterion] | None = None,
    *,
    settings: Settings | None = None,
) -> LawyerValidation:
    """
    Fora do caminho crítico.
    Nome isolado nunca resulta em MATCHED_LOCAL.
    """
    settings = settings or get_settings()
    criteria = monitored_criteria or _criteria_from_yaml(settings)

    if oab and local_exact_oab_match(oab, criteria):
        return LawyerValidation(status="MATCHED_LOCAL", detail=oab.canonical)

    # Nome sozinho → nunca MATCHED_LOCAL
    if lawyer_name and not oab:
        for crit in criteria:
            if crit.criterion_type == "NOME" and _name_is_full_match(lawyer_name, crit.value):
                return LawyerValidation(
                    status=MatchStatus.PROBABLE_NAME.value,
                    detail="nome completo sem OAB",
                )
        return LawyerValidation(status=MatchStatus.AMBIGUOUS.value, detail="nome sem evidência")

    if not settings.cna_enabled:
        return LawyerValidation(status=MatchStatus.PENDING_CNA.value, detail="CNA desabilitado")

    # Stub: futuro SOAP
    return LawyerValidation(status=MatchStatus.PENDING_CNA.value, detail="CNA stub")
