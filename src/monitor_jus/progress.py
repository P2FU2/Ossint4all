"""Progresso de jobs: %, barra, ETA — persistido + logs estruturados."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from monitor_jus.db.session import get_engine
from monitor_jus.logging_setup import get_logger

logger = get_logger(__name__)

_current_job_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "progress_job_id", default=None
)
_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "progress_run_id", default=None
)


@dataclass
class ProgressState:
    job_id: str
    run_id: str | None
    stage: str
    done: float
    total: float
    message: str
    started_mono: float
    last_emit_mono: float = 0.0
    last_pct: int = -1


_state: ProgressState | None = None
_MIN_EMIT_SECONDS = 2.0


def bind_job(job_id: str, run_id: str | None = None) -> None:
    global _state
    _current_job_id.set(job_id)
    _current_run_id.set(run_id)
    _state = ProgressState(
        job_id=job_id,
        run_id=run_id,
        stage="starting",
        done=0,
        total=1,
        message="Iniciando",
        started_mono=time.monotonic(),
    )
    report(stage="starting", done=0, total=1, message="Iniciando", force=True)


def clear_job() -> None:
    global _state
    _current_job_id.set(None)
    _current_run_id.set(None)
    _state = None


def current_job_id() -> str | None:
    return _current_job_id.get()


def _eta_seconds(done: float, total: float, started_mono: float) -> float | None:
    if done <= 0 or total <= 0 or done >= total:
        return 0.0 if total > 0 and done >= total else None
    elapsed = time.monotonic() - started_mono
    rate = done / elapsed if elapsed > 0 else 0
    if rate <= 0:
        return None
    remaining = (total - done) / rate
    return max(0.0, remaining)


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    secs = int(round(seconds))
    if secs <= 0:
        return "0s"
    if secs < 60:
        return f"{secs}s"
    mins, s = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m {s}s"
    hours, m = divmod(mins, 60)
    return f"{hours}h {m}m"


def format_bar(pct: int, width: int = 20) -> str:
    pct = max(0, min(100, pct))
    filled = int(round(width * pct / 100))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def report(
    *,
    stage: str | None = None,
    done: float | None = None,
    total: float | None = None,
    message: str | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    """Atualiza progresso do job atual (DB + log). Retorna snapshot ou None."""
    global _state
    job_id = _current_job_id.get()
    if not job_id or _state is None:
        return None

    if stage is not None:
        _state.stage = stage
    if done is not None:
        _state.done = max(0.0, float(done))
    if total is not None:
        _state.total = max(0.0, float(total))
    if message is not None:
        _state.message = message

    total = _state.total if _state.total > 0 else 1.0
    done = min(_state.done, total)
    pct = int(round(100.0 * done / total)) if total else 0
    pct = max(0, min(100, pct))
    eta = _eta_seconds(done, total, _state.started_mono)
    now_mono = time.monotonic()

    should_emit = (
        force
        or pct != _state.last_pct
        or (now_mono - _state.last_emit_mono) >= _MIN_EMIT_SECONDS
        or pct >= 100
        or done >= total
    )
    if not should_emit:
        return None

    _state.last_emit_mono = now_mono
    _state.last_pct = pct
    bar = format_bar(pct)
    eta_label = format_eta(eta)
    extra = {
        "job_id": job_id,
        "run_id": _state.run_id,
        "stage": _state.stage,
        "done": round(done, 2),
        "total": round(total, 2),
        "progress_pct": pct,
        "eta_seconds": None if eta is None else round(eta, 1),
        "eta": eta_label,
        "bar": bar,
        "message": _state.message,
    }
    logger.info(
        f"progress {bar} {pct}% ETA {eta_label} · {_state.stage} · {_state.message}",
        extra={
            "job_id": job_id,
            "run_id": _state.run_id,
            "progress_pct": pct,
            "progress_eta_seconds": extra["eta_seconds"],
            "progress_stage": _state.stage,
            "extra": extra,
        },
    )
    _persist(job_id, pct, done, total, _state.stage, _state.message, eta)
    return extra


def complete(message: str = "Concluído") -> None:
    report(stage="done", done=1, total=1, message=message, force=True)


def fail(message: str = "Falhou") -> None:
    st = _state
    if not st:
        return
    # mantém % atual; só marca estágio
    report(stage="failed", message=message, force=True)


def _persist(
    job_id: str,
    pct: int,
    done: float,
    total: float,
    stage: str,
    message: str,
    eta: float | None,
) -> None:
    """UPDATE dedicado para a UI ver progresso durante o job."""
    engine = get_engine()
    now = datetime.now(timezone.utc)
    sql = text(
        """
        UPDATE jobs
        SET progress_pct = :pct,
            progress_done = :done,
            progress_total = :total,
            progress_stage = :stage,
            progress_message = :message,
            eta_seconds = :eta,
            heartbeat_at = :now
        WHERE id = :id
        """
    )
    try:
        with engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "pct": pct,
                    "done": done,
                    "total": total,
                    "stage": stage[:64],
                    "message": (message or "")[:512],
                    "eta": None if eta is None else float(eta),
                    "now": now,
                    "id": job_id,
                },
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "progress_persist_failed",
            extra={"job_id": job_id, "extra": {"error": str(exc)}},
        )


def job_progress_dict(job: Any) -> dict[str, Any]:
    """Serializa campos de progresso de um Job ORM."""
    pct = int(job.progress_pct or 0) if getattr(job, "progress_pct", None) is not None else 0
    eta = getattr(job, "eta_seconds", None)
    status = getattr(job, "status", "") or ""
    if status == "SUCCESS":
        pct = 100
        eta = 0.0
    elif status in ("PENDING", "RETRY") and not getattr(job, "started_at", None):
        pct = 0
    return {
        "progress_pct": pct,
        "progress_done": getattr(job, "progress_done", None),
        "progress_total": getattr(job, "progress_total", None),
        "progress_stage": getattr(job, "progress_stage", None) or "—",
        "progress_message": getattr(job, "progress_message", None) or "",
        "eta_seconds": eta,
        "eta_label": format_eta(float(eta) if eta is not None else None),
        "bar": format_bar(pct),
    }
