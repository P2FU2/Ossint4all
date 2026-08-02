"""Schema SQLAlchemy — SQLite e PostgreSQL."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Criterion(Base):
    __tablename__ = "criteria"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    criterion_type: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[str] = mapped_column(String(255), index=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("criterion_type", "value", name="uq_criterion"),)


class ProviderSubscription(Base):
    __tablename__ = "provider_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(32), default="judit")
    external_tracking_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tracking_type: Mapped[str] = mapped_column(String(64))
    criterion_id: Mapped[str] = mapped_column(ForeignKey("criteria.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    recurrence: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(32), default="judit")
    delivery_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    webhook_delivery_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED")


class WebhookRaw(Base):
    __tablename__ = "webhooks_raw"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(32), default="judit")
    delivery_key: Mapped[str] = mapped_column(String(128), index=True)
    headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    provider_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalizer_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_type: Mapped[str] = mapped_column(String(64), index=True)
    trigger_type: Mapped[str] = mapped_column(String(32))
    run_mode: Mapped[str] = mapped_column(String(32), default="LIVE")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    jobs: Mapped[list[Job]] = relationship(back_populates="run")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run | None] = relationship(back_populates="jobs")

    __table_args__ = (
        Index("ix_jobs_claim", "status", "available_at", "created_at"),
    )


class JobDeadLetter(Base):
    __tablename__ = "job_dead_letter"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    job_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Process(Base):
    __tablename__ = "processes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    numero_cnj: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    numero_cnj_digits: Mapped[str] = mapped_column(String(20), index=True)
    tribunal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classe: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assunto: Mapped[str | None] = mapped_column(String(255), nullable=True)
    orgao_julgador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grau: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # status/fase da Judit pode ser longo (ex.: "Conclusos para decisão ao(à) Ministro…")
    situacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_distribuicao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_movement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    check_frequency_days: Mapped[int] = mapped_column(Integer, default=1)
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessMovement(Base):
    __tablename__ = "process_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    process_id: Mapped[str] = mapped_column(ForeignKey("processes.id"), index=True)
    movement_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    source_name: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    codigo: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nome: Mapped[str | None] = mapped_column(String(512), nullable=True)
    data_hora: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orgao_julgador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    complemento: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Communication(Base):
    __tablename__ = "communications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    communication_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    communication_type: Mapped[str] = mapped_column(String(64))
    numero_cnj: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_name: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_identity_key: Mapped[str] = mapped_column(String(128), index=True)
    notify_status: Mapped[str] = mapped_column(String(32), default="PENDING_NOTIFY", index=True)
    source_name: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    numero_cnj: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    tribunal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="media")
    area_juridica: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tipo_movimentacao: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    possible_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    possible_deadline_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    official_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    criterion_refs: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    requires_name_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("event_identity_key", "payload_hash", name="uq_event_identity_payload"),
    )


class EventVersion(Base):
    __tablename__ = "event_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    provider_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalizer_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventQuarantine(Base):
    __tablename__ = "event_quarantine"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    reason: Mapped[str] = mapped_column(String(64), index=True)
    delivery_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CriterionLink(Base):
    __tablename__ = "criterion_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    criterion_id: Mapped[str] = mapped_column(ForeignKey("criteria.id"), index=True)
    process_id: Mapped[str | None] = mapped_column(ForeignKey("processes.id"), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceCapability(Base):
    __tablename__ = "source_capabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(32))
    capability: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    contracted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source", "capability", name="uq_source_cap"),)


class SourceCheckpoint(Base):
    __tablename__ = "source_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(32))
    checkpoint_key: Mapped[str] = mapped_column(String(128))
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("source", "checkpoint_key", name="uq_checkpoint"),)


class AiGeneration(Base):
    __tablename__ = "ai_generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="OK")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    reference_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="BUILDING", index=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    html_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    total_events: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DigestItem(Base):
    __tablename__ = "digest_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    digest_id: Mapped[str] = mapped_column(ForeignKey("digests.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    included_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("digest_id", "event_id", name="uq_digest_event"),)


class DigestCursor(Base):
    __tablename__ = "digest_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_successful_digest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    digest_id: Mapped[str | None] = mapped_column(ForeignKey("digests.id"), nullable=True, index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    recipient: Mapped[str] = mapped_column(String(255))
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    html_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notification_id: Mapped[str] = mapped_column(ForeignKey("notifications.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionLock(Base):
    __tablename__ = "execution_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128))
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
