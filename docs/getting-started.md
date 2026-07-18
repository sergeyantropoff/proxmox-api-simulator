**Language / Язык:** [English](getting-started.md) | [Русский](ru/getting-started.md)

# Getting started

Bring up a local laboratory cluster, authenticate, and exercise a first
read/mutation cycle against the simulator.

## Prerequisites

- Docker and Docker Compose
- `make` (optional but used by the documented commands)

Python, linters, and tests run **inside** containers. You do not need a local
Python toolchain for day-to-day use.

## Choose a path

| Path | When to use |
|---|---|
| [Published image](#1a-published-image-docker-hub) | Fastest lab using `inecs/proxmox-api-simulator` |
| [Helm / Kubernetes](kubernetes.md) | Cluster install with Ingress + Let's Encrypt |
| [Development checkout](#1b-development-checkout) | Contribute / bind-mount source / HTTP API on `:8006` |

## 1a. Published image (Docker Hub)

Uses [`docker-compose.release.yml`](../docker-compose.release.yml) — PostgreSQL +
runtime simulator from Hub. No source build required.

> Laboratory / CI only — rotate `TICKET_SIGNING_KEY` and the DB password before
> any shared or networked demo. See [SECURITY.md](../SECURITY.md).

```bash
# from this repository (compose file + docker/tls/)
docker compose -f docker-compose.release.yml pull
docker compose -f docker-compose.release.yml up -d
docker compose -f docker-compose.release.yml run --rm --entrypoint python \
  simulator -m app.simulation.seed_cli
```

Pin a version:

```bash
IMAGE_TAG=0.1.0 docker compose -f docker-compose.release.yml up -d
```

Make helpers (git checkout):

```bash
make release-up
make release-seed PROFILE=small
```

| Host port | Service |
|---|---|
| `8006` | HTTP API + Web UI (same port as real PVE; real PVE uses HTTPS) |
| `5432` | PostgreSQL (localhost only) |

Migrations run automatically via the `migrate` one-shot service.

Then continue from [Wait until ready](#2-wait-until-ready).

## 1b. Development checkout

```bash
make install
make up
```

Services:

| Host port | Service |
|---|---|
| `8006` | HTTP API + Web UI (same port as real PVE; real PVE uses HTTPS) |
| `5432` | PostgreSQL (localhost only) |

On real Proxmox VE the REST API is **only** `https://<host>:8006/api2/json/...`.
The lab publishes plain **HTTP** on host `:8006`; see
[Ports and TLS](configuration.md#ports-and-tls). Optional HTTPS for proxmoxer:
`docker compose --profile tls` → `https://localhost:8443/`. Host `:8007` is
**not** used (on hardware it is typically PBS, not PVE API).

Migrations apply automatically before the simulator becomes ready.

## 2. Wait until ready

```bash
curl -sS http://localhost:8006/health/live
curl -sS http://localhost:8006/health/ready
```

`/health/ready` returns HTTP 503 until PostgreSQL is reachable **and** the
latest packaged migration is applied.

## 3. Seed a profile

```bash
make seed PROFILE=small
```

`small` creates node `pve01`, two QEMU guests (`100`, `101`), one LXC (`200`),
local storages, and the standard development principals. See
[Seed profiles](seed-profiles.md) for other sizes.

## 4. Check the API version

```bash
curl -sS http://localhost:8006/api2/json/version | jq .
```

The cold-start contract defaults to the bundled PVE **9.2.3** snapshot in Docker
Compose. Switch majors 6–9 from the Web UI or
[API versions](api-versions.md).

## 5. Authenticate

```bash
curl -sS -X POST \
  -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket | jq .
```

Save `ticket` and `CSRFPreventionToken` from `data`. For mutations, send:

- Cookie: `PVEAuthCookie=<ticket>`
- Header: `CSRFPreventionToken: <token>`

Details: [Authentication](authentication.md).

## 6. List guests and start one

```bash
# replace TICKET / CSRF from the previous response
curl -sS -H "Cookie: PVEAuthCookie=$TICKET" \
  http://localhost:8006/api2/json/nodes/pve01/qemu | jq .

curl -sS -X POST \
  -H "Cookie: PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  http://localhost:8006/api2/json/nodes/pve01/qemu/100/status/start | jq .
```

Async operations return a UPID string. Poll until the task finishes:

```bash
curl -sS -H "Cookie: PVEAuthCookie=$TICKET" \
  "http://localhost:8006/api2/json/nodes/pve01/tasks/${UPID}/status" | jq .
```

## 7. Open the Web UI

Visit [http://localhost:8006/](http://localhost:8006/) for the interactive
console, contract catalog (PVE 6–9), compatibility view, runtime contract apply,
and demo-cluster controls. See [Web UI](web-ui.md) for screenshots and the
full feature list.

## 8. Try a client library

```bash
# from the repository root after make up + seed
python examples/python/proxmoxer_cookbook.py
```

More stacks: [Clients](clients.md) and [`examples/`](../examples/README.md).

## You’re done when…

- `/health/ready` returns `{"status":"ok"}` (or equivalent OK body)
- `/api2/json/version` reports the active contract version
- Ticket login succeeds for `root@pam`
- `nodes/pve01/qemu` lists seeded VMs
- At least one power or create path returns a UPID that completes successfully

## Next steps

- [Configuration](configuration.md) — env vars, workers, contract path
- [API versions](api-versions.md) — hot-swap majors 6–9
- [Clients](clients.md) — Ansible, Terraform, Pulumi, Go, Java, Perl
- [Operations](operations.md) — reseed, migrate, upgrades
