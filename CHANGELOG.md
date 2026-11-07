# Changelog

## 1.0.1
- Prometheus source: the queries run in parallel (a snapshot took a minute with a slow `localhost`
  lookup on Windows, now a few seconds) and the data's age counts from when it was complete.
- Prometheus source: a filesystem mounted at several places is listed once; the Windows boot time is
  found with any windows_exporter version.
- Kiosk page: long disk lists are cut to fit the screen with a "+ N more" line.
- Server: connections dropped by the browser no longer print tracebacks.
- `check-config` warns about `localhost` in URLs on Windows.
- Python 3.14: HTTP error responses are closed (ResourceWarning).
- CI: the firmware job runs on Ubuntu 24.04.

## 1.0.0
- Kiosk page with five rotating screens, stale-data detection and burn-in protection.
- Sources: local (/proc, /sys), Prometheus, demo.
- Docker containers, TCP/HTTP checks, Shelly/Tasmota/JSON power, custom PromQL tiles.
- Plain-text frames for small displays, ESP32 + OLED sketch.
- `/metrics`, `/healthz`, optional token, strict CSP.
- Docker image and compose file (with optional read-only Docker socket proxy).
