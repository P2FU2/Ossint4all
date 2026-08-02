"""Enums e modelos de domínio."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY = "RETRY"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"


class RunMode(StrEnum):
    BOOTSTRAP = "BOOTSTRAP"
    LIVE = "LIVE"
    RECONCILIATION = "RECONCILIATION"


class RunType(StrEnum):
    DAILY_DIGEST = "DAILY_DIGEST"
    BOOTSTRAP = "BOOTSTRAP"
    WEBHOOK_INGEST = "WEBHOOK_INGEST"
    HISTORICAL_DISCOVERY = "HISTORICAL_DISCOVERY"
    RECONCILIATION = "RECONCILIATION"
    PROCESS_REFRESH = "PROCESS_REFRESH"
    DELIVERY_RETRY = "DELIVERY_RETRY"


class JobType(StrEnum):
    WEBHOOK_INGEST = "WEBHOOK_INGEST"
    HISTORICAL_DISCOVERY = "HISTORICAL_DISCOVERY"
    PROCESS_REFRESH = "PROCESS_REFRESH"
    RECONCILIATION = "RECONCILIATION"
    DAILY_DIGEST = "DAILY_DIGEST"
    DELIVERY_RETRY = "DELIVERY_RETRY"
    LOAD_PENDING_EVENTS = "LOAD_PENDING_EVENTS"
    GENERATE_SUMMARIES = "GENERATE_SUMMARIES"
    BUILD_HTML = "BUILD_HTML"
    SEND_EMAIL = "SEND_EMAIL"


class EventType(StrEnum):
    PROCESSO_DESCOBERTO = "PROCESSO_DESCOBERTO"
    MOVIMENTACAO_PROCESSUAL = "MOVIMENTACAO_PROCESSUAL"
    PUBLICACAO_DJEN = "PUBLICACAO_DJEN"
    INTIMACAO_PROCESSUAL = "INTIMACAO_PROCESSUAL"
    COMUNICACAO_OUTRA = "COMUNICACAO_OUTRA"
    EVENTO_CORRIGIDO = "EVENTO_CORRIGIDO"


class NotifyStatus(StrEnum):
    PENDING_NOTIFY = "PENDING_NOTIFY"
    IN_DIGEST = "IN_DIGEST"
    NOTIFIED = "NOTIFIED"
    QUARANTINED = "QUARANTINED"
    IGNORED = "IGNORED"


class DigestStatus(StrEnum):
    BUILDING = "BUILDING"
    READY = "READY"
    DELIVERY_PENDING = "DELIVERY_PENDING"
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SubscriptionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STALE = "STALE"
    ERROR = "ERROR"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class QuarantineReason(StrEnum):
    UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
    INVALID_CNJ = "INVALID_CNJ"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD"
    UNSUPPORTED_COURT = "UNSUPPORTED_COURT"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class Priority(StrEnum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


class CriterionType(StrEnum):
    OAB = "OAB"
    CPF = "CPF"
    CNPJ = "CNPJ"
    NOME = "NOME"
    PROCESSO = "PROCESSO"
    EMPRESA = "EMPRESA"


class NormalizedEvent(BaseModel):
    event_type: EventType
    event_identity_key: str
    source_name: str
    source_event_id: str | None = None
    numero_cnj: str | None = None
    tribunal: str | None = None
    title: str = ""
    description: str = ""
    movement_code: str | None = None
    movement_date: datetime | None = None
    orgao_julgador: str | None = None
    complemento: str | None = None
    sequencia_origem: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = ""
    criterion_refs: list[str] = Field(default_factory=list)
    confidence: str = "high"
    requires_name_validation: bool = False
    official_link: str | None = None
    cached_response: bool | None = None
    provider_schema_version: str | None = None
    normalizer_version: str | None = None
