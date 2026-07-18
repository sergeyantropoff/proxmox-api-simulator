**Language / Язык:** [English](CONTRIBUTING.md) | [Русский](CONTRIBUTING.ru.md)

# Contributing

Thanks for helping improve the Proxmox VE API laboratory simulator.

## Prerequisites

- Docker + Docker Compose
- `make`
- No local Python toolchain required for day-to-day work (tools run in Compose)

## Local loop

```bash
cp -n .env.example .env
make install
make up
make seed PROFILE=small
curl -sS http://localhost:8006/health/ready
```

Primary HTTP endpoint (same port as real PVE): `http://localhost:8006/`

Optional HTTPS for proxmoxer: `docker compose --profile tls` →
`https://localhost:8443/` (self-signed — use `curl -sk` or accept the browser
warning).

## Quality gates (must pass before a PR)

```bash
make ci            # ruff format/check + mypy + offline pytest + surface probe
make ci-all        # also remaining integration + proxmoxer compatibility
make helm-lint     # chart lint (+ ingress example values)
make pulumi-tests  # Pulumi surface (majors 6–9) + pulumi-proxmoxve lifecycle
```

GitHub Actions runs `make ci` plus Compose/Helm validation on every push and PR
to `main`. Run `make ci-all`, `make helm-lint`, and `make pulumi-tests` locally
before larger API or client-facing changes.

## Project rules worth remembering

1. Mutations must **persist to PostgreSQL** (tables and/or jsonb metadata).
2. Do **not** add user-facing “not supported in the simulator” style errors —
   see `.cursor/rules/durable-simulator.mdc`.
3. Prefer matching Proxmox request/response shapes from the contract snapshot.
4. Keep EN and RU docs in sync when you change operator-facing behaviour.

## Docs

- Index: [docs/README.md](docs/README.md) · [docs/ru/README.md](docs/ru/README.md)
- Security / lab threat model: [SECURITY.md](SECURITY.md)

## Releases

Maintainers publish the runtime image with:

```bash
docker login
make release          # pushes inecs/proxmox-api-simulator:<version> (+ :latest)
```

After a public release, paste the overview from
[docs/docker-hub-overview.md](docs/docker-hub-overview.md) into the Docker Hub
repository description if it drifted.
