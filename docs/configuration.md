# Configuration

Application settings are loaded from the environment (see `.env.example`).
Docker Compose injects many of these for the `simulator` service; values
declared under `environment:` in `docker-compose.yml` override `.env` for that
service.

## Core

| Variable | Default / example | Meaning |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `8006` | HTTP listen port |
| `DATABASE_URL` | `postgresql://proxmox:proxmox@postgres:5432/proxmox_simulator` | asyncpg DSN |
| `DB_POOL_MIN_SIZE` | `1` | Pool minimum |
| `DB_POOL_MAX_SIZE` | `10` | Pool maximum |
| `DB_CONNECT_TIMEOUT_SECONDS` | `10` | Connect timeout |
| `DB_COMMAND_TIMEOUT_SECONDS` | `30` | Command timeout |
| `LOG_LEVEL` | `INFO` | Logging level |
| `REQUEST_ID_HEADER` | `X-Request-ID` | Request correlation header |

## Contract and catalog

| Variable | Meaning |
|---|---|
| `CONTRACT_SNAPSHOT` | Path to the normalized snapshot loaded at **cold start** |
| `CONTRACT_FALLBACK` | `error` (default), `schema-default`, or `fixture` — behaviour for methods **without** a semantic handler |
| `COMPATIBILITY_EVIDENCE` | Optional evidence JSON used by compatibility reports |
| `CATALOG_ARTIFACT_URL_6` … `_9` | Official API Viewer URLs used when importing/caching catalog majors |

Runtime hot-swap (Web UI / `POST /ui/api/contract/apply`) replaces the in-memory
route table for majors **6–9** without rewriting `CONTRACT_SNAPSHOT`. A process
restart restores the cold-start snapshot. See [API versions](api-versions.md).

With **100%** handler coverage on majors 6–9, `CONTRACT_FALLBACK` is unused for
declared methods of the active contract. Keep `error` in production-like labs so
any accidental gap surfaces as HTTP 501.

## Security and tasks

| Variable | Meaning |
|---|---|
| `TICKET_SIGNING_KEY` | HMAC key for tickets and ticket-bound CSRF tokens (**change outside toy labs**) |
| `TASK_WORKER_CONCURRENCY` | Number of leased asyncio workers (1–32) |
| `TASK_LEASE_SECONDS` | PostgreSQL task lease duration |
| `SIMULATION_TIME_SCALE` | Accelerates simulated task durations |

## Seed and client test hooks

| Variable | Meaning |
|---|---|
| `SEED_PROFILE` | Profile name for the seed CLI (`small`, `medium`, …) |
| `SEED_LARGE_NODES` | Node count for `large` |
| `SEED_LARGE_RESOURCES` | Guest count for `large` (default 10 000) |
| `TEST_DATABASE_URL` | Integration-test DSN |
| `PROXMOXER_HOST` / `PROXMOXER_PORT` | Compatibility test client target (`tls-gateway` / `8443` in Compose) |

## Ports and TLS

| Endpoint | Use |
|---|---|
| `http://localhost:8006` | Direct HTTP (curl, browsers, most examples) |
| `https://localhost:8007` | TLS gateway for TLS-assuming clients (proxmoxer, etc.) |

The checked-in certificate under `docker/tls/` is disposable development
material. Never reuse it outside local labs. See [Security](security.md).

## Compose notes

- `migrate` runs once; `simulator` waits for a successful migrate.
- Development Compose bind-mounts the repository and enables Uvicorn reload.
- The default Compose `CONTRACT_SNAPSHOT` pins the bundled PVE **9.2.3**
  revision for cold start.

## Open and unused example keys

`.env.example` may still list keys such as `PVE_API_VERSION`,
`SIMULATION_SEED`, `SIMULATOR_ADMIN_ENABLED`, and `SIMULATOR_ADMIN_TOKEN` that
are **not** consumed by the current settings model. Prefer `CONTRACT_SNAPSHOT`
for the default major and the Web UI / apply API for runtime switches. Do not
assume an authenticated `/_simulator` admin API exists today.
