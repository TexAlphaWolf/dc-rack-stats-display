# HTTP API

All endpoints are GET (HEAD works). With a token set, everything except `/`, its assets and `/healthz`
needs `Authorization: Bearer <token>` or `?token=<token>`.

| Path | Returns |
|---|---|
| `/` | the kiosk page |
| `/healthz` | `200 ok`, or `503` when the snapshot is older than max(15 s, 4 x interval) |
| `/api/stats` | the full snapshot as JSON (hosts, containers, services, power, tiles, alerts, problems) |
| `/api/config` | what the page needs: title, rotation, screens |
| `/api/lcd?cols=20&rows=4` | pages as JSON (cols 8-40, rows 1-16) |
| `/api/lcd.txt?cols=20&rows=4` | the same, plain text: lines separated by `\n`, pages by `\f` |
| `/metrics` | Prometheus text format, all names start with `rackdisplay_` |

`problems` lists sources that failed (for example "docker: connection refused") so a broken
reader is visible instead of silently showing zeros.
