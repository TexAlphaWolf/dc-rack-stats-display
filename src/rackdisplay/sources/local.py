"""This machine, read straight from /proc and /sys (Linux). No agent, no dependencies."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from ..checks import run_checks
from ..config import Config, PduSpec
from ..docker_api import list_containers
from ..http import FetchError
from ..model import Disk, Host, PowerItem, Snapshot, finalize
from ..power import read_power
from .common import add_tiles

_SKIP_IFACE = ("lo", "veth", "docker", "br-", "virbr", "tailscale", "wg")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def cpu_times(stat: str) -> tuple[float, float]:
    """(busy, total) jiffies from the first line of /proc/stat."""
    fields = [float(x) for x in stat.splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0.0)  # idle + iowait
    total = sum(fields[:8])  # user..steal; guest time is already inside user
    return total - idle, total


def meminfo(text: str) -> tuple[float, float]:
    """(used, total) bytes, 'used' meaning total minus what is available."""
    values: dict[str, float] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            values[key] = float(parts[0]) * 1024
    total = values["MemTotal"]
    available = values.get("MemAvailable", values.get("MemFree", 0.0))
    return total - available, total


def net_bytes(text: str) -> tuple[float, float]:
    """(received, transmitted) bytes over every real interface in /proc/net/dev."""
    rx = tx = 0.0
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        if not rest or name.startswith(_SKIP_IFACE):
            continue
        cols = rest.split()
        rx += float(cols[0])
        tx += float(cols[8])
    return rx, tx


class LocalSource:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.proc = Path(cfg.source.proc)
        self.sys = Path(cfg.source.sys)
        self._cpu: tuple[float, float] | None = None
        self._net: tuple[float, float, float] | None = None
        if not (self.proc / "stat").is_file():
            raise FileNotFoundError(
                f"{self.proc}/stat not found: the local source needs Linux "
                "(use the prometheus or demo source elsewhere)"
            )
        try:  # a first sample now, so the very first screen already has rates to show
            self._cpu_ratio()
            self._net_rates()
            time.sleep(0.2)
        except (OSError, ValueError, IndexError):
            pass

    # ------------------------------------------------------------------ pieces

    def _cpu_ratio(self) -> float | None:
        busy, total = cpu_times(_read(self.proc / "stat"))
        previous, self._cpu = self._cpu, (busy, total)
        if previous is None or total <= previous[1]:
            return None
        return max(0.0, min(1.0, (busy - previous[0]) / (total - previous[1])))

    def _net_rates(self) -> tuple[float | None, float | None]:
        rx, tx = net_bytes(_read(self.proc / "net" / "dev"))
        now = time.monotonic()
        previous, self._net = self._net, (rx, tx, now)
        if previous is None or now <= previous[2] or rx < previous[0] or tx < previous[1]:
            return None, None
        span = now - previous[2]
        return (rx - previous[0]) / span, (tx - previous[1]) / span

    def _temperature(self) -> float | None:
        readings: list[float] = []
        for pattern in ("class/hwmon/hwmon*/temp*_input", "class/thermal/thermal_zone*/temp"):
            for path in sorted(self.sys.glob(pattern)):
                try:
                    value = float(_read(path).strip()) / 1000
                except (OSError, ValueError):
                    continue
                if -40 < value < 150:
                    readings.append(value)
        return max(readings) if readings else None

    def _disks(self) -> list[Disk]:
        found = []
        for spec in self.cfg.disks:
            try:
                st = os.statvfs(spec.mount)
            except OSError:
                continue
            total = (st.f_blocks - st.f_bfree + st.f_bavail) * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            if total > 0:
                found.append(Disk(spec.name or spec.mount, float(used), float(total)))
        return found

    def _host(self) -> Host:
        used, total = meminfo(_read(self.proc / "meminfo"))
        rx, tx = self._net_rates()
        name = self.cfg.source.name
        if not name:
            try:
                name = _read(self.proc / "sys" / "kernel" / "hostname").strip()
            except OSError:
                name = ""
        name = name or socket.gethostname()
        load1: float | None = None
        uptime: float | None = None
        try:
            load1 = float(_read(self.proc / "loadavg").split()[0])
            uptime = float(_read(self.proc / "uptime").split()[0])
        except (OSError, ValueError, IndexError):
            pass
        return Host(
            name=name,
            kind="linux",
            cpu=self._cpu_ratio(),
            mem_used=used,
            mem_total=total,
            load1=load1,
            uptime=uptime,
            temp=self._temperature(),
            rx_bps=rx,
            tx_bps=tx,
            disks=self._disks(),
        )

    # ------------------------------------------------------------------ the whole

    def collect(self) -> Snapshot:
        snap = Snapshot(ts=time.time(), source="local")
        try:
            snap.hosts.append(self._host())
        except (OSError, ValueError, KeyError, IndexError) as error:
            snap.problems.append(f"this machine: {error}")
        if self.cfg.docker.enabled:
            try:
                snap.containers = list_containers(self.cfg.docker, self.cfg.source.timeout)
                snap.containers_known = True
            except FetchError as error:
                snap.problems.append(f"docker: {error}")
        snap.services = run_checks(self.cfg.checks)
        snap.power = _power(self.cfg.pdu, snap, self.cfg.source.timeout)
        if self.cfg.tiles:
            add_tiles(snap, self.cfg)
        return finalize(snap, self.cfg.thresholds)


def _power(specs: list[PduSpec], snap: Snapshot, timeout: float) -> list[PowerItem]:
    items = []
    for spec in specs:
        try:
            items.append(read_power(spec, timeout))
        except FetchError as error:
            snap.problems.append(f"power {spec.name}: {error}")
            items.append(PowerItem(spec.name, None))
    return items
