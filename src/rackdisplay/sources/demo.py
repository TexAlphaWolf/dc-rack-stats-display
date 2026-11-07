"""Made-up but lifelike numbers, so the display can be seen with nothing connected.

Everything is a smooth function of the clock plus a fixed seed per item: the same moment always
gives the same picture, which also makes screenshots and tests repeatable.
"""

from __future__ import annotations

import math
import time

from ..config import Config
from ..model import Alert, Container, Disk, Host, PowerItem, Service, Snapshot, Tile, finalize

GB = 1024**3
TB = 1024**4


def _wave(t: float, period: float, phase: float, low: float, high: float) -> float:
    return low + (high - low) * (0.5 + 0.5 * math.sin(2 * math.pi * t / period + phase))


class DemoSource:
    def __init__(self, cfg: Config, clock: float | None = None) -> None:
        self.cfg = cfg
        self.clock = clock  # fixed for tests and screenshots; None follows the real time
        self.boot = (clock if clock is not None else time.time()) - 41 * 86400

    def collect(self) -> Snapshot:
        now = self.clock if self.clock is not None else time.time()
        snap = Snapshot(ts=now, source="demo")
        snap.hosts = [
            Host(
                "rack-server", "linux", True, _wave(now, 90, 0.0, 0.08, 0.46),
                mem_used=_wave(now, 400, 1.0, 21, 26) * GB, mem_total=64 * GB,
                load1=_wave(now, 90, 0.0, 0.3, 2.1), uptime=now - self.boot,
                temp=_wave(now, 240, 2.0, 47, 58),
                rx_bps=_wave(now, 30, 0.0, 0.4e6, 9e6), tx_bps=_wave(now, 45, 1.0, 0.2e6, 4e6),
                disks=[Disk("/", 142 * GB, 468 * GB), Disk("/srv/data", 5.4 * TB, 7.2 * TB),
                       Disk("/srv/backup", 3.0 * TB, 8.0 * TB)],
            ),
            Host(
                "nas", "linux", True, _wave(now, 150, 2.0, 0.03, 0.18),
                mem_used=_wave(now, 500, 0.5, 5, 6.5) * GB, mem_total=16 * GB,
                load1=_wave(now, 150, 2.0, 0.1, 0.6), uptime=now - self.boot + 9 * 86400,
                temp=_wave(now, 300, 0.5, 38, 44),
                rx_bps=_wave(now, 60, 2.0, 0.1e6, 2e6), tx_bps=_wave(now, 50, 0.3, 0.1e6, 6e6),
                disks=[Disk("/", 21 * GB, 110 * GB), Disk("/tank", 10.3 * TB, 12.0 * TB)],
            ),
            Host(
                "desktop", "windows", True, _wave(now, 70, 4.0, 0.12, 0.7),
                mem_used=_wave(now, 200, 3.0, 18, 24) * GB, mem_total=32 * GB,
                uptime=now - self.boot - 38 * 86400,
                rx_bps=_wave(now, 25, 4.0, 0.1e6, 3e6), tx_bps=_wave(now, 35, 0.8, 0.05e6, 1e6),
                disks=[Disk("C:", 410 * GB, 931 * GB), Disk("D:", 1.2 * TB, 1.8 * TB)],
            ),
        ]  # fmt: skip
        names = [
            "traefik", "grafana", "prometheus", "alertmanager", "postgres", "nextcloud",
            "jellyfin", "pihole", "vaultwarden", "loganomaly", "node-exporter", "cadvisor",
        ]  # fmt: skip
        snap.containers = [
            Container(
                n,
                "running",
                _wave(now, 40 + 7 * i, i, 0.002, 0.25),
                _wave(now, 300, i, 40, 700) * 1024**2,
            )
            for i, n in enumerate(names)
        ]
        snap.containers.append(Container("old-test-app", "exited"))
        snap.containers_known = True
        snap.services = [
            Service("Router", "192.168.1.1:443", True, _wave(now, 20, 0.0, 1, 3), "up"),
            Service("Switch", "192.168.1.2:80", True, _wave(now, 25, 1.0, 2, 6), "up"),
            Service("NAS web", "https://nas.lan", True, _wave(now, 35, 2.0, 18, 40), "HTTP 200"),
            Service("Internet", "1.1.1.1:443", True, _wave(now, 15, 3.0, 9, 21), "up"),
            Service("Pi-hole DNS", "192.168.1.5:53", True, _wave(now, 18, 4.0, 1, 4), "up"),
        ]
        snap.power = [
            PowerItem("Server", _wave(now, 90, 0.2, 92, 131)),
            PowerItem("NAS", _wave(now, 150, 2.0, 34, 47)),
            PowerItem("Switch + router", _wave(now, 600, 1.0, 21, 24)),
        ]
        snap.tiles = [
            Tile("Switch ports up", 13, "/ 16"),
            Tile("UPS battery", _wave(now, 3600, 0.0, 96, 100), "%", warn_below=50, crit_below=20),
            Tile("Download speed", 92.4, "Mb/s"),
        ]
        if int(now // 120) % 4 == 3:  # an alert now and then, so that screen can be seen too
            snap.alerts.append(Alert("HostHighTemperature", "warning", "nas is running warm"))
        return finalize(snap, self.cfg.thresholds)
