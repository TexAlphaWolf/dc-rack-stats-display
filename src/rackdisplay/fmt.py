"""Number formatting shared by the LCD frames and the metrics."""

from __future__ import annotations


def pct(value: float | None) -> str:
    return "--" if value is None else f"{round(value * 100):d}"


def rate(bps: float | None) -> str:
    """Bytes per second as a short string: 12K, 3.4M."""
    if bps is None:
        return "--"
    for unit, size in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if bps >= size:
            number = bps / size
            return f"{number:.0f}{unit}" if number >= 10 else f"{number:.1f}{unit}"
    return f"{bps:.0f}B"


def size(value: float) -> str:
    """Bytes as a short string: 468G, 7.2T."""
    for unit, step in (("T", 1024**4), ("G", 1024**3), ("M", 1024**2)):
        if value >= step:
            number = value / step
            return f"{number:.0f}{unit}" if number >= 10 else f"{number:.1f}{unit}"
    return f"{value / 1024:.0f}K"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d{hours:02d}h"
    return f"{hours}h{rest // 60:02d}m"


def ascii_only(text: str) -> str:
    """Small displays have no accents or symbols: drop what they cannot show."""
    return text.encode("ascii", "replace").decode("ascii")
