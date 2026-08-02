"""OpenRouter com fallback + modo sem IA."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import OpenAI
from sqlalchemy.orm import Session

from monitor_jus.ai.deterministic import deterministic_summary
from monitor_jus.config import Settings, get_settings
from monitor_jus.db.models import AiGeneration, Event
from monitor_jus.http_client import RateLimitedClient
from monitor_jus.logging_setup import get_logger

logger = get_logger(__name__)
PROMPT_VERSION = "1.0.0"

_ai_available: bool | None = None


def check_openrouter(settings: Settings | None = None) -> dict[str, Any]:
    """Startup check — não bloqueia o serviço."""
    global _ai_available
    settings = settings or get_settings()
    if not settings.openrouter_api_key:
        _ai_available = False
        return {"ok": False, "reason": "OPENROUTER_API_KEY ausente"}
    try:
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout_seconds,
        )
        # list models é leve; se falhar, marca indisponível
        models = client.models.list()
        ids = {m.id for m in (models.data or [])}
        primary_ok = settings.openrouter_model in ids or True  # catálogo pode filtrar
        _ai_available = True
        return {
            "ok": True,
            "primary": settings.openrouter_model,
            "primary_listed": settings.openrouter_model in ids,
            "fallbacks": settings.openrouter_fallback_list,
        }
    except Exception as exc:  # noqa: BLE001
        _ai_available = False
        logger.warning("openrouter_unavailable", extra={"extra": {"error": str(exc)}})
        return {"ok": False, "reason": str(exc)}


def is_ai_available() -> bool:
    return bool(_ai_available)


def _load_prompt(settings: Settings) -> str:
    path = Path(__file__).parent / "prompts" / "summarize_v1.txt"
    return path.read_text(encoding="utf-8")


def summarize_event(session: Session, event: Event, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    text = f"{event.title or ''}\n{event.description or ''}".strip()
    if not text:
        summary = deterministic_summary(event)
        session.add(
            AiGeneration(
                id=str(uuid4()),
                event_id=event.id,
                model=None,
                prompt_version=PROMPT_VERSION,
                input_text=text,
                output_text=summary,
                fallback_used=True,
                status="AI_UNAVAILABLE",
            )
        )
        return summary

    if _ai_available is False or not settings.openrouter_api_key:
        summary = deterministic_summary(event)
        session.add(
            AiGeneration(
                id=str(uuid4()),
                event_id=event.id,
                model=None,
                prompt_version=PROMPT_VERSION,
                input_text=text,
                output_text=summary,
                fallback_used=True,
                status="AI_UNAVAILABLE",
            )
        )
        return summary

    prompt_tmpl = _load_prompt(settings)
    prompt = (
        prompt_tmpl.replace("{{priority}}", event.priority or "media")
        .replace("{{numero_cnj}}", event.numero_cnj or "n/d")
        .replace("{{event_type}}", event.event_type)
        .replace("{{text}}", text)
    )

    models = [settings.openrouter_model, *settings.openrouter_fallback_list]
    client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.openrouter_timeout_seconds,
    )
    # concurrency via simple semaphore in RateLimitedClient not used for openai SDK;
    # rely on OPENROUTER_MAX_CONCURRENCY externally if needed
    last_err: Exception | None = None
    for model in models:
        for attempt in range(1, settings.openrouter_max_retries + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Assistente jurídico cuidadoso."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                content = (resp.choices[0].message.content or "").strip()
                if event.possible_deadline_flag and "Possível prazo identificado" not in content:
                    content += (
                        "\nPossível prazo identificado. Necessária validação jurídica "
                        "na publicação oficial."
                    )
                session.add(
                    AiGeneration(
                        id=str(uuid4()),
                        event_id=event.id,
                        model=model,
                        prompt_version=PROMPT_VERSION,
                        input_text=prompt,
                        output_text=content,
                        fallback_used=model != settings.openrouter_model,
                        status="OK",
                    )
                )
                return content
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning(
                    "openrouter_retry",
                    extra={"extra": {"model": model, "attempt": attempt, "err": str(exc)}},
                )

    summary = deterministic_summary(event)
    session.add(
        AiGeneration(
            id=str(uuid4()),
            event_id=event.id,
            model=None,
            prompt_version=PROMPT_VERSION,
            input_text=prompt,
            output_text=summary,
            fallback_used=True,
            status="AI_UNAVAILABLE",
        )
    )
    logger.error("openrouter_failed", extra={"extra": {"err": str(last_err)}})
    return summary
