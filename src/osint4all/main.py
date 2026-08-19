"""CLI: serve, worker, schedule, init-db, expand, purge."""

from __future__ import annotations

import argparse
import sys

from osint4all.config import get_settings
from osint4all.db.session import init_db, session_scope
from osint4all.graph.expand import process_pending_jobs
from osint4all.graph.monitor import requeue_monitored_seeds
from osint4all.logging_setup import get_logger

logger = get_logger(__name__)


def app_entry() -> None:
    main(sys.argv[1:])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="osint4all")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("worker")
    sub.add_parser("schedule")
    exp = sub.add_parser("expand")
    exp.add_argument("investigation_id")
    exp.add_argument("--limit", type=int, default=50)
    sub.add_parser("monitor")
    purge = sub.add_parser("purge")
    purge.add_argument("investigation_id")
    args = parser.parse_args(argv)

    if args.cmd == "init-db":
        init_db()
        logger.info("db_ready")
        return
    if args.cmd == "serve":
        import uvicorn

        from osint4all.api import app

        uvicorn.run(app, host=args.host, port=args.port)
        return
    if args.cmd == "worker":
        from osint4all.worker import run_worker

        run_worker()
        return
    if args.cmd == "schedule":
        from osint4all.scheduler import run_scheduler

        run_scheduler()
        return
    if args.cmd == "expand":
        n = process_pending_jobs(investigation_id=args.investigation_id, limit=args.limit)
        logger.info("expanded jobs=%s", n)
        return
    if args.cmd == "monitor":
        q = requeue_monitored_seeds()
        n = process_pending_jobs(limit=get_settings().expand_sync_limit)
        logger.info("monitor queued=%s processed=%s", q, n)
        return
    if args.cmd == "purge":
        from osint4all.db.models import Investigation

        with session_scope() as session:
            inv = session.get(Investigation, args.investigation_id)
            if inv:
                session.delete(inv)
                logger.info("purged %s", args.investigation_id)
            else:
                logger.info("not_found %s", args.investigation_id)
        return


if __name__ == "__main__":
    main()
