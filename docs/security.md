# Security

- **Listens on 127.0.0.1 by default.** To reach it from a display, bind `0.0.0.0` and set a token.
- **Token**: compared in constant time; protects `/api/*` and `/metrics`. The page and `/healthz` stay open
  because the page contains no data by itself. Use it on a trusted network: it is plain HTTP.
- **The page never uses `innerHTML`**: names from containers and hosts are inserted as text, and a
  browser test feeds it `<img onerror=...>` to prove nothing runs.
- **Strict CSP**: `default-src 'none'; script-src 'self'; ...; frame-ancestors 'none'`, plus `nosniff`,
  `no-referrer`, `no-store`. No inline scripts, no external requests.
- **Docker**: use the read-only socket proxy, never the raw socket (see [configuration](configuration.md)).
- **Container**: non-root user, read-only filesystem, all capabilities dropped, `no-new-privileges`, 128 MB limit.
  Host `/proc`, `/sys` and `/` are mounted read-only.
- **Power readers** only issue GET requests to the devices you list.
- Responses from other services are capped at 4 MB.

Report vulnerabilities as described in [SECURITY.md](../SECURITY.md).
