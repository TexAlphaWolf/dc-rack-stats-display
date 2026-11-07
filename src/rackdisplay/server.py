"""The HTTP side: a background collector, the kiosk page, a JSON API, LCD frames and metrics."""

from __future__ import annotations

import hmac
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any

from . import __version__, metrics
from .config import Config
from .model import Snapshot
from .render import frames
from .sources import Source

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
# Scripts and styles only from this server, data only from this server, nothing embedded.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class Collector:
    """Calls the source every `interval` seconds and keeps the latest snapshot."""

    def __init__(self, source: Source, interval: float) -> None:
        self.source = source
        self.interval = interval
        self._lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="collector", daemon=True)

    def collect_once(self) -> None:
        try:
            snap = self.source.collect()
        except Exception as error:  # a source must never take the display down
            with self._lock:
                self._error = f"{type(error).__name__}: {error}"
            return
        with self._lock:
            self._snapshot, self._error = snap, ""

    def _run(self) -> None:
        while not self._stop.is_set():
            self.collect_once()
            self._stop.wait(self.interval)

    def start(self) -> None:
        self.collect_once()  # so the first request already has data
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def current(self) -> tuple[Snapshot | None, float | None, str]:
        with self._lock:
            snap, error = self._snapshot, self._error
        return snap, (time.time() - snap.ts if snap else None), error


def _read_static(name: str) -> bytes:
    return resources.files("rackdisplay").joinpath("web", name).read_bytes()


class Handler(BaseHTTPRequestHandler):
    server_version = f"rackdisplay/{__version__}"
    protocol_version = "HTTP/1.1"
    collector: Collector
    cfg: Config

    def log_message(self, format: str, *args: Any) -> None:
        pass  # a wall display polls every few seconds: access logs would only be noise

    # ------------------------------------------------------------------ helpers

    def do_HEAD(self) -> None:
        self.do_GET()  # _send leaves the body out for HEAD

    def _send(
        self, code: int, body: bytes, content_type: str, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")  # the token may be in the page's URL
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _authorised(self, query: dict[str, list[str]]) -> bool:
        token = self.cfg.server.token
        if not token:
            return True
        given = query.get("token", [""])[0]
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            given = header[7:]
        return hmac.compare_digest(given.encode(), token.encode())

    # ------------------------------------------------------------------ routes

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        if path in STATIC:
            name, content_type = STATIC[path]
            self._send(200, _read_static(name), content_type, {"Content-Security-Policy": CSP})
            return
        if path == "/healthz":
            self._health()
            return
        if path not in ("/api/stats", "/api/lcd", "/api/lcd.txt", "/api/config", "/metrics"):
            self._json({"error": "not found"}, 404)
            return
        if not self._authorised(query):
            self._send(
                401,
                b'{"error": "token required"}',
                "application/json",
                {"WWW-Authenticate": "Bearer"},
            )
            return
        snap, age, error = self.collector.current()
        if path == "/metrics":
            self._send(
                200, metrics.render(snap, age).encode(), "text/plain; version=0.0.4; charset=utf-8"
            )
        elif path == "/api/config":
            d = self.cfg.display
            self._json({"title": d.title, "rotate_seconds": d.rotate_seconds, "screens": d.screens,
                        "interval": self.cfg.server.interval, "version": __version__})  # fmt: skip
        elif snap is None:
            self._json({"error": error or "no data yet"}, 503)
        elif path == "/api/stats":
            data = snap.to_dict()
            data["age"] = age
            data["collector_error"] = error
            self._json(data)
        else:
            self._lcd(snap, path.endswith(".txt"), query)

    def _health(self) -> None:
        snap, age, error = self.collector.current()
        limit = max(15.0, self.cfg.server.interval * 4)
        healthy = snap is not None and age is not None and age < limit
        self._json({"ok": healthy, "age": age, "error": error}, 200 if healthy else 503)

    def _lcd(self, snap: Snapshot, text: bool, query: dict[str, list[str]]) -> None:
        try:
            cols = int(query.get("cols", ["20"])[0])
            rows = int(query.get("rows", ["4"])[0])
        except ValueError:
            self._json({"error": "cols and rows must be numbers"}, 400)
            return
        pages = frames(snap, cols, rows)
        if (
            text
        ):  # lines separated by \n, pages by a form feed: trivial to parse on a microcontroller
            body = "\f".join("\n".join(page) for page in pages)
            self._send(200, body.encode("ascii", "replace"), "text/plain; charset=us-ascii")
        else:
            first = pages[0] if pages else []
            self._json(
                {
                    "cols": len(first[0]) if first else cols,
                    "rows": len(first) or rows,
                    "status": snap.status,
                    "pages": pages,
                }
            )


class Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        # A browser that reloads or closes the tab drops the connection mid-answer. That is
        # normal for a display, not an error: do not print a traceback for it.
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def make_server(cfg: Config, collector: Collector) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"collector": collector, "cfg": cfg})
    server = Server((cfg.server.host, cfg.server.port), handler)
    server.daemon_threads = True
    return server
