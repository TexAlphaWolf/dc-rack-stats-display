"""The display's own numbers in the Prometheus text format, so Prometheus can scrape it too."""

from __future__ import annotations

from .model import Snapshot

_RANK = {"unknown": 0, "ok": 1, "warn": 2, "crit": 3}


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels: str) -> str:
    return "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items()) + "}" if labels else ""


def render(snap: Snapshot | None, age: float | None) -> str:
    lines: list[str] = []

    def metric(name: str, help_text: str, rows: list[tuple[str, float]]) -> None:
        if not rows:
            return
        lines.append(f"# HELP rackdisplay_{name} {help_text}")
        lines.append(f"# TYPE rackdisplay_{name} gauge")
        lines.extend(f"rackdisplay_{name}{lab} {value:g}" for lab, value in rows)

    metric("snapshot_age_seconds", "Seconds since the last successful collection.",
           [("", age)] if age is not None else [])  # fmt: skip
    if snap is None:
        return "\n".join(lines) + "\n"
    metric("status", "Overall status: 0 unknown, 1 ok, 2 warn, 3 crit.", [("", _RANK[snap.status])])
    metric("problems", "Collectors that failed in the last collection.", [("", len(snap.problems))])
    hosts = snap.hosts
    metric(
        "host_up", "1 if the host answers.", [(_labels(host=h.name), float(h.up)) for h in hosts]
    )
    metric(
        "host_cpu_ratio",
        "CPU busy share, 0 to 1.",
        [(_labels(host=h.name), h.cpu) for h in hosts if h.cpu is not None],
    )
    metric(
        "host_memory_ratio",
        "Memory in use, 0 to 1.",
        [(_labels(host=h.name), h.mem) for h in hosts if h.mem is not None],
    )
    metric(
        "host_temperature_celsius",
        "Hottest sensor.",
        [(_labels(host=h.name), h.temp) for h in hosts if h.temp is not None],
    )
    disks = [(_labels(host=h.name, mount=d.mount), d.pct) for h in hosts for d in h.disks]
    metric("disk_used_ratio", "Disk space in use, 0 to 1.", disks)
    metric(
        "service_up",
        "1 if the check succeeds.",
        [(_labels(name=s.name), float(s.ok)) for s in snap.services],
    )
    if snap.containers_known:
        metric("containers_running", "Containers in the running state.",
               [("", sum(1 for c in snap.containers if c.state == "running"))])  # fmt: skip
        metric("containers_total", "Containers known to the engine.", [("", len(snap.containers))])
    metric(
        "power_watts",
        "Power draw.",
        [(_labels(name=p.name), p.watts) for p in snap.power if p.watts is not None],
    )
    metric(
        "alerts_firing",
        "Alerts firing in Prometheus.",
        [("", len(snap.alerts))] if snap.source == "prometheus" else [],
    )
    return "\n".join(lines) + "\n"
