"""Extração de campos de uma comunicação DJEN."""

from __future__ import annotations

import re
from typing import Any

from monitor_jus.canonical_oab import CanonicalOab, canonicalize_oab, OabCanonicalizeError
from monitor_jus.matching import extract_oabs_from_text
from monitor_jus.validators import normalize_cnj

_CNJ_IN_TEXT = re.compile(
    r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b"
)


def _first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, (int, float)):
            return str(val)
    return None


def extract_communication(payload: dict[str, Any]) -> dict[str, Any]:
    text = _first_str(
        payload,
        ("texto", "conteudo", "conteudoPublicacao", "inteiroTeor", "body", "text", "mensagem"),
    ) or ""
    court = _first_str(
        payload,
        ("siglaTribunal", "tribunal", "court", "sigla"),
    )
    process_raw = _first_str(
        payload,
        ("numeroProcesso", "numero_processo", "processo", "numero_cnj", "cnj"),
    )
    if not process_raw:
        m = _CNJ_IN_TEXT.search(text)
        if m:
            process_raw = m.group(0)
    parts = normalize_cnj(process_raw or "")
    process_number = parts.numero_formatado if parts else process_raw

    external_id = _first_str(
        payload,
        ("id", "idComunicacao", "codigo", "hash", "uuid"),
    )
    availability = _first_str(
        payload,
        ("dataDisponibilizacao", "data_disponibilizacao", "disponibilizacao", "availabilityDate"),
    )
    publication = _first_str(
        payload,
        ("dataPublicacao", "data_publicacao", "publicationDate"),
    )
    comm_type = _first_str(
        payload,
        ("tipoComunicacao", "tipo", "type", "meio"),
    ) or "COMUNICACAO"

    lawyer_names: list[str] = []
    for key in ("nomeAdvogado", "advogados", "destinatarios", "partes"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            lawyer_names.append(val.strip())
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    lawyer_names.append(item.strip())
                elif isinstance(item, dict):
                    n = item.get("nome") or item.get("name")
                    if isinstance(n, str) and n.strip():
                        lawyer_names.append(n.strip())

    oabs: list[CanonicalOab] = extract_oabs_from_text(text, default_state=None)
    # campos estruturados
    oab_num = _first_str(payload, ("numeroOab", "oab", "oabNumero"))
    oab_uf = _first_str(payload, ("ufOab", "uf", "seccional"))
    if oab_num:
        try:
            oabs.append(
                canonicalize_oab(
                    f"{oab_uf or ''}{oab_num}" if oab_uf else oab_num,
                    default_state=oab_uf,
                )
            )
        except OabCanonicalizeError:
            pass

    # dedupe oabs
    uniq: dict[str, CanonicalOab] = {}
    for o in oabs:
        uniq[o.canonical or f"{o.number}:{o.state}:{o.suffix}"] = o

    return {
        "external_id": external_id,
        "process_number": process_number,
        "court": court.upper() if court else None,
        "communication_type": comm_type,
        "availability_date": availability,
        "publication_date": publication,
        "raw_text": text,
        "lawyer_names": list(dict.fromkeys(lawyer_names)),
        "oabs": list(uniq.values()),
        "parties": lawyer_names,
    }
