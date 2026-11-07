from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from rackdisplay.checks import run_checks
from rackdisplay.config import (
    CheckSpec,
    Config,
    DiskSpec,
    DockerSpec,
    PduSpec,
    TileSpec,
    parse,
)
from rackdisplay.docker_api import list_containers
from rackdisplay.http import FetchError, get_json, get_json_unix
from rackdisplay.model import CRIT, OK
from rackdisplay.power import dig, read_power
from rackdisplay.sources import make_source
from rackdisplay.sources import prom as promsrc
from rackdisplay.sources.demo import DemoSource
from rackdisplay.sources.local import LocalSource, cpu_times, meminfo, net_bytes

# ----------------------------------------------------------------------------- local source

STAT_1 = "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3\n"
STAT_2 = "cpu  200 0 200 1000 0 0 0 0 0 0\n"  # +200 busy of +400 total: 50 %
MEMINFO = "MemTotal: 8000000 kB\nMemFree: 1000000 kB\nMemAvailable: 6000000 kB\n"
NETDEV = (
    "Inter-|   Receive |  Transmit\n face |bytes packets errs drop fifo frame compressed multicast"
    "|bytes packets errs drop fifo colls carrier compressed\n"
    "    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n"
    "  eth0: 1000 1 0 0 0 0 0 0 500 1 0 0 0 0 0 0\n"
    "docker0: 777 1 0 0 0 0 0 0 777 1 0 0 0 0 0 0\n"
)


def fake_machine(root: Path) -> tuple[Path, Path]:
    proc, sysfs = root / "proc", root / "sys"
    (proc / "net").mkdir(parents=True)
    (proc / "sys" / "kernel").mkdir(parents=True)
    (proc / "stat").write_text(STAT_1)
    (proc / "meminfo").write_text(MEMINFO)
    (proc / "net" / "dev").write_text(NETDEV)
    (proc / "loadavg").write_text("0.52 0.40 0.30 1/200 999\n")
    (proc / "uptime").write_text("90061.50 1000.00\n")
    (proc / "sys" / "kernel" / "hostname").write_text("rack01\n")
    (sysfs / "class" / "hwmon" / "hwmon0").mkdir(parents=True)
    (sysfs / "class" / "hwmon" / "hwmon0" / "temp1_input").write_text("48500\n")
    (sysfs / "class" / "thermal" / "thermal_zone0").mkdir(parents=True)
    (sysfs / "class" / "thermal" / "thermal_zone0" / "temp").write_text("61000\n")
    return proc, sysfs


def local_cfg(proc: Path, sysfs: Path, mount: Path) -> Config:
    cfg = Config()
    cfg.source.proc, cfg.source.sys = str(proc), str(sysfs)
    cfg.disks = [DiskSpec(str(mount), "data"), DiskSpec("/definitely/not/mounted", "gone")]
    return cfg


def test_parsers_of_proc_files() -> None:
    assert cpu_times(STAT_1) == (200.0, 1000.0)
    used, total = meminfo(MEMINFO)
    assert (used, total) == (2000000 * 1024, 8000000 * 1024)
    assert net_bytes(NETDEV) == (1000.0, 500.0)  # loopback and docker0 are left out
    assert meminfo("MemTotal: 100 kB\nMemFree: 40 kB\n") == (60 * 1024, 100 * 1024)  # old kernels


def test_local_source_reads_a_fake_machine(tmp_path: Path) -> None:
    proc, sysfs = fake_machine(tmp_path)
    source = LocalSource(local_cfg(proc, sysfs, tmp_path))
    (proc / "stat").write_text(STAT_2)
    (proc / "net" / "dev").write_text(NETDEV.replace("1000 1", "3000 1").replace("500 1", "1500 1"))
    snap = source.collect()
    assert snap.source == "local"
    host = snap.hosts[0]
    assert host.name == "rack01"
    assert host.cpu == pytest.approx(0.5)
    assert host.mem == pytest.approx(0.25)
    assert host.temp == pytest.approx(61.0)  # the hottest sensor
    assert host.load1 == pytest.approx(0.52)
    assert host.uptime == pytest.approx(90061.5)
    assert host.rx_bps is not None
    assert host.rx_bps > 0
    assert [d.mount for d in host.disks] == ["data"]  # the missing mount is skipped
    assert host.status == OK
    assert snap.problems == []


