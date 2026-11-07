from __future__ import annotations

import pytest

from rackdisplay.fmt import ascii_only, duration, pct, rate, size


def test_pct() -> None:
    assert (pct(None), pct(0.456), pct(1.0)) == ("--", "46", "100")


@pytest.mark.parametrize(
    ("value", "text"),
    [(None, "--"), (12, "12B"), (1500, "1.5K"), (25_000, "25K"), (3.4e6, "3.4M"), (2e9, "2.0G")],
)
def test_rate(value: float | None, text: str) -> None:
    assert rate(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (512, "0K"),
        (2048, "2K"),
        (5 * 1024**2, "5.0M"),
        (468 * 1024**3, "468G"),
        (7.2 * 1024**4, "7.2T"),
    ],
)
def test_size(value: float, text: str) -> None:
    assert size(value) == text


def test_duration_and_ascii() -> None:
    assert duration(None) == "--"
    assert duration(3 * 86400 + 5 * 3600) == "3d05h"
    assert duration(2 * 3600 + 7 * 60) == "2h07m"
    assert ascii_only("Café ☃") == "Caf? ?"
