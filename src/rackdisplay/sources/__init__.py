"""Where the numbers come from: this machine, a Prometheus server, or made-up demo data."""

from __future__ import annotations

from typing import Protocol

from ..config import Config
from ..model import Snapshot


class Source(Protocol):
    def collect(self) -> Snapshot: ...


def make_source(cfg: Config) -> Source:
    if cfg.source.type == "demo":
        from .demo import DemoSource

        return DemoSource(cfg)
    if cfg.source.type == "prometheus":
        from .prom import PrometheusSource

        return PrometheusSource(cfg)
    from .local import LocalSource

    return LocalSource(cfg)
