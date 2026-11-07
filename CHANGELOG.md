# Changelog

## 1.0.0
- Kiosk page with five rotating screens, stale-data detection and burn-in protection.
- Sources: local (/proc, /sys), Prometheus, demo.
- Docker containers, TCP/HTTP checks, Shelly/Tasmota/JSON power, custom PromQL tiles.
- Plain-text frames for small displays, ESP32 + OLED sketch.
- `/metrics`, `/healthz`, optional token, strict CSP.
- Docker image and compose file (with optional read-only Docker socket proxy).
