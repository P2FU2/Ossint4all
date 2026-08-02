"""Ingestão de webhooks Judit → eventos."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from monitor_jus.config import Settings, get_settings
from monitor_jus.db.repository import Repository
from monitor_jus.logging_setup import get_logger
from monitor_jus.metrics import incr
from monitor_jus.models import EventType, NotifyStatus, QuarantineReason
from monitor_jus.pipeline.categorize import categorize
from monitor_jus.pipeline.normalize import normalize_judit_webhook
from monitor_jus.pipeline.prioritize import classify_priority, has_possible_deadline
from monitor_jus.pipeline.quarantine import quarantine_event
from monitor_jus.progress import report as report_progress
from monitor_jus.sources.judit.webhooks import classify_webhook_event_type
from monitor_jus.validators import normalize_cnj

logger = get_logger(__name__)


def ingest_webhook_raw(session: Session, webhook_id: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = Repository(session)
    report_progress(stage="webhook", done=0, total=3, message="Ingerindo webhook", force=True)
    raw = repo.get_webhook_raw(webhook_id)
    if not raw:
        raise ValueError(f"webhook_raw não encontrado: {webhook_id}")

    payload = raw.payload or {}
    classified = classify_webhook_event_type(payload)
    report_progress(stage="webhook", done=1, total=3, message=f"Tipo {classified}")
    if classified == "UNKNOWN":
        quarantine_event(
            session,
            QuarantineReason.UNKNOWN_EVENT_TYPE,
            payload,
            details="Tipo de evento não reconhecido",
            delivery_key=raw.delivery_key,
        )
        repo.mark_webhook_processed(webhook_id, "QUARANTINED")
        report_progress(stage="webhook", done=3, total=3, message="Quarentena UNKNOWN", force=True)
        return {"status": "quarantined", "reason": "UNKNOWN_EVENT_TYPE"}

    normalized = normalize_judit_webhook(payload, classified)
    if not normalized:
        quarantine_event(
            session,
            QuarantineReason.MALFORMED_PAYLOAD,
            payload,
            delivery_key=raw.delivery_key,
        )
        repo.mark_webhook_processed(webhook_id, "QUARANTINED")
        return {"status": "quarantined", "reason": "MALFORMED_PAYLOAD"}

    if normalized.numero_cnj:
        parts = normalize_cnj(normalized.numero_cnj)
        if normalized.numero_cnj and parts is None and classified not in (
            EventType.PUBLICACAO_DJEN.value,
            "PUBLICACAO_DJEN",
        ):
            # publicações podem não ter CNJ
            if classified not in (
                EventType.PUBLICACAO_DJEN,
                EventType.COMUNICACAO_OUTRA,
            ):
                quarantine_event(
                    session,
                    QuarantineReason.INVALID_CNJ,
                    payload,
                    details=f"CNJ inválido: {normalized.numero_cnj}",
                    delivery_key=raw.delivery_key,
                )
                repo.mark_webhook_processed(webhook_id, "QUARANTINED")
                return {"status": "quarantined", "reason": "INVALID_CNJ"}
        if parts:
            repo.upsert_process(
                parts.numero_formatado,
                parts.numero_digits,
                tribunal=normalized.tribunal,
            )

    existing = repo.find_event_by_identity(normalized.event_identity_key)
    if existing and existing.payload_hash == normalized.payload_hash:
        # duplicata exata — só last_seen implícito
        repo.mark_webhook_processed(webhook_id, "DUPLICATE")
        incr("webhooks_duplicate")
        return {"status": "duplicate", "event_id": existing.id}

    text_for_rules = f"{normalized.title}\n{normalized.description}"
    priority, _rule = classify_priority(text_for_rules, settings.config_path("prioridades.yaml"))
    area, tipo = categorize(text_for_rules, settings.config_path("categorias.yaml"))
    deadline = has_possible_deadline(text_for_rules)

    if existing and existing.payload_hash != normalized.payload_hash:
        # correção da fonte
        event = repo.create_event(
            event_type=EventType.EVENTO_CORRIGIDO.value,
            event_identity_key=normalized.event_identity_key,
            notify_status=NotifyStatus.PENDING_NOTIFY.value,
            source_name=normalized.source_name,
            source_event_id=normalized.source_event_id,
            numero_cnj=normalized.numero_cnj,
            tribunal=normalized.tribunal,
            title=normalized.title,
            description=normalized.description,
            priority=priority.value,
            area_juridica=area,
            tipo_movimentacao=tipo,
            possible_deadline_flag=deadline,
            official_link=normalized.official_link,
            criterion_refs=normalized.criterion_refs,
            payload_hash=normalized.payload_hash,
            requires_name_validation=normalized.requires_name_validation,
        )
        repo.add_event_version(
            event.id,
            normalized.payload,
            normalized.payload_hash,
            normalized.provider_schema_version,
            normalized.normalizer_version,
        )
        incr("events_created")
        repo.mark_webhook_processed(webhook_id, "PROCESSED")
        return {"status": "corrected", "event_id": event.id}

    # evento novo
    # Em bootstrap, discovery marca IGNORED; webhooks LIVE ficam PENDING_NOTIFY
    notify_status = NotifyStatus.PENDING_NOTIFY.value
    event = repo.create_event(
        event_type=normalized.event_type.value,
        event_identity_key=normalized.event_identity_key,
        notify_status=notify_status,
        source_name=normalized.source_name,
        source_event_id=normalized.source_event_id,
        numero_cnj=normalized.numero_cnj,
        tribunal=normalized.tribunal,
        title=normalized.title,
        description=normalized.description,
        priority=priority.value,
        area_juridica=area,
        tipo_movimentacao=tipo,
        possible_deadline_flag=deadline,
        official_link=normalized.official_link,
        criterion_refs=normalized.criterion_refs,
        payload_hash=normalized.payload_hash,
        requires_name_validation=normalized.requires_name_validation,
    )
    repo.add_event_version(
        event.id,
        normalized.payload,
        normalized.payload_hash,
        normalized.provider_schema_version,
        normalized.normalizer_version,
    )
    incr("events_created")
    repo.mark_webhook_processed(webhook_id, "PROCESSED")
    report_progress(
        stage="webhook",
        done=3,
        total=3,
        message=f"Evento {event.event_type}",
        force=True,
    )
    logger.info("webhook_ingested", extra={"event_id": event.id, "extra": {"type": event.event_type}})
    return {"status": "created", "event_id": event.id}
