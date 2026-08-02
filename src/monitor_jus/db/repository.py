"""Operações de persistência e claim de jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, and_, or_, select, text, update
from sqlalchemy.orm import Session

from monitor_jus.db.models import (
    Digest,
    DigestCursor,
    DigestItem,
    Event,
    EventQuarantine,
    EventVersion,
    ExecutionLock,
    Job,
    JobDeadLetter,
    Notification,
    Process,
    ProviderSubscription,
    Run,
    SourceCapability,
    WebhookDelivery,
    WebhookRaw,
)
from monitor_jus.models import DigestStatus, JobStatus, NotifyStatus, RunStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- locks ---
    def acquire_lock(self, name: str, owner: str, ttl_seconds: int = 3600) -> bool:
        now = utcnow()
        existing = self.session.get(ExecutionLock, name)
        if existing and existing.expires_at.replace(tzinfo=timezone.utc) > now:
            if existing.owner != owner:
                return False
        lock = existing or ExecutionLock(name=name, owner=owner, expires_at=now)
        lock.owner = owner
        lock.locked_at = now
        lock.expires_at = now + timedelta(seconds=ttl_seconds)
        self.session.add(lock)
        self.session.flush()
        return True

    def release_lock(self, name: str, owner: str) -> None:
        lock = self.session.get(ExecutionLock, name)
        if lock and lock.owner == owner:
            self.session.delete(lock)

    # --- runs / jobs ---
    def create_run(
        self,
        run_type: str,
        trigger_type: str,
        *,
        run_mode: str = "LIVE",
        idempotency_key: str | None = None,
    ) -> Run:
        if idempotency_key:
            existing = self.session.scalar(
                select(Run).where(Run.idempotency_key == idempotency_key)
            )
            if existing:
                return existing
        run = Run(
            id=str(uuid4()),
            run_type=run_type,
            trigger_type=trigger_type,
            run_mode=run_mode,
            status=RunStatus.PENDING.value,
            idempotency_key=idempotency_key,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def enqueue_job(
        self,
        run_id: str | None,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
    ) -> Job:
        if idempotency_key:
            existing = self.session.scalar(
                select(Job).where(
                    Job.idempotency_key == idempotency_key,
                    Job.status.in_(
                        [
                            JobStatus.PENDING.value,
                            JobStatus.RUNNING.value,
                            JobStatus.RETRY.value,
                        ]
                    ),
                )
            )
            if existing:
                return existing
        job = Job(
            id=str(uuid4()),
            run_id=run_id,
            job_type=job_type,
            status=JobStatus.PENDING.value,
            payload=payload or {},
            max_attempts=max_attempts,
            available_at=available_at or utcnow(),
            idempotency_key=idempotency_key,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def claim_next_job(self, worker_id: str) -> Job | None:
        """Claim atômico — SKIP LOCKED no Postgres; fallback SQLite."""
        now = utcnow()
        bind = self.session.get_bind()
        dialect = bind.dialect.name if bind is not None else "sqlite"

        if dialect == "postgresql":
            sql = text(
                """
                SELECT id FROM jobs
                WHERE status IN ('PENDING', 'RETRY')
                  AND (available_at IS NULL OR available_at <= :now)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            row = self.session.execute(sql, {"now": now}).first()
            if not row:
                return None
            job = self.session.get(Job, row[0])
        else:
            job = self.session.scalar(
                select(Job)
                .where(
                    Job.status.in_([JobStatus.PENDING.value, JobStatus.RETRY.value]),
                    or_(Job.available_at.is_(None), Job.available_at <= now),
                )
                .order_by(Job.created_at)
                .with_for_update()
            )
            if not job:
                return None

        assert job is not None
        job.status = JobStatus.RUNNING.value
        job.locked_by = worker_id
        job.locked_at = now
        job.heartbeat_at = now
        job.started_at = now
        job.attempt_count = (job.attempt_count or 0) + 1
        self.session.flush()
        return job

    def heartbeat_job(self, job_id: str) -> None:
        job = self.session.get(Job, job_id)
        if job:
            job.heartbeat_at = utcnow()

    def complete_job(self, job: Job) -> None:
        job.status = JobStatus.SUCCESS.value
        job.finished_at = utcnow()
        job.locked_by = None

    def fail_job(
        self,
        job: Job,
        *,
        error_code: str,
        error_message: str,
        recoverable: bool,
        retry_delay_seconds: int = 60,
    ) -> None:
        job.last_error_code = error_code
        job.last_error_message = error_message[:4000]
        if recoverable and job.attempt_count < job.max_attempts:
            job.status = JobStatus.RETRY.value
            job.available_at = utcnow() + timedelta(seconds=retry_delay_seconds * job.attempt_count)
            job.locked_by = None
        else:
            job.status = JobStatus.DEAD.value
            job.finished_at = utcnow()
            job.locked_by = None
            self.session.add(
                JobDeadLetter(
                    id=str(uuid4()),
                    job_id=job.id,
                    job_type=job.job_type,
                    payload=job.payload,
                    error_code=error_code,
                    error_message=error_message[:4000],
                )
            )

    def finish_run(self, run_id: str, status: str, error_summary: str | None = None) -> None:
        run = self.session.get(Run, run_id)
        if not run:
            return
        run.status = status
        run.finished_at = utcnow()
        run.error_summary = error_summary

    def get_run(self, run_id: str) -> Run | None:
        return self.session.get(Run, run_id)

    def count_jobs_by_status(self, status: str) -> int:
        from sqlalchemy import func

        return int(
            self.session.scalar(select(func.count()).select_from(Job).where(Job.status == status))
            or 0
        )

    # --- webhooks ---
    def webhook_delivery_exists(self, delivery_key: str) -> bool:
        return (
            self.session.scalar(
                select(WebhookDelivery.id).where(WebhookDelivery.delivery_key == delivery_key)
            )
            is not None
        )

    def save_webhook(
        self,
        *,
        delivery_key: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None,
        provider_schema_version: str,
        normalizer_version: str,
        webhook_delivery_id: str | None = None,
    ) -> WebhookRaw:
        self.session.add(
            WebhookDelivery(
                id=str(uuid4()),
                delivery_key=delivery_key,
                webhook_delivery_id=webhook_delivery_id,
            )
        )
        raw = WebhookRaw(
            id=str(uuid4()),
            delivery_key=delivery_key,
            headers=headers,
            payload=payload,
            provider_schema_version=provider_schema_version,
            normalizer_version=normalizer_version,
            status="PENDING",
        )
        self.session.add(raw)
        self.session.flush()
        return raw

    def get_webhook_raw(self, webhook_id: str) -> WebhookRaw | None:
        return self.session.get(WebhookRaw, webhook_id)

    def mark_webhook_processed(self, webhook_id: str, status: str = "PROCESSED") -> None:
        raw = self.session.get(WebhookRaw, webhook_id)
        if raw:
            raw.status = status
            raw.processed_at = utcnow()

    # --- events / quarantine ---
    def find_event_by_identity(self, event_identity_key: str) -> Event | None:
        return self.session.scalar(
            select(Event)
            .where(Event.event_identity_key == event_identity_key)
            .order_by(Event.created_at.desc())
        )

    def create_event(self, **kwargs: Any) -> Event:
        event = Event(id=str(uuid4()), **kwargs)
        self.session.add(event)
        self.session.flush()
        return event

    def add_event_version(
        self,
        event_id: str,
        payload: dict[str, Any],
        payload_hash: str,
        provider_schema_version: str | None,
        normalizer_version: str | None,
    ) -> EventVersion:
        ver = EventVersion(
            id=str(uuid4()),
            event_id=event_id,
            payload=payload,
            payload_hash=payload_hash,
            provider_schema_version=provider_schema_version,
            normalizer_version=normalizer_version,
        )
        self.session.add(ver)
        self.session.flush()
        return ver

    def quarantine(
        self,
        reason: str,
        payload: dict[str, Any] | None,
        details: str | None = None,
        delivery_key: str | None = None,
    ) -> EventQuarantine:
        q = EventQuarantine(
            id=str(uuid4()),
            reason=reason,
            payload=payload,
            details=details,
            delivery_key=delivery_key,
        )
        self.session.add(q)
        self.session.flush()
        return q

    def pending_notify_events(self, since: datetime | None) -> list[Event]:
        stmt: Select[tuple[Event]] = select(Event).where(
            Event.notify_status == NotifyStatus.PENDING_NOTIFY.value
        )
        if since is not None:
            stmt = stmt.where(Event.created_at > since)
        stmt = stmt.order_by(Event.priority.asc(), Event.created_at.asc())
        return list(self.session.scalars(stmt).all())

    def count_quarantine_open(self) -> int:
        from sqlalchemy import func

        return int(
            self.session.scalar(
                select(func.count())
                .select_from(EventQuarantine)
                .where(EventQuarantine.resolved_at.is_(None))
            )
            or 0
        )

    # --- digest ---
    def get_digest_cursor(self) -> DigestCursor:
        cursor = self.session.get(DigestCursor, 1)
        if not cursor:
            cursor = DigestCursor(id=1, last_successful_digest_at=None)
            self.session.add(cursor)
            self.session.flush()
        return cursor

    def create_digest(self, **kwargs: Any) -> Digest:
        digest = Digest(id=str(uuid4()), **kwargs)
        self.session.add(digest)
        self.session.flush()
        return digest

    def attach_digest_items(self, digest_id: str, event_ids: list[str]) -> None:
        for eid in event_ids:
            self.session.add(
                DigestItem(id=str(uuid4()), digest_id=digest_id, event_id=eid)
            )
            event = self.session.get(Event, eid)
            if event:
                event.notify_status = NotifyStatus.IN_DIGEST.value
        self.session.flush()

    def mark_digest_sent(self, digest: Digest) -> None:
        digest.status = DigestStatus.SENT.value
        digest.sent_at = utcnow()
        items = self.session.scalars(
            select(DigestItem).where(DigestItem.digest_id == digest.id)
        ).all()
        for item in items:
            event = self.session.get(Event, item.event_id)
            if event:
                event.notify_status = NotifyStatus.NOTIFIED.value
        cursor = self.get_digest_cursor()
        cursor.last_successful_digest_at = digest.sent_at
        self.session.flush()

    def get_digest(self, digest_id: str) -> Digest | None:
        return self.session.get(Digest, digest_id)

    # --- processes ---
    def upsert_process(self, numero_cnj: str, numero_digits: str, **kwargs: Any) -> Process:
        proc = self.session.scalar(select(Process).where(Process.numero_cnj == numero_cnj))
        if not proc:
            proc = Process(
                id=str(uuid4()),
                numero_cnj=numero_cnj,
                numero_cnj_digits=numero_digits,
            )
            self.session.add(proc)
        for k, v in kwargs.items():
            if hasattr(proc, k) and v is not None:
                setattr(proc, k, v)
        self.session.flush()
        return proc

    def processes_due(self, now: datetime | None = None) -> list[Process]:
        now = now or utcnow()
        return list(
            self.session.scalars(
                select(Process).where(
                    or_(Process.next_check_at.is_(None), Process.next_check_at <= now)
                )
            ).all()
        )

    # --- capabilities / subscriptions ---
    def upsert_capability(
        self, source: str, capability: str, *, enabled: bool, contracted: bool
    ) -> SourceCapability:
        cap = self.session.scalar(
            select(SourceCapability).where(
                SourceCapability.source == source,
                SourceCapability.capability == capability,
            )
        )
        if not cap:
            cap = SourceCapability(
                id=str(uuid4()),
                source=source,
                capability=capability,
            )
            self.session.add(cap)
        cap.enabled = enabled
        cap.contracted = contracted
        self.session.flush()
        return cap

    def list_capabilities(self) -> list[SourceCapability]:
        return list(self.session.scalars(select(SourceCapability)).all())

    def find_subscription(
        self, provider: str, criterion_id: str, tracking_type: str
    ) -> ProviderSubscription | None:
        return self.session.scalar(
            select(ProviderSubscription).where(
                ProviderSubscription.provider == provider,
                ProviderSubscription.criterion_id == criterion_id,
                ProviderSubscription.tracking_type == tracking_type,
            )
        )

    def create_notification(self, **kwargs: Any) -> Notification:
        n = Notification(id=str(uuid4()), **kwargs)
        self.session.add(n)
        self.session.flush()
        return n
