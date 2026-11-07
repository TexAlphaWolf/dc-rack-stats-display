"""Plain-text frames for displays too small for a web page: 16x2, 20x4 or 128x64 OLEDs.

A frame is a list of exactly `rows` strings of exactly `cols` characters. The content is cut
into as many pages as needed; the device shows one page after another.
"""

from __future__ import annotations

from .fmt import ascii_only, pct, rate, size
from .model import Snapshot

MIN_COLS, MAX_COLS = 8, 40
MIN_ROWS, MAX_ROWS = 1, 16


def _fit(text: str, cols: int) -> str:
    return ascii_only(text)[:cols].ljust(cols)


def _lines(snap: Snapshot, cols: int) -> list[str]:
    """Every fact as one line that fits `cols`, grouped so that related lines stay together."""
    out: list[str] = []
    alerts = len(snap.alerts)
    out.append(
        f"RACK {snap.status.upper()}"
        + (f" {alerts} alert" + ("s" if alerts != 1 else "") if alerts else "")
    )
    wide = cols >= 20
    for host in snap.hosts:
        if not host.up:
            out.append(f"{host.name[: cols - 5]} DOWN")
            continue
        name_w = max(4, cols - (16 if wide else 11))
        line = f"{host.name[:name_w]:<{name_w}} C{pct(host.cpu):>3} M{pct(host.mem):>3}"
        if wide and host.temp is not None:
            line += f" {host.temp:.0f}C"
        out.append(line)
    for host in snap.hosts:
        for disk in host.disks:
            width = max(3, cols - 13)
            used, total = size(disk.used), size(disk.total)
            out.append(f"{disk.mount[:width]:<{width}} {used:>4}/{total:<4}{pct(disk.pct):>3}")
    for host in snap.hosts:
        if host.rx_bps is not None:
            width = max(4, cols - 12)
            out.append(
                f"{host.name[:width]:<{width}} v{rate(host.rx_bps):>4} ^{rate(host.tx_bps):>4}"
            )
    for service in snap.services:
        state = "ok" if service.ok else "DOWN"
        out.append(f"{service.name[: max(3, cols - 5)]:<{max(3, cols - 5)}} {state:>4}")
    if snap.containers_known:
        running = sum(1 for c in snap.containers if c.state == "running")
        bad = [c for c in snap.containers if c.state not in ("running", "exited")]
        out.append(f"Containers {running}/{len(snap.containers)}")
        out.extend(f"{c.name[: cols - 4]} {c.state[:3]}" for c in bad)
    watts = snap.power_total()
    if watts is not None:
        out.append(f"Power {watts:.0f} W")
        out.extend(
            f"{p.name[: cols - 6]:<{cols - 6}} {p.watts:>4.0f}W"
            for p in snap.power
            if p.watts is not None and len(snap.power) > 1
        )
    for tile in snap.tiles:
        if tile.value is not None:
            out.append(
                f"{tile.name[: max(3, cols - 8)]:<{max(3, cols - 8)}} {tile.value:g}{tile.unit}"[
                    :cols
                ]
            )
    for alert in snap.alerts:
        out.append(f"! {alert.name}"[:cols])
    return out


def frames(snap: Snapshot, cols: int = 20, rows: int = 4) -> list[list[str]]:
    """The pages for a `cols` x `rows` text display."""
    cols = max(MIN_COLS, min(MAX_COLS, cols))
    rows = max(MIN_ROWS, min(MAX_ROWS, rows))
    lines = [_fit(line, cols) for line in _lines(snap, cols)]
    pages = []
    for start in range(0, len(lines), rows):
        page = lines[start : start + rows]
        page += [" " * cols] * (rows - len(page))
        pages.append(page)
    return pages
