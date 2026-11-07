"""The `rackdisplay` command."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from types import FrameType

from . import __version__
from .config import Config, ConfigError, load
from .render import frames
from .server import Collector, make_server
from .sources import make_source


def _config(args: argparse.Namespace) -> Config:
    try:
        cfg = load(args.config)
    except ConfigError as error:
        raise SystemExit(f"error: {error}") from error
    if getattr(args, "demo", False):
        cfg.source.type = "demo"
    if getattr(args, "host", None):
        cfg.server.host = args.host
    if getattr(args, "port", None):
        cfg.server.port = args.port
    return cfg


def _source(cfg: Config):  # type: ignore[no-untyped-def]
    try:
        return make_source(cfg)
    except (FileNotFoundError, ConfigError) as error:
        raise SystemExit(f"error: {error}") from error


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = _config(args)
    collector = Collector(_source(cfg), cfg.server.interval)
    try:
        server = make_server(cfg, collector)
    except OSError as error:
        raise SystemExit(
            f"error: cannot listen on {cfg.server.host}:{cfg.server.port}: {error}"
        ) from error
    collector.start()
    shown = "localhost" if cfg.server.host in ("0.0.0.0", "::") else cfg.server.host
    print(
        f"rackdisplay {__version__}: source '{cfg.source.type}', open http://{shown}:{cfg.server.port}/"
    )
    if cfg.server.host not in ("127.0.0.1", "localhost", "::1") and not cfg.server.token:
        print(
            "warning: listening on the network without a token; anyone on it can read the numbers",
            file=sys.stderr,
        )

    def stop(_signal: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        collector.stop()
        server.server_close()
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    cfg = _config(args)
    snap = _source(cfg).collect()
    print(json.dumps(snap.to_dict(), indent=2))
    return 0


def cmd_lcd(args: argparse.Namespace) -> int:
    cfg = _config(args)
    snap = _source(cfg).collect()
    for number, page in enumerate(frames(snap, args.cols, args.rows), 1):
        print(f"--- page {number} " + "-" * max(0, args.cols - 10))
        print("\n".join(f"|{line}|" for line in page))
    return 0


def cmd_check_config(args: argparse.Namespace) -> int:
    cfg = _config(args)
    print(f"ok: source '{cfg.source.type}', {len(cfg.checks)} checks, {len(cfg.pdu)} power meters, "
          f"{len(cfg.tiles)} custom tiles, screens {', '.join(cfg.display.screens)}")  # fmt: skip
    urls = [cfg.source.prometheus_url, cfg.docker.url, *(p.url for p in cfg.pdu if p.url)]
    if sys.platform == "win32" and any("//localhost" in url for url in urls):
        print(
            "note: on Windows 'localhost' can add seconds to every request; "
            "use 127.0.0.1 in the URLs if the page says NO DATA or is slow",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rackdisplay",
        description="Live rack statistics for a wall display: kiosk page and small-screen frames.",
    )
    parser.add_argument("--version", action="version", version=f"rackdisplay {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "-c", "--config", metavar="FILE", help="TOML configuration (defaults apply without one)"
        )
        p.add_argument(
            "--demo", action="store_true", help="use made-up data instead of the configured source"
        )

    p = sub.add_parser("serve", help="run the display server")
    common(p)
    p.add_argument("--host", help="address to listen on (default 127.0.0.1)")
    p.add_argument("--port", type=int, help="port (default 8080)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("snapshot", help="collect once and print the JSON")
    common(p)
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("lcd", help="print the frames for a small text display")
    common(p)
    p.add_argument("--cols", type=int, default=20)
    p.add_argument("--rows", type=int, default=4)
    p.set_defaults(func=cmd_lcd)

    p = sub.add_parser("check-config", help="validate a configuration file")
    common(p)
    p.set_defaults(func=cmd_check_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
