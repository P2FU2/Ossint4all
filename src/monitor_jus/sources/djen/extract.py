"""Extração de campos de uma comunicação DJEN (contrato Comunica API)."""

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


def _collect_from_destinatarioadvogados(
    payload: dict[str, Any],
) -> tuple[list[str], list[CanonicalOab]]:
    names: list[str] = []
    oabs: list[CanonicalOab] = []
    rows = payload.get("destinatarioadvogados")
    if not isinstance(rows, list):
        return names, oabs
    for row in rows:
        if not isinstance(row, dict):
            continue
        adv = row.get("advogado") if isinstance(row.get("advogado"), dict) else row
        nome = adv.get("nome")
        if isinstance(nome, str) and nome.strip():
            names.append(nome.strip())
        numero = adv.get("numero_oab") or adv.get("numeroOab")
        uf = adv.get("uf_oab") or adv.get("ufOab")
        if numero:
            try:
                oabs.append(
                    canonicalize_oab(
                        str(numero),
                        default_state=str(uf).upper() if uf else None,
                    )
                )
            except OabCanonicalizeError:
                pass
    return names, oabs


def _collect_party_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("destinatarios", "partes"):
        val = payload.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
                elif isinstance(item, dict):
                    n = item.get("nome") or item.get("name")
                    if isinstance(n, str) and n.strip():
                        names.append(n.strip())
    return names


def extract_communication(payload: dict[str, Any]) -> dict[str, Any]:
    text = _first_str(payload, ("texto", "conteudo", "body", "text")) or ""
    court = _first_str(payload, ("siglaTribunal", "tribunal", "sigla"))

    # Preferir CNJ mascarado; fallback dígitos / texto
    process_raw = _first_str(
        payload,
        (
            "numeroprocessocommascara",
            "numero_processo",
            "numeroProcesso",
            "processo",
            "cnj",
        ),
    )
    if not process_raw:
        m = _CNJ_IN_TEXT.search(text)
        if m:
            process_raw = m.group(0)
    parts = normalize_cnj(process_raw or "")
    process_number = parts.numero_formatado if parts else process_raw

    # id numérico da comunicação é estável → DJEN:{id}
    external_id = _first_str(payload, ("id", "hash", "numeroComunicacao"))

    availability = _first_str(
        payload,
        (
            "data_disponibilizacao",
            "datadisponibilizacao",
            "dataDisponibilizacao",
        ),
    )
    publication = _first_str(payload, ("dataPublicacao", "data_publicacao"))
    comm_type = _first_str(
        payload,
        ("tipoComunicacao", "tipoDocumento", "meio", "meiocompleto"),
    ) or "COMUNICACAO"

    lawyer_names, structured_oabs = _collect_from_destinatarioadvogados(payload)
    lawyer_names.extend(_collect_party_names(payload))

    oabs: list[CanonicalOab] = list(structured_oabs)
    oabs.extend(extract_oabs_from_text(text, default_state=None))

    uniq_oabs: dict[str, CanonicalOab] = {}
    for o in oabs:
        uniq_oabs[o.canonical or f"{o.number}:{o.state}:{o.suffix}"] = o

    link = _first_str(payload, ("link", "url", "official_url"))

    return {
        "external_id": external_id,
        "process_number": process_number,
        "court": court.upper() if court else None,
        "communication_type": comm_type,
        "availability_date": availability,
        "publication_date": publication,
        "raw_text": text,
        "lawyer_names": list(dict.fromkeys(lawyer_names)),
        "oabs": list(uniq_oabs.values()),
        "parties": list(dict.fromkeys(_collect_party_names(payload))),
        "source_link": link,
        "hash": payload.get("hash"),
        "nome_orgao": _first_str(payload, ("nomeOrgao",)),
        "nome_classe": _first_str(payload, ("nomeClasse",)),
    }
