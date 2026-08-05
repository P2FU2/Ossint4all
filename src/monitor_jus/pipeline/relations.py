"""Relações processuais (origem / recurso / incidente)."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from monitor_jus.db.models import Process, ProcessRelation
from monitor_jus.logging_setup import get_logger
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)


class RelationType(StrEnum):
    APPEAL_OF = "APPEAL_OF"
    ORIGIN_OF = "ORIGIN_OF"
    RELATED_TO = "RELATED_TO"
    INCIDENT_OF = "INCIDENT_OF"
    DERIVED_FROM = "DERIVED_FROM"
    POSSIBLE_SAME_CASE = "POSSIBLE_SAME_CASE"


class RelationConfidence(StrEnum):
    CONFIRMED_NUMBER = "CONFIRMED_NUMBER"
    CONFIRMED_METADATA = "CONFIRMED_METADATA"
    PROBABLE_TEXT = "PROBABLE_TEXT"
    AMBIGUOUS = "AMBIGUOUS"


_ORIGIN_PATTERNS = [
    re.compile(
        r"(?:processo\s+de\s+origem|n[uú]mero\s+de\s+origem|origin[aá]rio)"
        r"[:\s]+(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:recurso\s+especial|recurso\s+extraordin[aá]rio|agravo|habeas\s+corpus|reclama[cç][aã]o)"
        r".{0,80}?(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})",
        re.IGNORECASE | re.DOTALL,
    ),
]


def maybe_extract_relations(
    session: Session,
    process: Process,
    text: str,
    *,
    source: str,
) -> list[ProcessRelation]:
    created: list[ProcessRelation] = []
    blob = text or ""
    found_numbers: list[tuple[str, RelationConfidence, RelationType]] = []

    for pat in _ORIGIN_PATTERNS:
        for m in pat.finditer(blob):
            parts = normalize_cnj(m.group(1))
            if not parts:
                continue
            if parts.numero_formatado == process.numero_cnj:
                continue
            found_numbers.append(
                (
                    parts.numero_formatado,
                    RelationConfidence.CONFIRMED_NUMBER,
                    RelationType.ORIGIN_OF,
                )
            )

    # CNJs genéricos no texto (provável)
    for m in re.finditer(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b", blob):
        parts = normalize_cnj(m.group(0))
        if not parts or parts.numero_formatado == process.numero_cnj:
            continue
        if any(n == parts.numero_formatado for n, _, _ in found_numbers):
            continue
        found_numbers.append(
            (
                parts.numero_formatado,
                RelationConfidence.PROBABLE_TEXT,
                RelationType.RELATED_TO,
            )
        )

    for numero, confidence, rel_type in found_numbers:
        # Só confirma relação com identificador forte
        if confidence not in {
            RelationConfidence.CONFIRMED_NUMBER,
            RelationConfidence.CONFIRMED_METADATA,
        }:
            continue
        digits = normalize_cnj(numero)
        if not digits:
            continue
        other = session.scalar(select(Process).where(Process.numero_cnj == numero))
        if not other:
            other = Process(
                id=str(uuid4()),
                numero_cnj=numero,
                numero_cnj_digits=digits.numero_digits,
                tribunal=None,
                payload={"discovered_via_relation": process.numero_cnj},
            )
            session.add(other)
            session.flush()

        exists = session.scalar(
            select(ProcessRelation).where(
                ProcessRelation.source_process_id == process.id,
                ProcessRelation.target_process_id == other.id,
                ProcessRelation.relation_type == rel_type.value,
            )
        )
        if exists:
            continue
        rel = ProcessRelation(
            id=str(uuid4()),
            source_process_id=process.id,
            target_process_id=other.id,
            relation_type=rel_type.value,
            evidence_source=source,
            confidence=confidence.value,
        )
        session.add(rel)
        created.append(rel)
        logger.info(
            "process_relation_created",
            extra={
                "extra": {
                    "from": process.numero_cnj,
                    "to": other.numero_cnj,
                    "type": rel_type.value,
                    "confidence": confidence.value,
                }
            },
        )
    session.flush()
    return created
