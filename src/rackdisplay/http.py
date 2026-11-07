"""Small HTTP helpers on the standard library: JSON over HTTP, and HTTP over a Unix socket."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any

MAX_BODY = 4 * 1024 * 1024  # a status page never needs more; stops a runaway server filling memory


def _ssl_context(verify: bool) -> ssl.SSLContext | None:
    """The default (verifying) context, or a non-verifying one when the user asked for it."""
    if verify:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class FetchError(Exception):
    """A request failed; the message is fit to show to the person running the display."""


def get_json(url: str, timeout: float = 4.0, verify: bool = True) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "rackdisplay"}
    )
    context = _ssl_context(verify)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as error:
        raise FetchError(f"{url}: HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        raise FetchError(f"{url}: {reason}") from error
    if len(body) > MAX_BODY:
        raise FetchError(f"{url}: answer too large")
    try:
        return json.loads(body)
    except ValueError as error:
        raise FetchError(f"{url}: not JSON") from error


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def get_json_unix(path: str, request_path: str, timeout: float = 4.0) -> Any:
    """GET `request_path` from a service listening on the Unix socket `path` (the Docker API)."""
    connection = _UnixConnection(path, timeout)
    try:
        connection.request("GET", request_path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(MAX_BODY + 1)
        status = response.status
    except (OSError, http.client.HTTPException) as error:
        raise FetchError(f"{path}: {error}") from error
    finally:
        connection.close()
    if status != 200 or len(body) > MAX_BODY:
        raise FetchError(f"{path}: HTTP {status}")
    try:
        return json.loads(body)
    except ValueError as error:
        raise FetchError(f"{path}: not JSON") from error
