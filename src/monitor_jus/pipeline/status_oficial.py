"""Situação oficial do processo (capa / inferência de movimentação)."""

from __future__ import annotations

import re
from typing import Any

# Chaves canônicas para filtro e exibição (alinhadas a e-SAJ / tribunais)
SITUACAO_LABELS: dict[str, str] = {
    "extinto": "Extinto",
    "cancelado": "Cancelado",
    "julgado": "Julgado",
    "encerrado": "Encerrado",
    "em_grau_de_recurso": "Em grau de recurso",
    "arquivado": "Arquivado",
    "baixado": "Baixado",
    "suspenso": "Suspenso",
    "em_tramitacao": "Em tramitação",
    "sem_informacao": "Sem informação",
}

# Sinais fortes de capa (badge e-SAJ / modal cposg / movimentos terminais)
_TERMINAL_KEYS = frozenset(
    {"extinto", "cancelado", "julgado", "encerrado", "arquivado", "baixado", "suspenso"}
)

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

    # Cancelamento (badge e-SAJ "Cancelado", incidente/distribuição cancelados)
    if re.search(
        r"\bcancelad[oa]\b|cancelamento\s+da\s+distribui|incidente\s+processual\s+cancelad",
        blob,
    ):
        return "cancelado"
    if "grau de recurso" in blob or "em grau de recurso" in blob:
        return "em_grau_de_recurso"
    if re.search(r"\bjulgad[oa]\b", blob) or "trânsito em julgado" in blob or "transito em julgado" in blob:
        return "julgado"
    # Modal e-SAJ cposg: "2º Grau Encerrado" / "Encerrado"
    if re.search(r"\bencerrad[oa]\b|grau\s+encerrado|2[oº°]?\s*grau\s+encerrado", blob):
        return "encerrado"
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
        # Preferir sinais fortes de encerramento / recurso / badge e-SAJ
        if key in _TERMINAL_KEYS or key == "em_grau_de_recurso":
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


def _label_from_strong_key(key: str, raw: str) -> str:
    if key == "arquivado":
        if "definitiv" in raw.lower() or "extin" in raw.lower():
            return "Extinto"
        return "Arquivado"
    if key in SITUACAO_LABELS and key != "em_tramitacao":
        return SITUACAO_LABELS[key]
    return raw


def extract_status_from_payload(payload: dict[str, Any] | None) -> str | None:
    """Extrai o melhor status possível do payload (DataJud / DJEN / legado)."""
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
    datajud = payload.get("datajud") if isinstance(payload.get("datajud"), dict) else {}
    if datajud:
        candidates.extend(
            [
                datajud.get("situacao"),
                datajud.get("status"),
                datajud.get("last_movement_name"),
            ]
        )
        for inst in datajud.get("instances") or []:
            if isinstance(inst, dict):
                candidates.append(inst.get("last_movement_name"))
                candidates.append(inst.get("situacao"))
    tags = payload.get("tags") or payload.get("labels")
    if isinstance(tags, list):
        candidates.extend(tags)
    elif isinstance(tags, str):
        candidates.append(tags)

    # Preferir candidatos com chave terminal (Cancelado, Suspenso, …)
    weak: str | None = None
    for c in candidates:
        cleaned = clean_status_text(c)
        if not cleaned:
            continue
        key = normalize_situacao_key(cleaned)
        if key in _TERMINAL_KEYS or key == "em_grau_de_recurso":
            return _label_from_strong_key(key, cleaned)
        if weak is None:
            weak = cleaned

    last_step = payload.get("last_step")
    if isinstance(last_step, dict):
        cleaned = clean_status_text(
            last_step.get("content") or last_step.get("nome") or last_step.get("name")
        )
        if cleaned:
            key = normalize_situacao_key(cleaned)
            if key in _TERMINAL_KEYS or key == "em_grau_de_recurso":
                return _label_from_strong_key(key, cleaned)
            # last_step genérico (juntada) — tentar steps antes de aceitar
            inferred = _from_steps(payload)
            if inferred:
                return inferred
            return cleaned

    inferred = _from_steps(payload)
    if inferred:
        return inferred
    return weak


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
            if key_mv in _TERMINAL_KEYS or key_mv == "em_grau_de_recurso":
                text = _label_from_strong_key(key_mv, mv)
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
