"""Configuration: one TOML file, checked on load so a typo fails at start, not at 3 a.m."""

from __future__ import annotations

import os
import tomllib
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any

from .model import Thresholds

SCREENS = ("overview", "storage", "network", "containers", "power")
SOURCES = ("local", "prometheus", "demo")
PDU_TYPES = ("shelly", "tasmota", "http-json")
CHECK_TYPES = ("tcp", "http")


class ConfigError(Exception):
    """The configuration file is missing, unreadable or has a value we cannot use."""


@dataclass
class Server:
    host: str = "127.0.0.1"
    port: int = 8080
    interval: float = 5.0  # seconds between collections
    token: str = ""  # when set, /api and /metrics need it (Authorization: Bearer, or ?token=)


@dataclass
class Display:
    title: str = "Rack"
    rotate_seconds: int = 15
    screens: list[str] = field(default_factory=lambda: list(SCREENS))


@dataclass
class Source:
    type: str = "local"
    name: str = (
        ""  # shown instead of the machine's own name (inside a container that is the container id)
    )
    proc: str = "/proc"
    sys: str = "/sys"
    prometheus_url: str = ""
    timeout: float = 4.0


@dataclass
class DiskSpec:
    mount: str
    name: str = ""


@dataclass
class CheckSpec:
    name: str
    type: str
    target: str
    verify_tls: bool = True


@dataclass
class PduSpec:
    name: str
    type: str
    url: str
    path: str = ""  # http-json only: where the watts are, e.g. "meters.0.power"


@dataclass
class TileSpec:
    name: str
    query: str
    unit: str = ""
    warn_above: float | None = None
    crit_above: float | None = None
    warn_below: float | None = None
    crit_below: float | None = None


@dataclass
class DockerSpec:
    enabled: bool = False
    socket: str = "/var/run/docker.sock"
    url: str = ""  # a docker socket proxy, e.g. http://docker-proxy:2375


@dataclass
class Config:
    server: Server = field(default_factory=Server)
    display: Display = field(default_factory=Display)
    source: Source = field(default_factory=Source)
    thresholds: Thresholds = field(default_factory=Thresholds)
    docker: DockerSpec = field(default_factory=DockerSpec)
    disks: list[DiskSpec] = field(default_factory=lambda: [DiskSpec("/", "root")])
    checks: list[CheckSpec] = field(default_factory=list)
    pdu: list[PduSpec] = field(default_factory=list)
    tiles: list[TileSpec] = field(default_factory=list)


def _build(cls: type, data: object, where: str) -> Any:
    """Make a dataclass from a TOML table, rejecting unknown keys and wrong types."""
    if not isinstance(data, dict):
        raise ConfigError(f"[{where}] must be a table")
    known = {f.name: f for f in fields(cls)}
    for key in data:
        if key not in known:
            raise ConfigError(
                f"[{where}] unknown key '{key}' (allowed: {', '.join(sorted(known))})"
            )
    values = {}
    for key, value in data.items():
        default = known[key].default
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, int | float) and not isinstance(default, bool):
            ok = isinstance(value, int | float) and not isinstance(value, bool)
        elif isinstance(default, str):
            ok = isinstance(value, str)
        else:
            ok = True
        if not ok:
            raise ConfigError(f"[{where}] '{key}' has the wrong type ({type(value).__name__})")
        values[key] = value
    required = [
        f.name
        for f in fields(cls)
        if f.default is MISSING and f.default_factory is MISSING and f.name not in values
    ]
    if required:
        raise ConfigError(f"[{where}] missing required key(s): {', '.join(required)}")
    return cls(**values)


def parse(data: dict[str, Any]) -> Config:
    """Build and validate a Config from a parsed TOML document."""
    allowed = {f.name for f in fields(Config)}
    for key in data:
        if key not in allowed:
            raise ConfigError(f"unknown section '{key}' (allowed: {', '.join(sorted(allowed))})")
    cfg = Config()
    for name in ("server", "display", "source", "thresholds", "docker"):
        if name in data:
            setattr(cfg, name, _build(type(getattr(cfg, name)), data[name], name))
    for name, cls in (
        ("disks", DiskSpec),
        ("checks", CheckSpec),
        ("pdu", PduSpec),
        ("tiles", TileSpec),
    ):
        if name in data:
            rows = data[name]
            if not isinstance(rows, list):
                raise ConfigError(f"[[{name}]] must be an array of tables")
            setattr(cfg, name, [_build(cls, row, f"{name}[{i}]") for i, row in enumerate(rows)])
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    if cfg.source.type not in SOURCES:
        raise ConfigError(f"[source] type must be one of {', '.join(SOURCES)}")
    if cfg.source.type == "prometheus" and not cfg.source.prometheus_url:
        raise ConfigError('[source] prometheus_url is required when type = "prometheus"')
    if cfg.source.prometheus_url and not cfg.source.prometheus_url.startswith(
        ("http://", "https://")
    ):
        raise ConfigError("[source] prometheus_url must start with http:// or https://")
    if not 1 <= cfg.server.port <= 65535:
        raise ConfigError("[server] port must be between 1 and 65535")
    if cfg.server.interval < 1:
        raise ConfigError("[server] interval must be at least 1 second")
    if cfg.display.rotate_seconds < 3:
        raise ConfigError("[display] rotate_seconds must be at least 3")
    bad = [s for s in cfg.display.screens if s not in SCREENS]
    if bad or not cfg.display.screens:
        raise ConfigError(f"[display] screens must be a non-empty list of: {', '.join(SCREENS)}")
    for check in cfg.checks:
        if check.type not in CHECK_TYPES:
            raise ConfigError(f"checks '{check.name}': type must be tcp or http")
        if check.type == "tcp" and ":" not in check.target:
            raise ConfigError(f"checks '{check.name}': a tcp target looks like host:port")
        if check.type == "http" and not check.target.startswith(("http://", "https://")):
            raise ConfigError(
                f"checks '{check.name}': an http target starts with http:// or https://"
            )
    for pdu in cfg.pdu:
        if pdu.type not in PDU_TYPES:
            raise ConfigError(f"pdu '{pdu.name}': type must be one of {', '.join(PDU_TYPES)}")
        if not pdu.url.startswith(("http://", "https://")):
            raise ConfigError(f"pdu '{pdu.name}': url must start with http:// or https://")
        if pdu.type == "http-json" and not pdu.path:
            raise ConfigError(f"pdu '{pdu.name}': http-json needs a path to the watts value")
    if cfg.tiles and not cfg.source.prometheus_url:
        raise ConfigError("[[tiles]] run PromQL queries: set [source] prometheus_url")
    if cfg.docker.url and not cfg.docker.url.startswith(("http://", "https://")):
        raise ConfigError("[docker] url must start with http:// or https://")


def load(path: str | Path | None) -> Config:
    """Read a config file. With no path the defaults apply; RACKDISPLAY_TOKEN fills the token."""
    cfg = Config()
    if path is not None:
        try:
            with open(path, "rb") as handle:
                data = tomllib.load(handle)
        except FileNotFoundError as error:
            raise ConfigError(f"config file not found: {path}") from error
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(f"{path} is not valid TOML: {error}") from error
        cfg = parse(data)
    token = os.environ.get("RACKDISPLAY_TOKEN")
    if token and not cfg.server.token:
        cfg.server.token = token
    return cfg
