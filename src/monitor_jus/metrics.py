"""Métricas operacionais via logs estruturados (+ snapshot in-memory)."""

from __future__ import annotations

import threading
import time
from typing import Any

from monitor_jus.logging_setup import get_logger

logger = get_logger("monitor_jus.metrics")

_lock = threading.Lock()
_counters: dict[str, float] = {
    "jobs_pending": 0,
    "jobs_failed": 0,
    "jobs_dead": 0,
    "webhooks_received": 0,
    "webhooks_duplicate": 0,
    "events_created": 0,
    "events_quarantined": 0,
    "digest_events_total": 0,
    "delivery_failures": 0,
}
_gauges: dict[str, float] = {
    "last_successful_digest_timestamp": 0,
}
_latencies: dict[str, list[float]] = {}


def incr(metric: str, value: float = 1.0, **extra: Any) -> None:
    with _lock:
        _counters[metric] = _counters.get(metric, 0) + value
        current = _counters[metric]
    logger.info(
        "metric_incr",
        extra={"metric": metric, "value": current, "extra": extra or None},
    )


def set_gauge(metric: str, value: float, **extra: Any) -> None:
    with _lock:
        _gauges[metric] = value
    logger.info(
        "metric_gauge",
        extra={"metric": metric, "value": value, "extra": extra or None},
    )


def observe_latency(source: str, latency_ms: float, operation: str = "") -> None:
    key = f"{source}:{operation}" if operation else source
    with _lock:
        _latencies.setdefault(key, []).append(latency_ms)
        if len(_latencies[key]) > 100:
            _latencies[key] = _latencies[key][-100:]
    logger.info(
        "metric_latency",
        extra={
            "metric": "source_latency",
            "value": latency_ms,
            "source": source,
            "latency_ms": latency_ms,
            "extra": {"operation": operation},
        },
    )


def snapshot() -> dict[str, Any]:
    with _lock:
        lat: dict[str, float] = {}
        for key, values in _latencies.items():
            if values:
                lat[key] = sum(values) / len(values)
        return {
            "counters": dict(_counters),
            "gauges": dict(_gauges),
            "source_latency_avg_ms": lat,
            "ts": time.time(),
        }
