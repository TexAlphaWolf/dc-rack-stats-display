# Limitations

- The `local` source needs Linux (`/proc`, `/sys`). On Windows or macOS use the `prometheus` source.
- Temperatures depend on what the kernel exposes; VMs and some boards expose none (the field is simply hidden).
- The ESP32 sketch is compiled in CI, not tested on real hardware by the author.
- No HTTPS: put a reverse proxy in front if the display is not on a trusted network.
- No history or graphs: this is a status display. Long-term data belongs in Prometheus/Grafana.
- Container CPU/memory per container is only available through the Prometheus source (cAdvisor);
  the Docker source lists names and states.
- The demo data is made up; do not read anything into it.
