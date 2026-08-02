"""Envio de e-mail via Resend com concorrência limitada."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import resend

from monitor_jus.config import Settings, get_settings
from monitor_jus.exceptions import FailedAuthentication, FailedSource
from monitor_jus.logging_setup import get_logger
from monitor_jus.metrics import incr, observe_latency

logger = get_logger(__name__)
_sem: threading.Semaphore | None = None


def _get_sem(settings: Settings) -> threading.Semaphore:
    global _sem
    if _sem is None:
        _sem = threading.Semaphore(settings.resend_max_concurrency)
    return _sem


def send_html_email(
    *,
    subject: str,
    html: str,
    settings: Settings | None = None,
    outbox_path: Path | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if outbox_path:
        outbox_path.parent.mkdir(parents=True, exist_ok=True)
        outbox_path.write_text(html, encoding="utf-8")

    if not settings.resend_api_key or not settings.email_from or not settings.email_to:
        incr("delivery_failures")
        raise FailedSource("Resend/EMAIL não configurados")

    recipients = [e.strip() for e in settings.email_to.split(",") if e.strip()]
    params: dict[str, Any] = {
        "from": settings.email_from,
        "to": recipients,
        "subject": subject,
        "html": html,
    }

    sem = _get_sem(settings)
    started = time.perf_counter()
    sem.acquire()
    try:
        resend.api_key = settings.resend_api_key
        result = resend.Emails.send(params)
        observe_latency("resend", (time.perf_counter() - started) * 1000, "send")
        # SDK retorna dict-like com id; erros levantam exceção
        msg_id = None
        if isinstance(result, dict):
            msg_id = result.get("id")
        else:
            msg_id = getattr(result, "id", None)
        return {"status_code": 200, "message_id": msg_id}
    except Exception as exc:  # noqa: BLE001
        incr("delivery_failures")
        msg = str(exc).lower()
        if "unauthorized" in msg or "401" in msg or "403" in msg or "api key" in msg:
            raise FailedAuthentication(f"Resend auth failed: {exc}") from exc
        raise FailedSource(f"Resend: {exc}") from exc
    finally:
        sem.release()
