"""Consome a fila de expansão."""

from __future__ import annotations

import time

from osint4all.graph.expand import process_pending_jobs
from osint4all.logging_setup import get_logger

logger = get_logger(__name__)


def run_worker(*, poll_seconds: float = 2.0) -> None:
    logger.info("worker_started")
    while True:
        n = process_pending_jobs(limit=10)
        if n == 0:
            time.sleep(poll_seconds)
