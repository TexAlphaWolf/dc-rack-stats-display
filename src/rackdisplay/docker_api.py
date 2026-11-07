"""Container states from the Docker Engine API (a socket, or a read-only socket proxy)."""

from __future__ import annotations

import urllib.parse
from typing import Any

from .config import DockerSpec
from .http import FetchError, get_json, get_json_unix
from .model import Container

_PATH = "/containers/json?all=true"


def _state(raw: dict[str, Any]) -> str:
    state = str(raw.get("State", "unknown"))
    status = str(raw.get("Status", ""))
    if state == "running" and "(unhealthy)" in status:
        return "unhealthy"
    return state


def list_containers(spec: DockerSpec, timeout: float = 4.0) -> list[Container]:
    """Every container, stopped ones included. Raises FetchError when Docker cannot be reached."""
    if spec.url:
        data = get_json(
            urllib.parse.urljoin(spec.url.rstrip("/") + "/", _PATH.lstrip("/")), timeout
        )
    else:
        data = get_json_unix(spec.socket, _PATH, timeout)
    if not isinstance(data, list):
        raise FetchError("docker: unexpected answer")
    found = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        names = raw.get("Names") or [str(raw.get("Id", "?"))[:12]]
        found.append(Container(name=str(names[0]).lstrip("/"), state=_state(raw)))
    return sorted(found, key=lambda c: c.name)