def test_local_source_name_can_be_set(tmp_path: Path) -> None:
    proc, sysfs = fake_machine(tmp_path)
    cfg = local_cfg(proc, sysfs, tmp_path)
    cfg.source.name = "my-rack"
    assert LocalSource(cfg).collect().hosts[0].name == "my-rack"
    (proc / "sys" / "kernel" / "hostname").unlink()
    cfg.source.name = ""
    assert LocalSource(cfg).collect().hosts[0].name  # falls back to the real hostname


def test_local_source_needs_linux(tmp_path: Path) -> None:
    cfg = Config()
    cfg.source.proc = str(tmp_path)
    with pytest.raises(FileNotFoundError, match="needs Linux"):
        LocalSource(cfg)


def test_local_source_survives_broken_files(tmp_path: Path) -> None:
    proc, sysfs = fake_machine(tmp_path)
    source = LocalSource(local_cfg(proc, sysfs, tmp_path))
    (proc / "meminfo").write_text("garbage")
    snap = source.collect()
    assert snap.hosts == []
    assert snap.problems
    assert snap.status == "unknown"


def test_local_source_ignores_absurd_temperatures_and_counter_resets(tmp_path: Path) -> None:
    proc, sysfs = fake_machine(tmp_path)
    (sysfs / "class" / "hwmon" / "hwmon0" / "temp1_input").write_text("999000\n")
    (sysfs / "class" / "thermal" / "thermal_zone0" / "temp").write_text("not a number\n")
    source = LocalSource(local_cfg(proc, sysfs, tmp_path))
    first = source.collect().hosts[0]
    assert first.temp is None
    (proc / "net" / "dev").write_text(NETDEV.replace("1000 1", "10 1"))  # counters went backwards
    assert source.collect().hosts[0].rx_bps is None


def test_local_source_with_everything_configured(
    tmp_path: Path,
    fake_http,
    unix_docker,  # type: ignore[no-untyped-def]
) -> None:
    proc, sysfs = fake_machine(tmp_path)
    plug = fake_http({"/rpc/Switch.GetStatus": {"apower": 123.4}})
    cfg = local_cfg(proc, sysfs, tmp_path)
    cfg.docker = DockerSpec(
        enabled=True, socket=unix_docker([{"Names": ["/web"], "State": "running", "Status": "Up"}])
    )
    cfg.pdu = [
        PduSpec("plug", "shelly", plug.url),
        PduSpec("dead", "tasmota", "http://127.0.0.1:1"),
    ]
    cfg.checks = [CheckSpec("web", "http", plug.url + "/rpc/Switch.GetStatus")]
    snap = make_source(cfg).collect()
    assert [c.name for c in snap.containers] == ["web"]
    assert snap.containers_known
    assert snap.power_total() == pytest.approx(123.4)
    assert any("power dead" in p for p in snap.problems)
    assert snap.services[0].ok


def test_local_source_reports_an_unreachable_docker(tmp_path: Path) -> None:
    proc, sysfs = fake_machine(tmp_path)
    cfg = local_cfg(proc, sysfs, tmp_path)
    cfg.docker = DockerSpec(enabled=True, socket=str(tmp_path / "nothing.sock"))
    snap = make_source(cfg).collect()
    assert any(p.startswith("docker:") for p in snap.problems)
    assert not snap.containers_known


# ----------------------------------------------------------------------------- http and docker


