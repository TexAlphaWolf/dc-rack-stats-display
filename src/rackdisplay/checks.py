"""Reachability checks for the things that are not hosts: a router, a NAS, a web page."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .config import CheckSpec
from .http import _ssl_context
from .model import Service


def _tcp(spec: CheckSpec, timeout: float) -> Service:
    host, _, port = spec.target.rpartition(":")
    started = time.perf_counter()
    try:
        with socket.create_connection((host.strip("[]"), int(port)), timeout=timeout):
            pass
    except (OSError, ValueError) as error:
        return Service(spec.name, spec.target, False, None, str(error) or type(error).__name__)
    return Service(spec.name, spec.target, True, (time.perf_counter() - started) * 1000)


def _http(spec: CheckSpec, timeout: float) -> Service:
    request = urllib.request.Request(spec.target, headers={"User-Agent": "rackdisplay"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_context(spec.verify_tls)
        ) as response:
            code = response.status
    except urllib.error.HTTPError as error:
        code = error.code
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        return Service(spec.name, spec.target, False, None, str(reason))
    latency = (time.perf_counter() - started) * 1000
    return Service(spec.name, spec.target, code < 400, latency, f"HTTP {code}")


def run_checks(specs: list[CheckSpec], timeout: float = 3.0) -> list[Service]:
    """Run all checks in parallel; the result keeps the configured order."""
    if not specs:
        return []

    def one(spec: CheckSpec) -> Service:
        return _tcp(spec, timeout) if spec.type == "tcp" else _http(spec, timeout)

    with ThreadPoolExecutor(max_workers=min(8, len(specs))) as pool:
        return list(pool.map(one, specs))
