"""The snapshot every source produces and every display reads.

A source fills in what it can; sections it cannot provide stay empty and the displays skip them.
`finalize` then adds the status of each item from the configured thresholds, so that all
displays (web page, LCD frames, metrics) agree on what is a warning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

OK, WARN, CRIT, UNKNOWN = "ok", "warn", "crit", "unknown"
_RANK = {UNKNOWN: 0, OK: 1, WARN: 2, CRIT: 3}


def worst(levels: list[str]) -> str:
    """The most serious of several statuses (unknown only if nothing is known)."""
    return max(levels, key=lambda s: _RANK[s], default=UNKNOWN)


@dataclass
class Thresholds:
    cpu_warn: float = 0.80
    cpu_crit: float = 0.95
    mem_warn: float = 0.85
    mem_crit: float = 0.95
    disk_warn: float = 0.85
    disk_crit: float = 0.95
    temp_warn: float = 70.0
    temp_crit: float = 85.0


def level(value: float | None, warn: float, crit: float) -> str:
    """Status of a value where bigger is worse."""
    if value is None:
        return UNKNOWN
    if value >= crit:
        return CRIT
    if value >= warn:
        return WARN
    return OK


@dataclass
class Disk:
    mount: str
    used: float  # bytes
    total: float  # bytes
    pct: float = 0.0
    status: str = UNKNOWN


@dataclass
class Host:
    name: str
    kind: str = "linux"  # linux or windows
    up: bool = True
    cpu: float | None = None  # 0..1
    mem: float | None = None  # 0..1
    mem_used: float | None = None  # bytes
    mem_total: float | None = None  # bytes
    load1: float | None = None
    uptime: float | None = None  # seconds
    temp: float | None = None  # degrees Celsius, the hottest sensor
    rx_bps: float | None = None
    tx_bps: float | None = None
    disks: list[Disk] = field(default_factory=list)
    status: str = UNKNOWN


@dataclass
class Container:
    name: str
    state: str = "running"  # running, restarting, exited, unhealthy, ...
    cpu: float | None = None  # cores in use
    mem: float | None = None  # bytes
    status: str = UNKNOWN


@dataclass
class Service:
    name: str
    target: str = ""
    ok: bool = False
    latency_ms: float | None = None
    detail: str = ""
    status: str = UNKNOWN


@dataclass
class PowerItem:
    name: str
    watts: float | None = None


@dataclass
class Tile:
    """A number from a custom query, with optional limits."""

    name: str
    value: float | None = None
    unit: str = ""
    warn_above: float | None = None
    crit_above: float | None = None
    warn_below: float | None = None
    crit_below: float | None = None
    status: str = UNKNOWN


@dataclass
class Alert:
    name: str
    severity: str = "warning"
    summary: str = ""


@dataclass
class Snapshot:
    ts: float
    source: str
    hosts: list[Host] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)
    containers_known: bool = False  # distinguishes "no containers" from "not monitored"
    services: list[Service] = field(default_factory=list)
    power: list[PowerItem] = field(default_factory=list)
    tiles: list[Tile] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # collectors that failed, in words
    status: str = UNKNOWN

    def power_total(self) -> float | None:
        known = [p.watts for p in self.power if p.watts is not None]
        return sum(known) if known else None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["power_total"] = self.power_total()
        return data


def tile_status(tile: Tile) -> str:
    v = tile.value
    if v is None:
        return UNKNOWN
    if (tile.crit_above is not None and v >= tile.crit_above) or (
        tile.crit_below is not None and v <= tile.crit_below
    ):
        return CRIT
    if (tile.warn_above is not None and v >= tile.warn_above) or (
        tile.warn_below is not None and v <= tile.warn_below
    ):
        return WARN
    return OK


def finalize(snap: Snapshot, t: Thresholds) -> Snapshot:
    """Fill in every status and the overall one. Safe to call twice."""
    overall: list[str] = []
    for host in snap.hosts:
        for disk in host.disks:
            disk.pct = disk.used / disk.total if disk.total > 0 else 0.0
            disk.status = level(disk.pct, t.disk_warn, t.disk_crit)
        if host.mem is None and host.mem_used is not None and host.mem_total:
            host.mem = host.mem_used / host.mem_total
        if not host.up:
            host.status = CRIT
        else:
            parts = [
                level(host.cpu, t.cpu_warn, t.cpu_crit),
                level(host.mem, t.mem_warn, t.mem_crit),
                level(host.temp, t.temp_warn, t.temp_crit),
                *(d.status for d in host.disks),
            ]
            host.status = worst(parts)
        overall.append(host.status)
    for c in snap.containers:
        c.status = OK if c.state == "running" else (WARN if c.state == "exited" else CRIT)
    overall += [c.status for c in snap.containers if c.state != "exited"]
    for s in snap.services:
        s.status = OK if s.ok else CRIT
    overall += [s.status for s in snap.services]
    for tile in snap.tiles:
        tile.status = tile_status(tile)
    overall += [tile.status for tile in snap.tiles]
    if any(a.severity == "critical" for a in snap.alerts):
        overall.append(CRIT)
    elif snap.alerts:
        overall.append(WARN)
    snap.status = worst(overall)
    return snap
