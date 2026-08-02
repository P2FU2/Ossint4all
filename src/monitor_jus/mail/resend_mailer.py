"""Envio de e-mail via Resend com concorrência limitada e anexos."""

from __future__ import annotations

import base64
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


def _attachment_from_path(path: Path, *, filename: str | None = None) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "filename": filename or path.name,
        "content": base64.b64encode(data).decode("ascii"),
    }


def _attachment_from_bytes(content: bytes, filename: str) -> dict[str, Any]:
    return {
        "filename": filename,
        "content": base64.b64encode(content).decode("ascii"),
    }


def parse_recipients(raw: str | None) -> list[str]:
    """Separa e-mails por vírgula ou ponto-e-vírgula."""
    if not raw:
        return []
    return [e.strip() for e in str(raw).replace(";", ",").split(",") if e.strip()]


def send_html_email(
    *,
    subject: str,
    html: str,
    settings: Settings | None = None,
    outbox_path: Path | None = None,
    attachments: list[Path | dict[str, Any]] | None = None,
    to: str | None = None,
) -> dict[str, Any]:
    """Envia HTML no body e opcionalmente anexa arquivos (HTML/PDF).

    `to` sobrescreve EMAIL_TO (útil para envio sob demanda pelo painel).
    `attachments` aceita Path ou dict com `filename` + `content` (bytes|str base64).
    """
    settings = settings or get_settings()
    if outbox_path:
        outbox_path.parent.mkdir(parents=True, exist_ok=True)
        outbox_path.write_text(html, encoding="utf-8")

    recipients = parse_recipients(to) or parse_recipients(settings.email_to)
    if not settings.resend_api_key or not settings.email_from or not recipients:
        incr("delivery_failures")
        raise FailedSource("Resend/EMAIL não configurados (from/to)")

    params: dict[str, Any] = {
        "from": settings.email_from,
        "to": recipients,
        "subject": subject,
        "html": html,
    }

    built: list[dict[str, Any]] = []
    for item in attachments or []:
        if isinstance(item, Path):
            if item.is_file():
                built.append(_attachment_from_path(item))
            else:
                logger.warning("attachment_missing", extra={"extra": {"path": str(item)}})
            continue
        if isinstance(item, dict):
            filename = str(item.get("filename") or "anexo.bin")
            content = item.get("content")
            if isinstance(content, (bytes, bytearray)):
                built.append(_attachment_from_bytes(bytes(content), filename))
            elif isinstance(content, str):
                # já em base64 ou texto — se parecer path, não usar
                built.append({"filename": filename, "content": content})
            elif item.get("path"):
                p = Path(str(item["path"]))
                if p.is_file():
                    built.append(_attachment_from_path(p, filename=filename))
    if built:
        params["attachments"] = built

    sem = _get_sem(settings)
    started = time.perf_counter()
    sem.acquire()
    try:
        resend.api_key = settings.resend_api_key
        result = resend.Emails.send(params)
        observe_latency("resend", (time.perf_counter() - started) * 1000, "send")
        msg_id = None
        if isinstance(result, dict):
            msg_id = result.get("id")
        else:
            msg_id = getattr(result, "id", None)
        logger.info(
            "email_sent",
            extra={
                "extra": {
                    "message_id": msg_id,
                    "attachments": [a.get("filename") for a in built],
                }
            },
        )
        return {"status_code": 200, "message_id": msg_id, "attachments": len(built)}
    except Exception as exc:  # noqa: BLE001
        incr("delivery_failures")
        msg = str(exc).lower()
        if "unauthorized" in msg or "401" in msg or "403" in msg or "api key" in msg:
            raise FailedAuthentication(f"Resend auth failed: {exc}") from exc
        raise FailedSource(f"Resend: {exc}") from exc
    finally:
        sem.release()
