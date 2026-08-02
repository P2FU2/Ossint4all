"""Situação oficial do processo (capa Judit / inferência de movimentação)."""

from __future__ import annotations

from typing import Any

# Chaves canônicas para filtro e exibição (alinhadas a e-SAJ / tribunais)
SITUACAO_LABELS: dict[str, str] = {
    "extinto": "Extinto",
    "em_grau_de_recurso": "Em grau de recurso",
    "arquivado": "Arquivado",
    "baixado": "Baixado",
    "suspenso": "Suspenso",
    "em_tramitacao": "Em tramitação",
    "sem_informacao": "Sem informação",
}

_PLACEHOLDERS = {
    "",
    "-",
    "---",
    "—",
    "n/d",
    "nd",
    "n.d.",
    "null",
    "none",
    "inconsistente",
    "desconhecido",
    "sem informação",
    "sem informacao",
}


def is_placeholder_status(value: str | None) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _PLACEHOLDERS


def clean_status_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for k in ("name", "nome", "label", "value", "status", "description", "content"):
            if value.get(k):
                return clean_status_text(value.get(k))
        return None
    text = str(value).strip()
    if not text or text.lower() in _PLACEHOLDERS:
        return None
    # templates Judit/e-SAJ às vezes vêm com placeholders literais
    if "#{ato" in text or "#{data" in text:
        return None
    return text


def normalize_situacao_key(text: str | None) -> str:
    """Mapeia texto livre → chave canônica de situação oficial."""
    if is_placeholder_status(text):
        return "sem_informacao"
    blob = (text or "").lower()

    if "grau de recurso" in blob or "em grau de recurso" in blob:
        return "em_grau_de_recurso"
    if "extint" in blob:
        return "extinto"
    if "arquiv" in blob:
        return "arquivado"
    if "baixa definitiva" in blob or "baixado" in blob or blob.strip() == "baixa":
        return "baixado"
    if "suspens" in blob or "sobrestad" in blob:
        return "suspenso"
    if any(
        k in blob
        for k in (
            "tramit",
            "andamento",
            "conclus",
            "juntada",
            "ativo",
            "curso",
            "despacho",
            "intim",
            "aguardando",
            "cumprimento",
            "execução",
            "execucao",
            "distribui",
            "redistribu",
        )
    ):
        return "em_tramitacao"
    # texto útil sem classificação específica → em tramitação (há informação de capa)
    if len(blob) >= 3:
        return "em_tramitacao"
    return "sem_informacao"


def situacao_label(key: str) -> str:
    return SITUACAO_LABELS.get(key, key)


def _from_steps(data: dict[str, Any]) -> str | None:
    """Inferência a partir da última movimentação relevante nos steps."""
    steps = data.get("steps") or data.get("movements") or data.get("timeline") or []
    if not isinstance(steps, list):
        return None
    # do mais recente ao mais antigo
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        content = clean_status_text(
            step.get("content")
            or step.get("nome")
            or step.get("name")
            or step.get("description")
            or step.get("type")
        )
        if not content:
            continue
        key = normalize_situacao_key(content)
        # Preferir sinais fortes de encerramento / recurso
        if key in ("extinto", "arquivado", "baixado", "em_grau_de_recurso", "suspenso"):
            if key == "arquivado":
                # e-SAJ costuma mostrar "Extinto" quando arquivado definitivamente
                low = content.lower()
                if "definitiv" in low or "extin" in low:
                    return "Extinto"
                return "Arquivado"
            return situacao_label(key)
        # se for só juntada/conclusos, continua procurando sinal mais forte
    # última step como fallback descritivo
    for step in reversed(steps):
        if isinstance(step, dict):
            content = clean_status_text(
                step.get("content") or step.get("nome") or step.get("name")
            )
            if content:
                return content
    return None


def extract_status_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Extrai o melhor status possível do JSON Judit."""
    if not isinstance(payload, dict):
        return None

    # aninhamentos comuns
    candidates: list[Any] = [
        payload.get("status"),
        payload.get("situation"),
        payload.get("situacao"),
        payload.get("phase"),
        payload.get("lawsuit_status"),
        payload.get("process_status"),
        payload.get("current_status"),
        payload.get("justice_status"),
    ]
    lawsuit = payload.get("lawsuit")
    if isinstance(lawsuit, dict):
        candidates.extend(
            [
                lawsuit.get("status"),
                lawsuit.get("situation"),
                lawsuit.get("situacao"),
                lawsuit.get("phase"),
            ]
        )
    tags = payload.get("tags") or payload.get("labels")
    if isinstance(tags, list):
        candidates.extend(tags)
    elif isinstance(tags, str):
        candidates.append(tags)

    for c in candidates:
        cleaned = clean_status_text(c)
        if cleaned:
            return cleaned

    last_step = payload.get("last_step")
    if isinstance(last_step, dict):
        cleaned = clean_status_text(
            last_step.get("content") or last_step.get("nome") or last_step.get("name")
        )
        if cleaned:
            key = normalize_situacao_key(cleaned)
            if key in ("extinto", "arquivado", "baixado", "em_grau_de_recurso"):
                if key == "arquivado" and "definitiv" in cleaned.lower():
                    return "Extinto"
                return situacao_label(key) if key != "arquivado" else cleaned
            # last_step genérico (juntada) — tentar steps antes de aceitar
            inferred = _from_steps(payload)
            if inferred:
                return inferred
            return cleaned

    return _from_steps(payload)


def resolve_situacao_oficial(
    situacao: str | None,
    *,
    payload: dict[str, Any] | None = None,
    last_movement: str | None = None,
) -> tuple[str, str]:
    """Retorna (texto_exibicao, chave_filtro)."""
    text = clean_status_text(situacao)
    if not text and payload:
        text = extract_status_from_payload(payload)
    if not text and last_movement:
        mv = clean_status_text(last_movement)
        if mv:
            key_mv = normalize_situacao_key(mv)
            if key_mv == "arquivado" and "definitiv" in mv.lower():
                text = "Extinto"
            elif key_mv in ("extinto", "arquivado", "baixado", "em_grau_de_recurso", "suspenso"):
                text = situacao_label(key_mv) if key_mv != "arquivado" else mv
            else:
                text = mv

    if not text:
        return "—", "sem_informacao"

    key = normalize_situacao_key(text)
    # Exibir rótulo canônico quando reconhecido; senão o texto original
    if key in SITUACAO_LABELS and key != "em_tramitacao":
        return SITUACAO_LABELS[key], key
    if key == "em_tramitacao":
        # manter texto da capa se for descritivo; senão rótulo genérico
        if text and not is_placeholder_status(text) and len(text) > 3:
            # se o texto já é o rótulo canônico
            if text.lower() in {v.lower() for v in SITUACAO_LABELS.values()}:
                return SITUACAO_LABELS[key], key
            return text, key
        return SITUACAO_LABELS[key], key
    return text, key
