"""Reconsulta periódica das sementes monitoradas."""

from __future__ import annotations

from sqlalchemy import select

from osint4all.config import get_settings
from osint4all.db.models import Entity, ExpansionJob, Investigation
from osint4all.db.repository import utcnow
from osint4all.db.session import session_scope
from osint4all.logging_setup import get_logger

logger = get_logger(__name__)


def requeue_monitored_seeds() -> int:
    settings = get_settings()
    queued = 0
    with session_scope() as session:
        investigations = session.scalars(
            select(Investigation).where(Investigation.monitor.is_(True), Investigation.status == "ACTIVE")
        ).all()
        for inv in investigations:
            seeds = session.scalars(
                select(Entity).where(Entity.investigation_id == inv.id, Entity.is_seed.is_(True))
            ).all()
            for entity in seeds:
                session.add(
                    ExpansionJob(
                        investigation_id=inv.id,
                        entity_id=entity.id,
                        job_type="EXPAND",
                        depth=0,
                        max_attempts=settings.job_max_attempts,
                    )
                )
                queued += 1
            inv.last_monitored_at = utcnow()
        logger.info("monitor_requeue investigations=%s jobs=%s", len(investigations), queued)
    return queued
