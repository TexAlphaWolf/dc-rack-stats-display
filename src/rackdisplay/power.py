"""Watts from a smart plug or PDU that speaks HTTP: Shelly, Tasmota, or any JSON endpoint."""

from __future__ import annotations

from typing import Any

from .config import PduSpec
from .http import FetchError, get_json
from .model import PowerItem


def dig(data: Any, path: str) -> Any:
    """Follow 'a.b.0.c' through nested dicts and lists."""
    for part in path.split("."):
        if isinstance(data, list):
            try:
                data = data[int(part)]
            except (ValueError, IndexError) as error:
                raise FetchError(f"no '{part}' in the answer") from error
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            raise FetchError(f"no '{part}' in the answer")
    return data


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FetchError(f"{what} is not a number")
    return float(value)


def read_power(spec: PduSpec, timeout: float = 4.0) -> PowerItem:
    """Current draw in watts. Raises FetchError when the device does not answer sensibly."""
    base = spec.url.rstrip("/")
    if spec.type == "tasmota":
        data = get_json(f"{base}/cm?cmnd=Status%208", timeout)
        return PowerItem(spec.name, _number(dig(data, "StatusSNS.ENERGY.Power"), "Power"))
    if spec.type == "shelly":
        try:  # second generation first, then the original API
            data = get_json(f"{base}/rpc/Switch.GetStatus?id=0", timeout)
            return PowerItem(spec.name, _number(dig(data, "apower"), "apower"))
        except FetchError:
            data = get_json(f"{base}/status", timeout)
            return PowerItem(spec.name, _number(dig(data, "meters.0.power"), "power"))
    data = get_json(spec.url, timeout)
    return PowerItem(spec.name, _number(dig(data, spec.path), spec.path))
