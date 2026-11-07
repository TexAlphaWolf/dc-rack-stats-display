# Limitations

- The `local` source needs Linux (`/proc`, `/sys`). On Windows or macOS use the `prometheus` source.
- Temperatures depend on what the kernel exposes; VMs and some boards expose none (the field is simply hidden).
- The ESP32 sketch is compiled in CI, not tested on real hardware by the author.
- No HTTPS: put a reverse proxy in front if the display is not on a trusted network.
- No history or graphs: this is a status display. Long-term data belongs in Prometheus/Grafana.
- Container CPU/memory per container is only available through the Prometheus source (cAdvisor);
  the Docker source lists names and states.
- The demo data is made up; do not read anything into it.
- On Windows, a URL with `localhost` can add seconds to every request (the name is tried over IPv6
  first). Use `127.0.0.1`: in one measurement a full snapshot took 10.5 s with `localhost` and 0.3 s
  with `127.0.0.1`. `rackdisplay check-config` warns about it.
