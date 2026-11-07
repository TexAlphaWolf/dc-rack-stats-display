# Configuration

Everything is in one TOML file; `config.example.toml` documents every key. Unknown keys and wrong
types are rejected when the file is loaded, so a typo fails at start-up instead of silently doing
nothing. Check a file without starting the server:

```
rackdisplay check-config -c config.toml
```

| Section | Purpose |
|---|---|
| `[server]` | `host`, `port`, `interval` (seconds between collections), `token` |
| `[display]` | `title`, `rotate_seconds`, `screens` |
| `[source]` | `type` = `local` / `prometheus` / `demo`, `name`, `prometheus_url`, `proc`, `sys` |
| `[thresholds]` | where OK becomes WARN and CRIT: cpu .80/.95, mem .85/.95, disk .85/.95, temp 70/85 |
| `[[disks]]` | mount points to show (local source); without any, only `/` |
| `[docker]` | `enabled`, `socket` or `url` |
| `[[checks]]` | TCP or HTTP reachability of things that are not hosts |
| `[[pdu]]` | power: Shelly, Tasmota or generic JSON (`path` into the document) |
| `[[tiles]]` | any PromQL number, with `warn_above/crit_above/warn_below/crit_below` |

Environment: `RACKDISPLAY_TOKEN` overrides `[server] token`.

## Sources
- **local** reads `/proc` and `/sys` of the machine. In Docker the host's are mounted read-only at
  `/host/proc`, `/host/sys`, `/host/rootfs` (see `deploy/config.docker.toml`). Inside a container the
  machine's name is not visible, so set `[source] name`.
- **prometheus** queries node_exporter (Linux), windows_exporter (Windows), cAdvisor (containers),
  Blackbox `probe_success` (services) and `/api/v1/alerts` (Watchdog is ignored). This is the same
  set of exporters that `dc-monitoring-stack` runs, so pointing it at that stack works unchanged.
- **demo** produces deterministic fake data from the clock: three hosts, 13 containers, 5 services,
  three power readings, an alert in every fourth two-minute slot.

## Containers and the Docker socket
Access to `/var/run/docker.sock` is access to the whole machine. rackdisplay therefore never needs
it directly: the `containers` compose profile starts
[docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) that only allows listing
containers, bound to `127.0.0.1:2375`, and rackdisplay reads from `http://127.0.0.1:2375`. Mounting the
raw socket (`socket = "/var/run/docker.sock"`) also works for a non-container install; do it only
if you accept that trade-off.

## Custom tiles
```toml
[[tiles]]
name = "Switch ports up"
query = 'count(ifOperStatus{job="snmp"} == 1)'
unit = "/ 16"
warn_below = 12
```
