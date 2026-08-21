"""Schema do grafo de investigação."""

from __future__ import annotations

from datetime import datetime, timezone
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    investigation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchHistory(Base):
    __tablename__ = "search_history"
    __table_args__ = (Index("ix_search_history_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    mode: Mapped[str] = mapped_column(String(32), default="auto")
    kind: Mapped[str] = mapped_column(String(32), default="")
    query: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(String(400), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class SearchChain(Base):
    __tablename__ = "search_chains"
    __table_args__ = (Index("ix_search_chains_user_active", "user_id", "active"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now(), onupdate=_now)


class SearchChainStep(Base):
    __tablename__ = "search_chain_steps"
    __table_args__ = (Index("ix_search_chain_steps_chain", "chain_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chain_id: Mapped[str] = mapped_column(ForeignKey("search_chains.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="")
    query: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(String(400), default="")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    identifiers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255))
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_depth: Mapped[int] = mapped_column(Integer, default=2)
    connectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    monitor: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_monitored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(80), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), default="interno")
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    playbook_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workflow: Mapped[str] = mapped_column(String(32), default="INVESTIGATING")
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entities: Mapped[list[Entity]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    edges: Mapped[list[Edge]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    jobs: Mapped[list[ExpansionJob]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    notes: Mapped[list[CaseNote]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    blocked_keys: Mapped[list[BlockedKey]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    host_intel: Mapped[list["HostIntel"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    events: Mapped[list["CaseEvent"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    tasks: Mapped[list["CaseTask"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    verifications: Mapped[list["VerificationRecord"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    changes: Mapped[list["ChangeLog"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    claims: Mapped[list["Claim"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    playbook_items: Mapped[list["PlaybookItem"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    entity_versions: Mapped[list["EntityVersion"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    query_logs: Mapped[list["QueryLog"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    negatives: Mapped[list["NegativeFinding"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    comments: Mapped[list["CaseComment"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    plans: Mapped[list["ResearchPlan"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    snapshots: Mapped[list["CaseSnapshot"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("investigation_id", "canonical_key", name="uq_entity_key"),
        Index("ix_entities_type", "investigation_id", "entity_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    canonical_key: Mapped[str] = mapped_column(String(512), index=True)
    display_name: Mapped[str] = mapped_column(String(512))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="entities")
    identifiers: Mapped[list[Identifier]] = relationship(back_populates="entity", cascade="all, delete-orphan")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="entity", cascade="all, delete-orphan")


class Identifier(Base):
    __tablename__ = "identifiers"
    __table_args__ = (UniqueConstraint("entity_id", "kind", "canonical_key", name="uq_identifier"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[str] = mapped_column(String(512))
    canonical_key: Mapped[str] = mapped_column(String(512), index=True)
    strong: Mapped[bool] = mapped_column(Boolean, default=False)

    entity: Mapped[Entity] = relationship(back_populates="identifiers")


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "from_entity_id",
            "to_entity_id",
            "rel_type",
            name="uq_edge",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    from_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    to_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    rel_type: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    attrs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_connector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="edges")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("investigation_id", "dedup_hash", name="uq_evidence_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id"), nullable=True, index=True)
    edge_id: Mapped[str | None] = mapped_column(ForeignKey("edges.id"), nullable=True)
    connector: Mapped[str] = mapped_column(String(64), index=True)
    source_label: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    method: Mapped[str] = mapped_column(String(16), default="GET")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    entity: Mapped[Entity | None] = relationship(back_populates="evidence")


class CaseNote(Base):
    __tablename__ = "case_notes"
    __table_args__ = (Index("ix_case_notes_inv", "investigation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("case_notes.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="notes")


class BlockedKey(Base):
    __tablename__ = "blocked_keys"
    __table_args__ = (UniqueConstraint("investigation_id", "canonical_key", name="uq_blocked_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(512), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="blocked_keys")


class HostIntel(Base):
    """Índice estilo IVRE: um host, várias fontes, sem iniciar scan."""

    __tablename__ = "host_intel"
    __table_args__ = (
        UniqueConstraint("investigation_id", "host", "source", name="uq_host_intel_src"),
        Index("ix_host_intel_inv_host", "investigation_id", "host"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True, index=True)
    host: Mapped[str] = mapped_column(String(255), index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    tech: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cert: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(64), index=True)
    origin: Mapped[str] = mapped_column(String(16), default="passive")
    snippet: Mapped[str] = mapped_column(String(400), default="")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="host_intel")


class ExpansionJob(Base):
    __tablename__ = "expansion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), index=True)
    job_type: Mapped[str] = mapped_column(String(32), default="EXPAND")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    investigation: Mapped[Investigation] = relationship(back_populates="jobs")


class CaseEvent(Base):
    """Linha do tempo persistida do caso."""

    __tablename__ = "case_events"
    __table_args__ = (Index("ix_case_events_inv_when", "investigation_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    meta: Mapped[str] = mapped_column(String(400), default="")
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="events")


class CaseTask(Base):
    __tablename__ = "case_tasks"
    __table_args__ = (Index("ix_case_tasks_inv", "investigation_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    assignee: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    investigation: Mapped[Investigation] = relationship(back_populates="tasks")


class VerificationRecord(Base):
    __tablename__ = "verification_records"
    __table_args__ = (Index("ix_verification_target", "investigation_id", "target_type", "target_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(16), default="entity")
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    verdict: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="verifications")


class ChangeLog(Base):
    __tablename__ = "change_log"
    __table_args__ = (Index("ix_change_log_inv", "investigation_id", "detected_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    field: Mapped[str] = mapped_column(String(64), default="")
    old_value: Mapped[str] = mapped_column(String(400), default="")
    new_value: Mapped[str] = mapped_column(String(400), default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="changes")


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (Index("ix_hypotheses_inv", "investigation_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="primary")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="hypotheses")
    stances: Mapped[list["HypothesisStance"]] = relationship(back_populates="hypothesis", cascade="all, delete-orphan")


class HypothesisStance(Base):
    __tablename__ = "hypothesis_stances"
    __table_args__ = (UniqueConstraint("hypothesis_id", "evidence_id", name="uq_hyp_evidence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), index=True)
    stance: Mapped[str] = mapped_column(String(16), default="inconclusive")
    note: Mapped[str] = mapped_column(String(400), default="")

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="stances")


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (Index("ix_claims_inv", "investigation_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(String(16), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="claims")
    approvals: Mapped[list["ClaimApproval"]] = relationship(back_populates="claim", cascade="all, delete-orphan")


class ClaimApproval(Base):
    __tablename__ = "claim_approvals"
    __table_args__ = (UniqueConstraint("claim_id", "username", name="uq_claim_approver"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    username: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(16), default="analyst")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped[Claim] = relationship(back_populates="approvals")


class PlaybookItem(Base):
    __tablename__ = "playbook_items"
    __table_args__ = (UniqueConstraint("investigation_id", "step_key", name="uq_playbook_step"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    playbook_key: Mapped[str] = mapped_column(String(32), default="CUSTOM")
    step_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="todo", index=True)
    note: Mapped[str] = mapped_column(String(400), default="")

    investigation: Mapped[Investigation] = relationship(back_populates="playbook_items")


class EntityVersion(Base):
    __tablename__ = "entity_versions"
    __table_args__ = (Index("ix_entity_versions_ent", "entity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str] = mapped_column(String(400), default="")
    new_value: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="entity_versions")


class QueryLog(Base):
    __tablename__ = "query_logs"
    __table_args__ = (Index("ix_query_logs_inv", "investigation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    connector: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    connector_version: Mapped[str] = mapped_column(String(32), default="1")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    empty: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="query_logs")


class NegativeFinding(Base):
    __tablename__ = "negative_findings"
    __table_args__ = (Index("ix_negative_inv", "investigation_id", "connector"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    connector: Mapped[str] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(String(512), default="")
    note: Mapped[str] = mapped_column(String(400), default="Não encontrado nesta fonte. Isso não prova que não existe.")

    investigation: Mapped[Investigation] = relationship(back_populates="negatives")


class CaseComment(Base):
    __tablename__ = "case_comments"
    __table_args__ = (Index("ix_case_comments_inv", "investigation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="comments")


class ResearchPlan(Base):
    __tablename__ = "research_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="plans")


class CaseSnapshot(Base):
    __tablename__ = "case_snapshots"
    __table_args__ = (Index("ix_case_snapshots_inv", "investigation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    digest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())

    investigation: Mapped[Investigation] = relationship(back_populates="snapshots")


class SourceHealthCheck(Base):
    __tablename__ = "source_health"
    __table_args__ = (Index("ix_source_health_src", "connector", "checked_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connector: Mapped[str] = mapped_column(String(64), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(400), default="")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, server_default=func.now())
