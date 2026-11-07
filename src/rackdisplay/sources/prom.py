"""Everything a Prometheus server already knows: hosts, containers, probes, alerts.

Written for the metric names of node_exporter, windows_exporter, cAdvisor and the Blackbox
exporter, which is what the dc-monitoring-stack project runs. One display can then show a whole
rack while running on a Raspberry Pi that has no exporters of its own.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from ..checks import run_checks
from ..config import Config
from ..http import FetchError, get_json
from ..model import Alert, Container, Disk, Host, Service, Snapshot, finalize
from .common import add_tiles, prom_query
from .local import _power

Key = tuple[str, str]  # (instance, host label)
Rows = list[tuple[dict[str, str], float]]

_REAL_FS = "ext[234]|xfs|btrfs|zfs|vfat|exfat|ntfs3?|fuseblk|f2fs"
_SKIP_MOUNTS = "/(boot.*|var/lib/docker.*|run.*|snap.*)|/mnt/wsl.*|/parent-distro.*|/etc/.*"
_NET = 'device!~"lo|veth.*|docker.*|br-.*|virbr.*"'

_LINUX = {
    "cpu": '1 - avg by (instance, host) (rate(node_cpu_seconds_total{mode="idle"}[2m]))',
    "mem_total": "node_memory_MemTotal_bytes",
    "mem_avail": "node_memory_MemAvailable_bytes",
    "load1": "node_load1",
    "uptime": "time() - node_boot_time_seconds",
    "temp": "max by (instance, host) (node_hwmon_temp_celsius or node_thermal_zone_temp)",
    "rx": f"sum by (instance, host) (rate(node_network_receive_bytes_total{{{_NET}}}[2m]))",
    "tx": f"sum by (instance, host) (rate(node_network_transmit_bytes_total{{{_NET}}}[2m]))",
}
_WINDOWS = {
    "cpu": '1 - avg by (instance, host) (rate(windows_cpu_time_total{mode="idle"}[2m]))',
    "mem_total": "windows_memory_physical_total_bytes",
    "mem_avail": "windows_memory_available_bytes",
    "uptime": "time() - windows_system_boot_time_timestamp_seconds",
    "rx": "sum by (instance, host) (rate(windows_net_bytes_received_total[2m]))",
    "tx": "sum by (instance, host) (rate(windows_net_bytes_sent_total[2m]))",
}
_FS = f'fstype=~"{_REAL_FS}", mountpoint!~"{_SKIP_MOUNTS}"'
_LINUX_DISK = (
    f"node_filesystem_size_bytes{{{_FS}}}",
    f"node_filesystem_avail_bytes{{{_FS}}}",
    "mountpoint",
)
_WINDOWS_DISK = (
    'windows_logical_disk_size_bytes{volume!~"HarddiskVolume.*"}',
    'windows_logical_disk_free_bytes{volume!~"HarddiskVolume.*"}',
    "volume",
)


def _key(labels: dict[str, str]) -> Key:
    return labels.get("instance", ""), labels.get("host", "")


def _short(instance: str) -> str:
    """'http://grafana:3000/api/health' -> 'grafana:3000/api/health'; 'pc:9182' -> 'pc'."""
    return re.sub(r"^https?://", "", instance)


class PrometheusSource:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.base = cfg.source.prometheus_url
        self.timeout = cfg.source.timeout

    def _q(self, snap: Snapshot, what: str, expr: str) -> Rows:
        try:
            return prom_query(self.base, expr, self.timeout)
        except FetchError as error:
            message = f"prometheus {what}: {error}"
            if message not in snap.problems:
                snap.problems.append(message)
            return []

    def _by_key(self, snap: Snapshot, what: str, expr: str) -> dict[Key, float]:
        return {_key(labels): value for labels, value in self._q(snap, what, expr)}

    # ------------------------------------------------------------------ sections

    def _hosts(self, snap: Snapshot) -> None:
        hosts: dict[Key, Host] = {}
        for labels, value in self._q(snap, "hosts", 'up{job=~"node|windows"}'):
            key = _key(labels)
            name = labels.get("host") or re.sub(r":\d+$", "", key[0]) or "?"
            kind = "windows" if labels.get("job") == "windows" else "linux"
            hosts[key] = Host(name=name, kind=kind, up=value >= 1)
        if not hosts:
            return
        for kind, queries, disk_queries in (
            ("linux", _LINUX, _LINUX_DISK),
            ("windows", _WINDOWS, _WINDOWS_DISK),
        ):
            mine = {k for k, h in hosts.items() if h.kind == kind}
            if not mine:
                continue
            data = {name: self._by_key(snap, name, expr) for name, expr in queries.items()}
            for key in mine:
                host = hosts[key]
                host.cpu = _clamp(data["cpu"].get(key))
                total, avail = data["mem_total"].get(key), data["mem_avail"].get(key)
                if total and avail is not None:
                    host.mem_total, host.mem_used = total, total - avail
                host.load1 = data.get("load1", {}).get(key)
                host.uptime = data["uptime"].get(key) if "uptime" in data else None
                host.temp = data.get("temp", {}).get(key)
                host.rx_bps, host.tx_bps = data["rx"].get(key), data["tx"].get(key)
            self._disks(snap, hosts, mine, *disk_queries)
        snap.hosts = sorted(hosts.values(), key=lambda h: h.name)

    def _disks(
        self,
        snap: Snapshot,
        hosts: dict[Key, Host],
        mine: set[Key],
        size_q: str,
        avail_q: str,
        label: str,
    ) -> None:
        sizes = {(*_key(lb), lb.get(label, "?")): v for lb, v in self._q(snap, "disks", size_q)}
        avails = {(*_key(lb), lb.get(label, "?")): v for lb, v in self._q(snap, "disks", avail_q)}
        for (instance, host_label, mount), size in sorted(sizes.items()):
            key = (instance, host_label)
            if key in mine and size > 0 and (instance, host_label, mount) in avails:
                free = avails[(instance, host_label, mount)]
                hosts[key].disks.append(Disk(mount, size - free, size))

    def _containers(self, snap: Snapshot) -> None:
        mem = self._q(
            snap, "containers", 'sum by (name) (container_memory_working_set_bytes{name!=""})'
        )
        if not mem:
            return
        cpu = {
            lb.get("name", ""): v
            for lb, v in self._q(
                snap,
                "containers",
                'sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[2m]))',
            )
        }
        snap.containers_known = True
        snap.containers = sorted(
            (
                Container(lb.get("name", "?"), "running", cpu.get(lb.get("name", "")), v)
                for lb, v in mem
            ),
            key=lambda c: c.name,
        )

    def _services(self, snap: Snapshot) -> None:
        latency = {
            lb.get("instance", ""): v
            for lb, v in self._q(snap, "probes", 'probe_duration_seconds{job=~"probe-.*"}')
        }
        for labels, value in self._q(snap, "probes", 'probe_success{job=~"probe-.*"}'):
            instance = labels.get("instance", "?")
            seconds = latency.get(instance)
            snap.services.append(
                Service(
                    _short(instance),
                    instance,
                    value >= 1,
                    seconds * 1000 if seconds is not None else None,
                    "" if value >= 1 else "probe failed",
                )
            )
        snap.services.sort(key=lambda s: s.name)

    def _alerts(self, snap: Snapshot) -> None:
        try:
            data = get_json(f"{self.base.rstrip('/')}/api/v1/alerts", self.timeout)
            for alert in data["data"]["alerts"]:
                labels = alert.get("labels", {})
                if alert.get("state") != "firing" or labels.get("alertname") == "Watchdog":
                    continue
                snap.alerts.append(
                    Alert(
                        str(labels.get("alertname", "?")),
                        str(labels.get("severity", "warning")),
                        str(alert.get("annotations", {}).get("summary", "")),
                    )
                )
        except (FetchError, KeyError, TypeError) as error:
            snap.problems.append(f"prometheus alerts: {error}")

    def collect(self) -> Snapshot:
        snap = Snapshot(ts=time.time(), source="prometheus")
        steps: list[Callable[[Snapshot], None]] = [
            self._hosts,
            self._containers,
            self._services,
            self._alerts,
        ]
        for step in steps:
            step(snap)
        snap.services += run_checks(self.cfg.checks)
        snap.power = _power(self.cfg.pdu, snap, self.timeout)
        add_tiles(snap, self.cfg)
        return finalize(snap, self.cfg.thresholds)


def _clamp(value: float | None) -> float | None:
    return None if value is None else max(0.0, min(1.0, value))
