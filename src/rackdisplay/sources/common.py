"""Pieces shared by the sources."""

from __future__ import annotations

import urllib.parse
from typing import Any

from ..config import Config
from ..http import FetchError, get_json
from ..model import Snapshot, Tile


def prom_query(base: str, expr: str, timeout: float) -> list[tuple[dict[str, str], float]]:
    """An instant PromQL query as (labels, value) pairs; NaN and missing values are dropped."""
    url = f"{base.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': expr})}"
    data: Any = get_json(url, timeout)
    if not isinstance(data, dict) or data.get("status") != "success":
        raise FetchError(f"query failed: {expr}")
    out = []
    for item in data.get("data", {}).get("result", []):
        try:
            value = float(item["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if value == value and abs(value) != float("inf"):  # not NaN, not infinite
            out.append((dict(item.get("metric", {})), value))
    return out


def add_tiles(snap: Snapshot, cfg: Config) -> None:
    """Custom numbers: one PromQL query each, the first series is the value."""
    for spec in cfg.tiles:
        tile = Tile(
            spec.name,
            None,
            spec.unit,
            spec.warn_above,
            spec.crit_above,
            spec.warn_below,
            spec.crit_below,
        )
        try:
            rows = prom_query(cfg.source.prometheus_url, spec.query, cfg.source.timeout)
            tile.value = rows[0][1] if rows else None
        except FetchError as error:
            snap.problems.append(f"tile {spec.name}: {error}")
        snap.tiles.append(tile)
