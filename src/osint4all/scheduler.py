"""Agenda reconsulta das investigações monitoradas."""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from osint4all.config import get_settings
from osint4all.graph.expand import process_pending_jobs
from osint4all.graph.monitor import requeue_monitored_seeds
from osint4all.logging_setup import get_logger

logger = get_logger(__name__)


def run_scheduler() -> None:
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    cron = croniter(settings.schedule_cron, datetime.now(tz))
    logger.info("scheduler_started cron=%s tz=%s", settings.schedule_cron, settings.tz)
    while True:
        nxt = cron.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=tz)
        delay = max(1.0, (nxt - datetime.now(tz)).total_seconds())
        time.sleep(delay)
        queued = requeue_monitored_seeds()
        processed = process_pending_jobs(limit=50)
        logger.info("scheduler_tick queued=%s processed=%s", queued, processed)
