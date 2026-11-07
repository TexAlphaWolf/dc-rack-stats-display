from __future__ import annotations

from pathlib import Path

import pytest

from rackdisplay import config as cfgmod
from rackdisplay.config import ConfigError, load, parse
from rackdisplay.model import (
    CRIT,
    OK,
    UNKNOWN,
    WARN,
    Disk,
    Host,
    Snapshot,
    Thresholds,
    Tile,
    finalize,
    level,
    tile_status,
    worst,
)


def test_defaults_are_valid() -> None:
    cfgmod.validate(cfgmod.Config())


def test_parse_full_example() -> None:
    cfg = parse(
        {
            "server": {"host": "0.0.0.0", "port": 9000, "interval": 2, "token": "t"},
            "display": {"title": "Home", "rotate_seconds": 10, "screens": ["overview", "power"]},
            "source": {"type": "prometheus", "prometheus_url": "http://p:9090"},
            "docker": {"enabled": True, "url": "http://proxy:2375"},
            "disks": [{"mount": "/", "name": "root"}],
            "checks": [{"name": "r", "type": "tcp", "target": "10.0.0.1:443"}],
            "pdu": [{"name": "p", "type": "shelly", "url": "http://10.0.0.9"}],
            "tiles": [{"name": "n", "query": "up", "warn_below": 1}],
            "thresholds": {"cpu_warn": 0.5},
        }
    )
    assert cfg.server.port == 9000
    assert cfg.thresholds.cpu_warn == 0.5
    assert cfg.tiles[0].warn_below == 1


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"nonsense": {}}, "unknown section"),
        ({"server": {"prot": 1}}, "unknown key 'prot'"),
        ({"server": {"port": "80"}}, "wrong type"),
        ({"server": "x"}, "must be a table"),
        ({"server": {"port": 0}}, "port"),
        ({"server": {"interval": 0.2}}, "interval"),
        ({"display": {"rotate_seconds": 1}}, "rotate_seconds"),
        ({"display": {"screens": ["nope"]}}, "screens"),
        ({"display": {"screens": []}}, "screens"),
        ({"source": {"type": "magic"}}, "type must be"),
        ({"source": {"type": "prometheus"}}, "prometheus_url is required"),
        ({"source": {"prometheus_url": "ftp://x"}}, "http://"),
        ({"checks": [{"name": "a", "type": "ping", "target": "x"}]}, "tcp or http"),
        ({"checks": [{"name": "a", "type": "tcp", "target": "nohostport"}]}, "host:port"),
        ({"checks": [{"name": "a", "type": "http", "target": "x"}]}, "http://"),
        ({"checks": {"name": "a"}}, "array of tables"),
        ({"checks": [{"name": "a"}]}, "missing required key"),
        ({"pdu": [{"name": "a", "type": "x", "url": "http://x"}]}, "type must be one of"),
        ({"pdu": [{"name": "a", "type": "shelly", "url": "x"}]}, "url must start"),
        ({"pdu": [{"name": "a", "type": "http-json", "url": "http://x"}]}, "needs a path"),
        ({"tiles": [{"name": "a", "query": "up"}]}, "prometheus_url"),
        ({"docker": {"url": "tcp://x"}}, "http://"),
    ],
)
def test_invalid_configs_say_what_is_wrong(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse(data)


def test_load_file_errors_and_token_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load(tmp_path / "missing.toml")
    broken = tmp_path / "broken.toml"
    broken.write_text("[server\nport=")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load(broken)
    good = tmp_path / "ok.toml"
    good.write_text("[display]\ntitle = 'X'\n")
    monkeypatch.setenv("RACKDISPLAY_TOKEN", "from-env")
    assert load(good).server.token == "from-env"
    assert load(None).server.token == "from-env"
    good.write_text("[server]\ntoken = 'from-file'\n")
    assert load(good).server.token == "from-file"


def test_example_config_in_the_repo_is_valid() -> None:
    root = Path(__file__).resolve().parent.parent
    cfg = load(root / "config.example.toml")
    assert cfg.display.screens


def test_level_and_worst() -> None:
    assert level(None, 1, 2) == UNKNOWN
    assert [level(v, 0.8, 0.95) for v in (0.1, 0.8, 0.95)] == [OK, WARN, CRIT]
    assert worst([OK, WARN, CRIT]) == CRIT
    assert worst([UNKNOWN, OK]) == OK
    assert worst([]) == UNKNOWN


def test_tile_status() -> None:
    assert tile_status(Tile("a", None)) == UNKNOWN
    assert tile_status(Tile("a", 5, warn_below=10)) == WARN
    assert tile_status(Tile("a", 5, crit_below=10)) == CRIT
    assert tile_status(Tile("a", 50, warn_above=40, crit_above=60)) == WARN
    assert tile_status(Tile("a", 70, warn_above=40, crit_above=60)) == CRIT
    assert tile_status(Tile("a", 20, warn_above=40, warn_below=10)) == OK


def test_finalize_statuses() -> None:
    snap = Snapshot(ts=0, source="t")
    snap.hosts = [
        Host("fine", cpu=0.1, mem_used=1, mem_total=10, disks=[Disk("/", 50, 100)]),
        Host("full", cpu=0.1, mem=0.1, disks=[Disk("/", 96, 100)]),
        Host("hot", cpu=0.1, mem=0.1, temp=72),
        Host("off", up=False),
    ]
    finalize(snap, Thresholds())
    status = {h.name: h.status for h in snap.hosts}
    assert status == {"fine": OK, "full": CRIT, "hot": WARN, "off": CRIT}
    assert snap.hosts[0].mem == pytest.approx(0.1)
    assert snap.hosts[1].disks[0].pct == pytest.approx(0.96)
    assert snap.status == CRIT


def test_finalize_unknown_when_nothing_is_known() -> None:
    assert finalize(Snapshot(ts=0, source="t"), Thresholds()).status == UNKNOWN
    empty_disk = Snapshot(ts=0, source="t", hosts=[Host("h", disks=[Disk("/", 0, 0)])])
    finalize(empty_disk, Thresholds())
    assert empty_disk.hosts[0].disks[0].pct == 0.0


def test_alerts_and_containers_drive_the_overall_status() -> None:
    from rackdisplay.model import Alert, Container

    snap = Snapshot(ts=0, source="t", alerts=[Alert("A", "warning")])
    assert finalize(snap, Thresholds()).status == WARN
    snap.alerts.append(Alert("B", "critical"))
    assert finalize(snap, Thresholds()).status == CRIT
    snap = Snapshot(
        ts=0, source="t", containers=[Container("a", "exited"), Container("b", "running")]
    )
    assert finalize(snap, Thresholds()).status == OK  # a stopped container is a warning label only
    snap.containers.append(Container("c", "restarting"))
    assert finalize(snap, Thresholds()).status == CRIT
    assert snap.to_dict()["power_total"] is None
