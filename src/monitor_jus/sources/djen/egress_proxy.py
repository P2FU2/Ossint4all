"""Proxy HTTP mínimo (CONNECT) só para o DJEN — rodar no PC (Tailscale).

Uso no PC (Tailscale ligado):
  python -m monitor_jus.sources.djen.egress_proxy
  # escuta 0.0.0.0:8899 — no Railway: DJEN_HTTP_PROXY=http://100.x.y.z:8899

Só permite CONNECT para hosts do DJEN/Comunica (não é proxy aberto).
"""

from __future__ import annotations

import argparse
import select
import socket
import socketserver
from typing import Iterable

# Destinos permitidos (HTTPS via CONNECT)
ALLOWED_HOSTS = frozenset(
    {
        "comunicaapi.pje.jus.br",
        "www.comunicaapi.pje.jus.br",
    }
)


def _allowed(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if h in ALLOWED_HOSTS:
        return True
    return any(h.endswith("." + a) for a in ALLOWED_HOSTS)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            line = self.rfile.readline(65536)
        except OSError:
            return
        if not line:
            return
        try:
            request_line = line.decode("latin-1", errors="replace").strip()
        except Exception:  # noqa: BLE001
            return
        parts = request_line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            self._send(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
            return
        target = parts[1]
        if ":" in target:
            host, _, port_s = target.partition(":")
            try:
                port = int(port_s)
            except ValueError:
                self._send(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                return
        else:
            host, port = target, 443
        # Drena headers
        while True:
            hdr = self.rfile.readline(65536)
            if not hdr or hdr in (b"\r\n", b"\n"):
                break
        if not _allowed(host) or port not in (443, 80):
            self._send(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=30)
        except OSError:
            self._send(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            return
        self._send(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        self._tunnel(self.connection, upstream)

    def _send(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
            self.wfile.flush()
        except OSError:
            pass

    def _tunnel(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets: list[socket.socket] = [client, upstream]
        try:
            while True:
                readable, _, errored = select.select(sockets, [], sockets, 120)
                if errored or not readable:
                    break
                for sock in readable:
                    other = upstream if sock is client else client
                    try:
                        data = sock.recv(65536)
                    except OSError:
                        return
                    if not data:
                        return
                    try:
                        other.sendall(data)
                    except OSError:
                        return
        finally:
            for s in (client, upstream):
                try:
                    s.close()
                except OSError:
                    pass


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(host: str = "0.0.0.0", port: int = 8899) -> None:
    server = _ThreadingTCPServer((host, port), _Handler)
    print(
        f"DJEN egress proxy em http://{host}:{port} "
        f"(só CONNECT → {', '.join(sorted(ALLOWED_HOSTS))})"
    )
    print("No Railway (mesma tailnet): DJEN_HTTP_PROXY=http://<IP-TAILSCALE-PC>:8899")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProxy encerrado.")
    finally:
        server.server_close()


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Proxy CONNECT restrito ao DJEN")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args(list(argv) if argv is not None else None)
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
