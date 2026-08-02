"""CLI: serve | worker | schedule | bootstrap | run | purge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from monitor_jus.config import get_settings
from monitor_jus.db.session import init_db, session_scope
from monitor_jus.logging_setup import setup_logging


def cmd_serve() -> None:
    import uvicorn

    uvicorn.run("monitor_jus.api:app", host="0.0.0.0", port=8000, reload=False)


def cmd_worker() -> None:
    from monitor_jus.worker import worker_loop

    worker_loop()


def cmd_schedule() -> None:
    from monitor_jus.scheduler import scheduler_loop

    scheduler_loop()


def cmd_bootstrap() -> None:
    from monitor_jus.db.repository import Repository
    from monitor_jus.models import RunMode, RunType

    setup_logging()
    init_db()
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session)
        run = repo.create_run(
            RunType.BOOTSTRAP.value,
            trigger_type="cli",
            run_mode=RunMode.BOOTSTRAP.value,
        )
        job = repo.enqueue_job(run.id, "BOOTSTRAP", max_attempts=settings.job_max_attempts)
        print(f"Bootstrap enfileirado run={run.id} job={job.id}")


def cmd_run(run_type: str) -> None:
    from monitor_jus.db.repository import Repository
    from monitor_jus.models import RunMode

    setup_logging()
    init_db()
    settings = get_settings()
    with session_scope() as session:
        repo = Repository(session)
        run = repo.create_run(run_type, trigger_type="cli", run_mode=RunMode.LIVE.value)
        job = repo.enqueue_job(run.id, run_type, max_attempts=settings.job_max_attempts)
        print(f"Run enfileirado run={run.id} job={job.id}")


def cmd_purge(criterion_value: str) -> None:
    """Remove critério e vínculos (LGPD)."""
    from sqlalchemy import delete, select

    from monitor_jus.db.models import Criterion, CriterionLink

    setup_logging()
    init_db()
    with session_scope() as session:
        crits = list(
            session.scalars(select(Criterion).where(Criterion.value == criterion_value)).all()
        )
        for c in crits:
            session.execute(delete(CriterionLink).where(CriterionLink.criterion_id == c.id))
            session.delete(c)
        print(f"Removidos {len(crits)} critérios com value={criterion_value}")


def cmd_init_db() -> None:
    setup_logging()
    Path("data").mkdir(exist_ok=True)
    Path("data/outbox").mkdir(parents=True, exist_ok=True)
    init_db()
    print("DB inicializado")


def app_entry() -> None:
    parser = argparse.ArgumentParser(prog="monitor-jus")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("worker")
    sub.add_parser("schedule")
    sub.add_parser("bootstrap")
    sub.add_parser("init-db")
    p_run = sub.add_parser("run")
    p_run.add_argument("run_type", help="DAILY_DIGEST | HISTORICAL_DISCOVERY | PROCESS_REFRESH")
    p_purge = sub.add_parser("purge")
    p_purge.add_argument("criterion_value")

    args = parser.parse_args()
    if args.cmd == "serve":
        cmd_serve()
    elif args.cmd == "worker":
        cmd_worker()
    elif args.cmd == "schedule":
        cmd_schedule()
    elif args.cmd == "bootstrap":
        cmd_bootstrap()
    elif args.cmd == "init-db":
        cmd_init_db()
    elif args.cmd == "run":
        cmd_run(args.run_type)
    elif args.cmd == "purge":
        cmd_purge(args.criterion_value)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    app_entry()
