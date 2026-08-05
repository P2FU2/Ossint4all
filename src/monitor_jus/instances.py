"""Graus de jurisdição no monitoramento.

No direito brasileiro há duas instâncias fundamentais (1º e 2º grau).
Na prática o percurso pode chegar aos tribunais superiores (STJ, TST, TSE, STM)
e ao STF — o que se costuma chamar de 3ª e 4ª instância, embora não sejam
“graus” no mesmo sentido orgânico do processo de conhecimento.

O sistema trata isso assim:
- capa ativa = instância mais alta conhecida para aquele CNJ/relacionados;
- G1 e G2 do mesmo número CNJ = duas capas do mesmo processo;
- STJ/STF etc. costumam ter CNJ próprio → process_relations.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from monitor_jus.validators import normalize_cnj


class InstanceLevel(IntEnum):
    UNKNOWN = 0
    PRIMEIRO_GRAU = 1
    SEGUNDO_GRAU = 2
    SUPERIOR = 3  # STJ, TST, TSE, STM — “terceira instância” na prática
    STF = 4  # controle concentrado / RE — “quarta instância” coloquial


INSTANCE_LABELS: dict[InstanceLevel, str] = {
    InstanceLevel.UNKNOWN: "Instância não informada",
    InstanceLevel.PRIMEIRO_GRAU: "1º grau",
    InstanceLevel.SEGUNDO_GRAU: "2º grau",
    InstanceLevel.SUPERIOR: "Tribunal superior",
    InstanceLevel.STF: "STF",
}

_SUPERIOR_COURTS = {"STJ", "TST", "TSE", "STM"}


def instance_label(level: InstanceLevel | int | None) -> str:
    try:
        return INSTANCE_LABELS[InstanceLevel(int(level or 0))]
    except (ValueError, KeyError):
        return INSTANCE_LABELS[InstanceLevel.UNKNOWN]


def instance_from_cnj_court(
    process_number: str | None,
    court: str | None = None,
    *,
    grau: str | None = None,
) -> InstanceLevel:
    """Classifica instância por CNJ (segmento), sigla e grau DataJud."""
    court_u = (court or "").strip().upper()
    if court_u == "STF":
        return InstanceLevel.STF
    if court_u in _SUPERIOR_COURTS:
        return InstanceLevel.SUPERIOR

    parts = normalize_cnj(process_number or "")
    if parts:
        seg = parts.segmento
        if seg == "1":
            return InstanceLevel.STF
        if seg == "3":  # STJ
            return InstanceLevel.SUPERIOR
        if seg == "7":  # TSE / eleitoral superior approx
            # 7.xx pode ser TRE (2º) ou TSE — TR=00 costuma ser TSE
            if parts.tribunal == "00":
                return InstanceLevel.SUPERIOR
        if seg == "5" and parts.tribunal == "00":
            return InstanceLevel.SUPERIOR  # TST
        if seg == "6" and parts.tribunal == "00":
            return InstanceLevel.SUPERIOR  # STM

    g = (grau or "").strip().upper()
    if g in {"G2", "2", "2G", "TR", "TU"} or (g.startswith("G") and "2" in g):
        return InstanceLevel.SEGUNDO_GRAU
    if g in {"G1", "1", "1G", "JE"} or (g.startswith("G") and "1" in g):
        return InstanceLevel.PRIMEIRO_GRAU

    # Tribunais de 2º grau sem grau explícito
    if court_u.startswith("TRF") or court_u.startswith("TRT") or (
        court_u.startswith("TJ") and g == ""
    ):
        # TJ/TRF sem grau → desconhecido; não assumir 2º
        return InstanceLevel.UNKNOWN

    return InstanceLevel.UNKNOWN


def instance_rank_from_datajud_hit(source: dict[str, Any]) -> int:
    """Ranking para escolher capa ativa entre hits do mesmo CNJ."""
    level = instance_from_cnj_court(
        None,
        str(source.get("tribunal") or "") or None,
        grau=str(source.get("grau") or "") or None,
    )
    # Fallback: G2 > G1 pelo campo grau
    if level == InstanceLevel.UNKNOWN:
        g = str(source.get("grau") or "").upper()
        if "2" in g:
            return int(InstanceLevel.SEGUNDO_GRAU)
        if "1" in g:
            return int(InstanceLevel.PRIMEIRO_GRAU)
    return int(level)


def summarize_instances(instances: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumo amigável da pilha de instâncias conhecidas."""
    levels: list[InstanceLevel] = []
    for row in instances:
        lvl = instance_from_cnj_court(
            row.get("process_number"),
            row.get("tribunal") or row.get("court"),
            grau=row.get("grau"),
        )
        if lvl != InstanceLevel.UNKNOWN:
            levels.append(lvl)
        elif row.get("grau"):
            levels.append(
                InstanceLevel.SEGUNDO_GRAU
                if "2" in str(row.get("grau")).upper()
                else InstanceLevel.PRIMEIRO_GRAU
            )

    unique = sorted(set(levels), reverse=True)
    active = unique[0] if unique else InstanceLevel.UNKNOWN
    return {
        "active_level": int(active),
        "active_label": instance_label(active),
        "levels": [int(x) for x in unique],
        "labels": [instance_label(x) for x in sorted(unique)],
        "has_fundamental_pair": (
            InstanceLevel.PRIMEIRO_GRAU in levels and InstanceLevel.SEGUNDO_GRAU in levels
        ),
        "reached_superior": any(x >= InstanceLevel.SUPERIOR for x in levels),
        "note": (
            "1º e 2º grau são as instâncias fundamentais; "
            "tribunais superiores e STF ampliam o percurso recursal."
        ),
    }
