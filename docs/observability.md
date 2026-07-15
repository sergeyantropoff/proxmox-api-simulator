# Observability

## Health

| Path | Meaning |
|---|---|
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Database reachable **and** migrations current; HTTP 503 when not |

Example:

```bash
curl -s http://localhost:8006/health/live
curl -s http://localhost:8006/health/ready
```

## Request correlation

Incoming requests accept or generate an ID via `REQUEST_ID_HEADER`
(default `X-Request-ID`). Structured logs include correlation fields and redact
known secret patterns.

## Metrics / tracing

There is **no** Prometheus `/metrics` scrape endpoint and **no** bundled
OpenTelemetry exporter in the current application. Architecture notes that
mention them describe target design, not shipping telemetry.

Do not confuse Proxmox API paths under `/cluster/metrics` with simulator
process telemetry — those handlers simulate PVE metrics-server configuration
state inside PostgreSQL.

## Compatibility evidence

Operational compatibility reports:

- `/admin/compatibility`
- `/admin/compatibility.md`
- `/admin/compatibility.html`

Also available through the Web UI compatibility panel.