def test_get_json_errors(fake_http) -> None:  # type: ignore[no-untyped-def]
    server = fake_http({"/ok": {"a": 1}, "/bad": b"not json", "/err": (500, {})})
    assert get_json(server.url + "/ok") == {"a": 1}
    with pytest.raises(FetchError, match="not JSON"):
        get_json(server.url + "/bad")
    with pytest.raises(FetchError, match="HTTP 500"):
        get_json(server.url + "/err")
    with pytest.raises(FetchError):
        get_json("http://127.0.0.1:1/", timeout=0.5)


def test_docker_states_and_errors(unix_docker, fake_http) -> None:  # type: ignore[no-untyped-def]
    body = [
        {"Names": ["/b"], "State": "running", "Status": "Up 2 hours (unhealthy)"},
        {"Names": ["/a"], "State": "restarting", "Status": "Restarting"},
        {"Id": "0123456789abcdef", "State": "exited", "Status": "Exited"},
        "junk",
    ]
    found = list_containers(DockerSpec(enabled=True, socket=unix_docker(body)))
    assert [(c.name, c.state) for c in found] == [
        ("0123456789ab", "exited"),
        ("a", "restarting"),
        ("b", "unhealthy"),
    ]
    proxy = fake_http({"/containers/json": body})
    assert len(list_containers(DockerSpec(enabled=True, url=proxy.url))) == 3
    with pytest.raises(FetchError):
        list_containers(DockerSpec(enabled=True, socket=unix_docker({"x": 1})))
    with pytest.raises(FetchError, match="HTTP 500"):
        get_json_unix(unix_docker([], 500), "/containers/json")
    with pytest.raises(FetchError):
        get_json_unix("/nonexistent.sock", "/")


# ----------------------------------------------------------------------------- checks and power


def test_checks(fake_http) -> None:  # type: ignore[no-untyped-def]
    web = fake_http({"/fine": {}, "/gone": (404, {})})
    host, port = web.url.removeprefix("http://").split(":")
    results = run_checks(
        [
            CheckSpec("tcp up", "tcp", f"{host}:{port}"),
            CheckSpec("tcp down", "tcp", "127.0.0.1:1"),
            CheckSpec("http up", "http", web.url + "/fine"),
            CheckSpec("http 404", "http", web.url + "/gone"),
            CheckSpec("http down", "http", "http://127.0.0.1:1/"),
            CheckSpec("bad port", "tcp", "127.0.0.1:notaport"),
        ],
        timeout=1.0,
    )
    assert [r.name for r in results][:2] == ["tcp up", "tcp down"]
    assert [r.ok for r in results] == [True, False, True, False, False, False]
    assert results[0].latency_ms is not None
    assert results[3].detail == "HTTP 404"
    assert run_checks([]) == []


def test_https_check_with_and_without_verification() -> None:
    # nothing listens, but building the context for both modes must work and fail politely
    for verify in (True, False):
        result = run_checks([CheckSpec("x", "http", "https://127.0.0.1:1/", verify)], timeout=0.5)[
            0
        ]
        assert not result.ok


def test_power_devices(fake_http) -> None:  # type: ignore[no-untyped-def]
    server = fake_http(
        {
            "/cm?cmnd=Status%208": {"StatusSNS": {"ENERGY": {"Power": 55}}},
            "/rpc/Switch.GetStatus": {"apower": 12.5},
            "/gen1/status": {"meters": [{"power": 7.25}]},
            "/custom": {"a": [{"w": 3}]},
            "/text": {"a": "abc"},
        }
    )
    assert read_power(PduSpec("t", "tasmota", server.url)).watts == 55
    assert read_power(PduSpec("s2", "shelly", server.url)).watts == 12.5
    assert read_power(PduSpec("s1", "shelly", server.url + "/gen1")).watts == 7.25
    assert read_power(PduSpec("j", "http-json", server.url + "/custom", "a.0.w")).watts == 3
    with pytest.raises(FetchError, match="not a number"):
        read_power(PduSpec("j", "http-json", server.url + "/text", "a"))
    with pytest.raises(FetchError, match="no 'zzz'"):
        read_power(PduSpec("j", "http-json", server.url + "/custom", "zzz"))
    with pytest.raises(FetchError, match="no '5'"):
        dig({"a": []}, "a.5")
    with pytest.raises(FetchError, match="no 'x'"):
        dig({"a": []}, "a.x")


