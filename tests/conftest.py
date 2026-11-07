"""Shared fixtures: fake servers for everything the display talks to."""

from __future__ import annotations

import json
import socket
import socketserver
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from rackdisplay.config import Config
from rackdisplay.sources.demo import DemoSource

Routes = dict[str, Any]  # path (with query) or path prefix -> JSON-able body, or (status, body)


class FakeHttp:
    """A tiny HTTP server answering from a dict. Longest matching prefix wins."""

    def __init__(self, routes: Routes) -> None:
        self.routes = routes
        self.requests: list[str] = []
        routes_ref = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                routes_ref.requests.append(self.path)
                match = max(
                    (r for r in routes_ref.routes if self.path.startswith(r)), key=len, default=None
                )
                status, body = 404, {"error": "not found"}
                if match is not None:
                    value = routes_ref.routes[match]
                    status, body = value if isinstance(value, tuple) else (200, value)
                    if callable(body):
                        body = body(self.path)
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_http() -> Iterator[Callable[[Routes], FakeHttp]]:
    made: list[FakeHttp] = []

    def make(routes: Routes) -> FakeHttp:
        fake = FakeHttp(routes)
        made.append(fake)
        return fake

    yield make
    for fake in made:
        fake.close()


@pytest.fixture
def unix_docker(tmp_path: Path) -> Iterator[Callable[[Any, int], str]]:
    """A fake Docker engine on a Unix socket; returns the socket path."""
    servers: list[socketserver.UnixStreamServer] = []

    def make(body: Any, status: int = 200) -> str:
        path = str(tmp_path / f"docker{len(servers)}.sock")

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                while self.rfile.readline().strip():  # read the request headers
                    pass
                payload = json.dumps(body).encode()
                self.wfile.write(
                    f"HTTP/1.1 {status} X\r\nContent-Length: {len(payload)}\r\n"
                    f"Content-Type: application/json\r\nConnection: close\r\n\r\n".encode()
                    + payload
                )

        server = socketserver.UnixStreamServer(path, Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return path

    yield make
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def demo_cfg() -> Config:
    cfg = Config()
    cfg.source.type = "demo"
    return cfg


@pytest.fixture
def demo_snapshot(demo_cfg: Config):  # type: ignore[no-untyped-def]
    return DemoSource(demo_cfg, clock=1_794_000_000.0).collect()
