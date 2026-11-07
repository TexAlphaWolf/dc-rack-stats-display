"""The kiosk page in a real browser. Skipped when Playwright or Chromium are not installed."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest

from rackdisplay.config import Config
from rackdisplay.model import Container, Host, Snapshot, finalize
from rackdisplay.server import Collector, make_server

pytestmark = pytest.mark.browser
sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser() -> Iterator[object]:
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as error:  # no browser binary installed
            pytest.skip(f"Chromium not available: {error}")
        yield b
        b.close()


class Hostile:
    """Names that try to become markup."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def collect(self) -> Snapshot:
        import time

        evil = '<img src=x onerror="window.__pwned=1">'
        snap = Snapshot(
            ts=time.time(),
            source="test",
            hosts=[Host(evil, cpu=0.5, mem=0.5)],
            containers=[Container(evil, "running")],
            containers_known=True,
        )
        return finalize(snap, self.cfg.thresholds)


class ManyDisks:
    """More disks than any small screen can show."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def collect(self) -> Snapshot:
        import time

        from rackdisplay.model import Disk

        disks = [Disk(f"/data/{i}", 100 * (i + 1), 2000) for i in range(30)]
        snap = Snapshot(
            ts=time.time(), source="test", hosts=[Host("big", cpu=0.1, mem=0.2, disks=disks)]
        )
        return finalize(snap, self.cfg.thresholds)


def serve(cfg: Config, source: object) -> tuple[object, Collector, str]:
    cfg.server.port = 0
    collector = Collector(source, 60)  # type: ignore[arg-type]
    collector.start()
    server = make_server(cfg, collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, collector, f"http://127.0.0.1:{server.server_address[1]}"


def stop(server: object, collector: Collector) -> None:
    collector.stop()
    server.shutdown()  # type: ignore[attr-defined]
    server.server_close()  # type: ignore[attr-defined]


def test_every_screen_renders_without_errors(browser: object, demo_cfg: Config) -> None:
    from rackdisplay.sources.demo import DemoSource

    server, collector, base = serve(demo_cfg, DemoSource(demo_cfg))
    try:
        page = browser.new_page(viewport={"width": 800, "height": 480})  # type: ignore[attr-defined]
        problems: list[str] = []
        page.on("pageerror", lambda e: problems.append(str(e)))
        page.on(
            "console", lambda m: problems.append(m.text) if m.type in ("error", "warning") else None
        )
        for screen, expected in (
            ("overview", "rack-server"),
            ("storage", "/tank"),
            ("network", "Router"),
            ("containers", "traefik"),
            ("power", "Switch ports up"),
        ):
            page.goto(f"{base}/?screen={screen}")
            page.wait_for_selector("#screen > *")
            assert expected in page.inner_text("#screen")
            assert page.inner_text("#pill") in ("OK", "WARN", "CRIT")
            overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
            assert not overflow, f"{screen} scrolls sideways"
        assert problems == []
    finally:
        stop(server, collector)


def test_hostile_names_are_shown_as_text(browser: object, demo_cfg: Config) -> None:
    server, collector, base = serve(demo_cfg, Hostile(demo_cfg))
    try:
        page = browser.new_page()  # type: ignore[attr-defined]
        for screen in ("overview", "containers"):
            page.goto(f"{base}/?screen={screen}")
            page.wait_for_selector("#screen > *")
            assert "<img" in page.inner_text("#screen")
            assert page.evaluate("window.__pwned") is None
            assert page.locator("#screen img").count() == 0
    finally:
        stop(server, collector)


def test_the_page_says_so_when_the_server_goes_away(browser: object, demo_cfg: Config) -> None:
    from rackdisplay.sources.demo import DemoSource

    demo_cfg.server.interval = 1
    server, collector, base = serve(demo_cfg, DemoSource(demo_cfg))
    page = browser.new_page()  # type: ignore[attr-defined]
    page.goto(f"{base}/?screen=overview")
    page.wait_for_selector("#screen .card")
    page.context.set_offline(True)  # what the wall display sees when the network or server dies
    try:
        sync_api.expect(page.locator("#pill")).to_have_text("NO DATA", timeout=10_000)
        assert "retrying" in page.inner_text("#banner")
        page.context.set_offline(False)
        sync_api.expect(page.locator("#pill")).not_to_have_text("NO DATA", timeout=10_000)
    finally:
        stop(server, collector)


def test_screens_rotate_and_can_be_stepped(browser: object, demo_cfg: Config) -> None:
    from rackdisplay.sources.demo import DemoSource

    server, collector, base = serve(demo_cfg, DemoSource(demo_cfg))
    try:
        page = browser.new_page(viewport={"width": 800, "height": 480})  # type: ignore[attr-defined]
        page.goto(f"{base}/?rotate=3")
        page.wait_for_selector("#screen .card")
        assert page.inner_text("#dots .on").lower() == "overview"
        sync_api.expect(page.locator("#dots .on")).not_to_have_text("overview", timeout=8000)
        page.keyboard.press("ArrowLeft")
        assert page.inner_text("#dots .on").lower() == "overview"
    finally:
        stop(server, collector)


def test_a_long_disk_list_is_cut_to_fit_the_screen(browser: object, demo_cfg: Config) -> None:
    server, collector, base = serve(demo_cfg, ManyDisks(demo_cfg))
    try:
        page = browser.new_page(viewport={"width": 800, "height": 480})  # type: ignore[attr-defined]
        page.goto(f"{base}/?screen=storage")
        page.wait_for_selector("#screen .rows > *")
        assert page.evaluate(
            "document.getElementById('screen').scrollHeight"
            " <= document.getElementById('screen').clientHeight + 1"
        )
        assert "more" in page.inner_text("#screen")
        assert page.locator("#screen .rows > *").count() < 30
    finally:
        stop(server, collector)
