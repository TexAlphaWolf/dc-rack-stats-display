from __future__ import annotations

import json
import re
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from rackdisplay import metrics
from rackdisplay.cli import main
from rackdisplay.config import Config
from rackdisplay.model import Host, Snapshot, finalize
from rackdisplay.render import frames
from rackdisplay.server import CSP, Collector, make_server
from rackdisplay.sources.demo import DemoSource

WEB = Path(__file__).resolve().parent.parent / "src" / "rackdisplay" / "web"


class Running:
    def __init__(self, cfg: Config, source: Any = None) -> None:
        cfg.server.port = 0
        self.cfg = cfg
        self.collector = Collector(source or DemoSource(cfg), 60)
        self.collector.start()
        self.server = make_server(cfg, self.collector)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(
        self, path: str, headers: dict[str, str] | None = None, method: str = "GET"
    ) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(self.base + path, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, dict(error.headers), error.read()

    def close(self) -> None:
        self.collector.stop()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def running(demo_cfg: Config) -> Iterator[Running]:
    r = Running(demo_cfg)
    yield r
    r.close()


def test_api_stats(running: Running) -> None:
    status, headers, body = running.get("/api/stats")
    data = json.loads(body)
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert [h["name"] for h in data["hosts"]] == ["rack-server", "nas", "desktop"]
    assert data["source"] == "demo"
    assert data["power_total"] > 0
    assert data["age"] is not None


def test_api_config_and_health(running: Running) -> None:
    config = json.loads(running.get("/api/config")[2])
    assert config["screens"] == ["overview", "storage", "network", "containers", "power"]
    status, _, body = running.get("/healthz")
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_static_files_and_security_headers(running: Running) -> None:
    for path, kind in (
        ("/", "text/html"),
        ("/app.js", "text/javascript"),
        ("/style.css", "text/css"),
    ):
        status, headers, body = running.get(path)
        assert status == 200
        assert headers["Content-Type"].startswith(kind)
        assert headers["Content-Security-Policy"] == CSP
        assert headers["Referrer-Policy"] == "no-referrer"
        assert body
    status, headers, body = running.get("/", method="HEAD")
    assert status == 200
    assert body == b""
    assert running.get("/nope")[0] == 404
    assert running.get("/../../etc/passwd")[0] == 404


def test_the_page_never_uses_innerhtml_or_inline_code() -> None:
    js = (WEB / "app.js").read_text()
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", js)
    html = (WEB / "index.html").read_text()
    assert "<script>" not in html
    assert not re.search(r"\son\w+=", html)
    assert not re.search(
        r"https?://",
        html + (WEB / "style.css").read_text() + js.replace("http://www.w3.org/2000/svg", ""),
    )


def test_lcd_frames_endpoint(running: Running) -> None:
    data = json.loads(running.get("/api/lcd?cols=16&rows=2")[2])
    assert (data["cols"], data["rows"]) == (16, 2)
    assert all(len(line) == 16 for page in data["pages"] for line in page)
    assert all(len(page) == 2 for page in data["pages"])
    text = running.get("/api/lcd.txt?cols=20&rows=4")[2].decode()
    pages = text.split("\f")
    snap, _, _ = running.collector.current()
    assert snap is not None
    assert len(pages) == len(frames(snap, 20, 4))
    assert all(len(line) == 20 for line in pages[0].split("\n"))
    assert running.get("/api/lcd?cols=abc")[0] == 400
    assert json.loads(running.get("/api/lcd?cols=1000&rows=1000")[2])["cols"] == 40  # clamped


def test_metrics_endpoint(running: Running) -> None:
    status, headers, body = running.get("/metrics")
    text = body.decode()
    assert status == 200
    assert headers["Content-Type"].startswith("text/plain")
    assert 'rackdisplay_host_cpu_ratio{host="rack-server"}' in text
    assert "rackdisplay_power_watts" in text
    assert "rackdisplay_containers_running 12" in text
    for line in text.splitlines():
        assert line.startswith("#") or re.fullmatch(r"[a-z_]+(\{.*\})? [-0-9.e+]+", line), line


def test_token_protects_the_data_but_not_the_page(demo_cfg: Config) -> None:
    demo_cfg.server.token = "s3cret"
    r = Running(demo_cfg)
    try:
        assert r.get("/")[0] == 200
        assert r.get("/healthz")[0] == 200
        for path in ("/api/stats", "/api/lcd", "/api/lcd.txt", "/api/config", "/metrics"):
            status, headers, _ = r.get(path)
            assert status == 401
            assert headers["WWW-Authenticate"] == "Bearer"
        assert r.get("/api/stats", {"Authorization": "Bearer wrong"})[0] == 401
        assert r.get("/api/stats", {"Authorization": "Bearer s3cret"})[0] == 200
        assert r.get("/api/stats?token=s3cret")[0] == 200
        assert r.get("/api/stats?token=")[0] == 401
    finally:
        r.close()


def test_a_failing_source_does_not_kill_the_server(demo_cfg: Config) -> None:
    class Broken:
        calls = 0

        def collect(self) -> Snapshot:
            Broken.calls += 1
            if Broken.calls > 1:
                raise RuntimeError("sensor exploded")
            return finalize(
                Snapshot(ts=__import__("time").time(), source="x", hosts=[Host("h", cpu=0.1)]),
                demo_cfg.thresholds,
            )

    r = Running(demo_cfg, Broken())
    try:
        assert r.get("/api/stats")[0] == 200
        r.collector.collect_once()
        data = json.loads(r.get("/api/stats")[2])
        assert "sensor exploded" in data["collector_error"]
        assert r.get("/healthz")[0] == 200  # still the old, recent snapshot
    finally:
        r.close()


def test_no_data_yet_and_stale_health(demo_cfg: Config) -> None:
    class Never:
        def collect(self) -> Snapshot:
            raise RuntimeError("down")

    r = Running(demo_cfg, Never())
    try:
        status, _, body = r.get("/api/stats")
        assert status == 503
        assert "down" in json.loads(body)["error"]
        assert r.get("/healthz")[0] == 503
        assert r.get("/metrics")[0] == 200
        assert r.get("/api/lcd")[0] == 503
    finally:
        r.close()
    r = Running(demo_cfg, DemoSource(demo_cfg, clock=1_794_000_000.0))  # a snapshot from long ago
    try:
        assert r.get("/healthz")[0] == 503
    finally:
        r.close()


def test_metrics_escape_label_values() -> None:
    snap = finalize(
        Snapshot(ts=0, source="x", hosts=[Host('we"ird\\name\n', cpu=0.5)]), Config().thresholds
    )
    text = metrics.render(snap, 1.0)
    assert 'host="we\\"ird\\\\name\\n"' in text
    assert metrics.render(None, None).strip() == ""


def test_lcd_frames_fit_every_size(demo_snapshot: Snapshot) -> None:
    for cols in (8, 16, 20, 40):
        for rows in (1, 2, 4, 8):
            pages = frames(demo_snapshot, cols, rows)
            assert pages
            assert all(len(p) == rows and all(len(line) == cols for line in p) for p in pages)
    ascii_only = frames(
        finalize(
            Snapshot(ts=0, source="x", hosts=[Host("Café ☃", cpu=0.2, mem=0.3)]),
            Config().thresholds,
        )
    )
    assert all(ch.isascii() for page in ascii_only for line in page for ch in line)


def test_lcd_shows_down_hosts_and_containers() -> None:
    from rackdisplay.model import Container

    snap = Snapshot(
        ts=0,
        source="x",
        hosts=[Host("dead", up=False)],
        containers=[Container("db", "restarting")],
        containers_known=True,
    )
    text = "\n".join("\n".join(p) for p in frames(finalize(snap, Config().thresholds), 20, 4))
    assert "dead DOWN" in text
    assert "Containers 0/1" in text
    assert "db res" in text


# ----------------------------------------------------------------------------- command line


def test_cli_snapshot_lcd_and_check_config(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["snapshot", "--demo"]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "demo"
    assert main(["lcd", "--demo", "--cols", "16", "--rows", "2"]) == 0
    assert "--- page 1" in capsys.readouterr().out
    cfg = tmp_path / "c.toml"
    cfg.write_text("[display]\ntitle = 'T'\n")
    assert main(["check-config", "-c", str(cfg)]) == 0
    assert "ok:" in capsys.readouterr().out


def test_check_config_warns_about_localhost_on_windows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text("[source]\ntype = 'prometheus'\nprometheus_url = 'http://localhost:9090'\n")
    monkeypatch.setattr(sys, "platform", "linux")
    assert main(["check-config", "-c", str(cfg)]) == 0
    assert "127.0.0.1" not in capsys.readouterr().err
    monkeypatch.setattr(sys, "platform", "win32")
    assert main(["check-config", "-c", str(cfg)]) == 0
    assert "127.0.0.1" in capsys.readouterr().err


def test_cli_errors(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="config file not found"):
        main(["check-config", "-c", str(tmp_path / "nope.toml")])
    bad = tmp_path / "bad.toml"
    bad.write_text("[server]\nport = 0\n")
    with pytest.raises(SystemExit, match="port"):
        main(["check-config", "-c", str(bad)])
    nolinux = tmp_path / "nolinux.toml"
    nolinux.write_text(f"[source]\nproc = '{tmp_path}'\n")
    with pytest.raises(SystemExit, match="needs Linux"):
        main(["snapshot", "-c", str(nolinux)])


def test_cli_serve_stops_on_interrupt(
    monkeypatch: pytest.MonkeyPatch, free_port: int, capsys: pytest.CaptureFixture[str]
) -> None:
    from http.server import ThreadingHTTPServer

    def interrupted(self: ThreadingHTTPServer, poll_interval: float = 0.5) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", interrupted)
    assert main(["serve", "--demo", "--host", "0.0.0.0", "--port", str(free_port)]) == 0
    captured = capsys.readouterr()
    assert f"http://localhost:{free_port}/" in captured.out
    assert "without a token" in captured.err


def test_cli_serve_reports_a_busy_port(free_port: int) -> None:
    import socket

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", free_port))
        busy.listen()
        with pytest.raises(SystemExit, match="cannot listen"):
            main(["serve", "--demo", "--port", str(free_port)])


def test_python_dash_m_entry_point() -> None:
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "rackdisplay", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "rackdisplay 1.0.0" in out.stdout


def test_a_dropped_connection_is_not_an_error(
    running: Running, capsys: pytest.CaptureFixture[str]
) -> None:
    server = running.server
    try:
        raise ConnectionAbortedError("the browser went away")
    except ConnectionError:
        server.handle_error(None, ("127.0.0.1", 1))  # type: ignore[arg-type]
    assert capsys.readouterr().err == ""
    try:
        raise ValueError("a real bug")
    except ValueError:
        server.handle_error(None, ("127.0.0.1", 1))  # type: ignore[arg-type]
    assert "a real bug" in capsys.readouterr().err