# ----------------------------------------------------------------------------- prometheus


def vector(*rows: tuple[dict[str, str], float | str]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": m, "value": [0, str(v)]} for m, v in rows],
        },
    }


LIN = {"instance": "srv:9100", "host": "srv"}
WIN = {"instance": "pc:9182", "host": "pc"}


def fake_prometheus(fake_http, extra: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
    answers: dict[str, Any] = {
        'up{job=~"node|windows"}': vector(
            ({**LIN, "job": "node"}, 1), ({**WIN, "job": "windows"}, 1)
        ),
        promsrc._LINUX["cpu"]: vector((LIN, 0.4)),
        promsrc._LINUX["mem_total"]: vector((LIN, 1000)),
        promsrc._LINUX["mem_avail"]: vector((LIN, 250)),
        promsrc._LINUX["load1"]: vector((LIN, 0.7)),
        promsrc._LINUX["uptime"]: vector((LIN, 86400)),
        promsrc._LINUX["temp"]: vector((LIN, 66)),
        promsrc._LINUX["rx"]: vector((LIN, 1e6)),
        promsrc._LINUX["tx"]: vector((LIN, 2e5)),
        promsrc._LINUX_DISK[0]: vector(
            ({**LIN, "mountpoint": "/"}, 1000), ({**LIN, "mountpoint": "/x"}, 0)
        ),
        promsrc._LINUX_DISK[1]: vector(
            ({**LIN, "mountpoint": "/"}, 300), ({**LIN, "mountpoint": "/x"}, 0)
        ),
        promsrc._WINDOWS["cpu"]: vector((WIN, 1.7)),  # over 1 is clamped
        promsrc._WINDOWS["mem_total"]: vector((WIN, 2000)),
        promsrc._WINDOWS["mem_avail"]: vector((WIN, 1000)),
        promsrc._WINDOWS_DISK[0]: vector(({**WIN, "volume": "C:"}, 500)),
        promsrc._WINDOWS_DISK[1]: vector(({**WIN, "volume": "C:"}, 25)),
        'sum by (name) (container_memory_working_set_bytes{name!=""})': vector(
            ({"name": "web"}, 5e7), ({"name": "db"}, 9e7)
        ),
        'sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[2m]))': vector(
            ({"name": "web"}, 0.1)
        ),
        'probe_success{job=~"probe-.*"}': vector(
            ({"instance": "http://grafana:3000/api/health"}, 1), ({"instance": "1.1.1.1:443"}, 0)
        ),
        'probe_duration_seconds{job=~"probe-.*"}': vector(
            ({"instance": "http://grafana:3000/api/health"}, 0.025)
        ),
        "tile-query": vector(({}, 13), ({}, "NaN")),
    }
    answers.update(extra or {})

    def query(path: str) -> Any:
        expr = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["query"][0]
        return answers.get(expr, vector())

    alerts = {
        "data": {
            "alerts": [
                {
                    "state": "firing",
                    "labels": {"alertname": "HostDown", "severity": "critical"},
                    "annotations": {"summary": "x"},
                },
                {"state": "firing", "labels": {"alertname": "Watchdog"}},
                {"state": "pending", "labels": {"alertname": "Soon"}},
            ]
        }
    }
    return fake_http({"/api/v1/query": query, "/api/v1/alerts": alerts})


def prom_cfg(url: str) -> Config:
    cfg = Config()
    cfg.source.type, cfg.source.prometheus_url = "prometheus", url
    cfg.tiles = [TileSpec("ports", "tile-query", "/16", warn_below=12)]
    return cfg


def test_prometheus_source(fake_http) -> None:  # type: ignore[no-untyped-def]
    server = fake_prometheus(fake_http)
    snap = make_source(prom_cfg(server.url)).collect()
    assert snap.problems == []
    hosts = {h.name: h for h in snap.hosts}
    srv, pc = hosts["srv"], hosts["pc"]
    assert (srv.kind, pc.kind) == ("linux", "windows")
    assert srv.cpu == pytest.approx(0.4)
    assert srv.mem == pytest.approx(0.75)
    assert srv.temp == 66
    assert srv.rx_bps == 1e6
    assert [(d.mount, d.pct) for d in srv.disks] == [("/", pytest.approx(0.7))]  # empty fs skipped
    assert pc.cpu == 1.0
    assert pc.mem == pytest.approx(0.5)
    assert pc.disks[0].pct == pytest.approx(0.95)
    assert pc.status == CRIT
    assert [c.name for c in snap.containers] == ["db", "web"]
    assert snap.containers_known
    assert {s.name: s.ok for s in snap.services} == {
        "grafana:3000/api/health": True,
        "1.1.1.1:443": False,
    }
    assert [a.name for a in snap.alerts] == ["HostDown"]  # no Watchdog, nothing pending
    assert snap.tiles[0].value == 13
    assert snap.tiles[0].status == "ok"


def test_prometheus_down_is_reported_not_raised(tmp_path: Path) -> None:
    snap = make_source(prom_cfg("http://127.0.0.1:1")).collect()
    assert snap.hosts == []
    assert any("prometheus hosts" in p for p in snap.problems)
    assert any("tile ports" in p for p in snap.problems)
    assert any("alerts" in p for p in snap.problems)


def test_prometheus_error_answers(fake_http) -> None:  # type: ignore[no-untyped-def]
    server = fake_http({"/api/v1/query": {"status": "error"}, "/api/v1/alerts": {"unexpected": 1}})
    snap = make_source(prom_cfg(server.url)).collect()
    assert snap.hosts == []
    assert snap.problems


def test_host_without_a_host_label_uses_the_instance(fake_http) -> None:  # type: ignore[no-untyped-def]
    server = fake_prometheus(
        fake_http,
        {'up{job=~"node|windows"}': vector(({"instance": "10.0.0.7:9100", "job": "node"}, 0))},
    )
    snap = make_source(prom_cfg(server.url)).collect()
    assert snap.hosts[0].name == "10.0.0.7"
    assert snap.hosts[0].up is False
    assert snap.hosts[0].status == CRIT


# ----------------------------------------------------------------------------- demo


def test_demo_is_repeatable_and_complete(demo_cfg: Config) -> None:
    a = DemoSource(demo_cfg, clock=1_794_000_000.0).collect()
    b = DemoSource(demo_cfg, clock=1_794_000_000.0).collect()
    assert a.to_dict() == b.to_dict()
    assert len(a.hosts) == 3
    assert a.containers_known
    assert a.services
    assert a.power_total() is not None
    assert a.tiles
    later = DemoSource(demo_cfg, clock=1_794_000_000.0 + 333).collect()
    assert later.hosts[0].cpu != a.hosts[0].cpu
    # over a few minutes an alert shows up at some point
    alerts = [
        DemoSource(demo_cfg, clock=1_794_000_000.0 + 120 * i).collect().alerts for i in range(8)
    ]
    assert any(alerts)
    assert not all(alerts)


def test_demo_with_the_real_clock(demo_cfg: Config) -> None:
    snap = DemoSource(demo_cfg).collect()
    assert abs(snap.ts - time.time()) < 5
    assert json.dumps(snap.to_dict())


def test_make_source_picks_by_type() -> None:
    assert type(make_source(parse({"source": {"type": "demo"}}))).__name__ == "DemoSource"
    assert (
        type(
            make_source(parse({"source": {"type": "prometheus", "prometheus_url": "http://x"}}))
        ).__name__
        == "PrometheusSource"
    )
