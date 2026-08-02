"""Resumo determinístico quando a IA está indisponível."""

from __future__ import annotations

from monitor_jus.db.models import Event


def deterministic_summary(event: Event) -> str:
    parts = [
        f"Tipo: {event.event_type}.",
        f"Processo: {event.numero_cnj or 'não informado'}.",
        f"Tribunal: {event.tribunal or 'não informado'}.",
        f"Título: {event.title or '—'}.",
    ]
    if event.description:
        desc = event.description.strip()
        if len(desc) > 400:
            desc = desc[:400] + "…"
        parts.append(f"Detalhe: {desc}")
    if event.possible_deadline_flag:
        parts.append(
            "Possível prazo identificado. Necessária validação jurídica na publicação oficial."
        )
    if event.requires_name_validation:
        parts.append("Correspondência por nome — requer validação.")
    parts.append(f"Prioridade (regras): {event.priority}.")
    return " ".join(parts)
