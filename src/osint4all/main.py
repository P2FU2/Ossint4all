"""CLI: serve, worker, schedule, init-db, expand, purge."""

from __future__ import annotations

import argparse
import select
import socket
import sys
import threading
from typing import Mapping

from osint4all.config import get_settings
from osint4all.db.session import init_db, session_scope
from osint4all.graph.expand import process_pending_jobs
from osint4all.graph.monitor import requeue_monitored_seeds
from osint4all.logging_setup import get_logger

logger = get_logger(__name__)

# O domínio antigo do Script_Jus no Railway (authenticadm.org) costuma
# continuar apontando para 8000, enquanto o healthcheck usa $PORT (8080).
_LEGACY_PUBLIC_PORTS = (8000,)


def resolve_serve_bind(
    env: Mapping[str, str],
    cli_host: str,
    cli_port: int,
) -> tuple[str, int, list[int]]:
    """Host/porta do uvicorn + portas extras que o proxy público ainda usa."""
    raw = (env.get("PORT") or "").strip()
    if raw:
        port = int(raw)
        extra = [p for p in _LEGACY_PUBLIC_PORTS if p != port]
        return "0.0.0.0", port, extra
    return cli_host, cli_port, []


def _pipe(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 120)
            if not readable:
                break
            for sock in readable:
                other = right if sock is left else left
                data = sock.recv(65536)
                if not data:
                    return
                other.sendall(data)
    except OSError:
        return
    finally:
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass


def start_port_bridge(listen_port: int, target_port: int, host: str = "0.0.0.0") -> bool:
    """Encaminha TCP listen_port → 127.0.0.1:target_port (domínio legado no Railway)."""

    def accept_loop() -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((host, listen_port))
            server.listen(128)
        except OSError as exc:
            logger.warning("legacy_port_bind_failed port=%s err=%s", listen_port, exc)
            return
        logger.info("legacy_public_port %s -> %s", listen_port, target_port)
        while True:
            try:
                client, _ = server.accept()
            except OSError:
                break
            try:
                upstream = socket.create_connection(("127.0.0.1", target_port), timeout=5)
            except OSError:
                client.close()
                continue
            threading.Thread(target=_pipe, args=(client, upstream), daemon=True).start()

    threading.Thread(target=accept_loop, name=f"port-bridge-{listen_port}", daemon=True).start()
    return True


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
        import os

        import uvicorn

        from osint4all.api import app

        # Healthcheck do Railway usa $PORT (em geral 8080). O domínio
        # authenticadm.org do projeto antigo ainda encaminha para 8000.
        host, port, extra_ports = resolve_serve_bind(os.environ, args.host, args.port)
        for extra in extra_ports:
            start_port_bridge(extra, port, host=host)
        logger.info("serve host=%s port=%s extra=%s", host, port, extra_ports)
        uvicorn.run(app, host=host, port=port)
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
