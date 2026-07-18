**Language / Язык:** [English](operations.md) | [Русский](ru/operations.md)

# Operations

## Day-2 commands

```bash
make up                 # start stack
make down               # stop stack
make restart
make logs
make dev                # foreground reload-oriented workflow
make db-migrate         # idempotent migrations
make seed PROFILE=small # atomic reseed
make shell              # interactive tools container
```

## Migrations

Ordered SQL files apply transactionally and record SHA-256 checksums.
Re-running `make db-migrate` is safe. Altering an already-applied migration is
rejected. `/health/ready` stays unavailable until the latest packaged migration
is present. Task workers retry claims after migrations catch up.

## Reseed

```bash
make seed PROFILE=medium
```

Reseed replaces mutable simulation state. External automation state (Terraform
state files, Pulumi stacks, Ansible inventories that encode VMIDs) may then
drift — refresh or recreate those side channels.

## Worker recovery

Workers use PostgreSQL leases. After a crash or restart, expired leases are
reclaimed and incomplete work can resume safely. Tunables:
`TASK_WORKER_CONCURRENCY`, `TASK_LEASE_SECONDS`, `SIMULATION_TIME_SCALE`.

## Changing the default API major

1. Prefer setting `CONTRACT_SNAPSHOT` to the desired bundled/normalized snapshot
   for cold start (Compose / k8s / OpenShift).
2. Use Web UI apply or `POST /ui/api/contract/apply?major=N` for temporary
   process-local switches.

## Backing up lab state

PostgreSQL is the system of record. Use normal Postgres backup/restore
(pg_dump / volume snapshots) if you need to preserve a seeded laboratory.
Application containers are disposable when the database volume remains.

## Publishing to Docker Hub

`make release` builds the **runtime** image (production target — not the local
bind-mounted `dev` image) and pushes it to Docker Hub:

```bash
docker login   # once; account must own or can push to DOCKERHUB_USER
make release
```

Defaults:

| Variable | Default | Meaning |
|---|---|---|
| `DOCKERHUB_USER` | `inecs` | Docker Hub namespace/org |
| `IMAGE_NAME` | `proxmox-api-simulator` | Repository name |
| `VERSION` | from `pyproject.toml` | Image tag |
| `PUSH_LATEST` | `1` | Also tag/push `:latest` |

Examples:

```bash
make release
make release VERSION=0.2.0
make release DOCKERHUB_USER=myorg PUSH_LATEST=0
make release-build   # build/tag locally without pushing
```

Published tags:

- `inecs/proxmox-api-simulator:<version>`
- `inecs/proxmox-api-simulator:latest` (unless `PUSH_LATEST=0`)

After publishing, paste
[Docker Hub overview](docker-hub-overview.md) into the Hub repository
description if it drifted, and keep GitHub “About” wording aligned
(“stateful Proxmox VE API simulator” — not a thin mock).

CI on GitHub Actions runs `make ci` plus Compose/Helm validation on every push
and PR to `main` (see `.github/workflows/ci.yml`).

## Quick start with the published compose file

[`docker-compose.release.yml`](../docker-compose.release.yml) pulls the Hub
runtime image and starts PostgreSQL + migrate + simulator:

```bash
docker compose -f docker-compose.release.yml up -d
docker compose -f docker-compose.release.yml run --rm --entrypoint python \
  simulator -m app.simulation.seed_cli

curl -sS http://localhost:8006/health/ready
open http://localhost:8006/
```

Helpers from a git checkout:

```bash
make release-up
make release-seed PROFILE=small
make release-down
```

Useful overrides:

| Variable | Default | Meaning |
|---|---|---|
| `DOCKER_IMAGE` | `inecs/proxmox-api-simulator` | Image repository |
| `IMAGE_TAG` | `latest` | Tag to pull |
| `SIMULATOR_PORT` | `8006` | Host HTTP port (simulator) |
| `TICKET_SIGNING_KEY` | lab default | Change outside toy labs |
| `POSTGRES_PASSWORD` | `proxmox` | DB password |

Both development and release Compose publish **HTTP `:8006`** on the host
(same port as real PVE, which uses HTTPS). Optional HTTPS for proxmoxer-style
clients: `docker compose --profile tls` on host `:8443`. See
[Ports and TLS](configuration.md#ports-and-tls).

For Kubernetes with public TLS (cert-manager / Let's Encrypt), use the Helm
chart — see [Kubernetes / Helm](kubernetes.md).

## Upgrades

1. Pull / rebuild images (`make install` / `make docker-build` as appropriate).
2. Run migrations.
3. Confirm `/health/ready`.
4. Re-check `/admin/compatibility` and `/api2/json/version`.
5. Re-run `make test-compatibility` if you validate external clients in CI
   (seeds the **medium** profile — `pve1`/`pve2`/`pve3` — for migration smoke).

## Resetting a lab

```bash
make seed PROFILE=small
# or via UI: unload demo → minimal, then seed again
```

For a hard database reset use `make db-reset` (destructive — see Makefile help).
