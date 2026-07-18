# Docker Hub overview (paste into Hub)

Copy the block below into the **Full description** of
[`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)
so Hub wording matches GitHub (stateful simulator — not a thin mock).

---

**proxmox-api-simulator** — stateful asynchronous Proxmox VE API simulator for
labs and CI. PostgreSQL-backed mutations, durable UPIDs, official API contracts
for PVE 6–9, and the same `/api2/json` surface clients already speak.

**Laboratory / CI only.** Default credentials and signing keys are intentional
lab defaults. Do **not** expose this image to the public Internet without
replacing secrets and adding your own network controls.

### Quick start

```bash
# from a git checkout (needs docker-compose.release.yml + docker/tls/)
docker compose -f docker-compose.release.yml up -d
docker compose -f docker-compose.release.yml run --rm --entrypoint python \
  simulator -m app.simulation.seed_cli

curl -sS http://localhost:8006/health/ready
curl -sS http://localhost:8006/api2/json/version
```

- HTTP API + Web UI: `http://localhost:8006/`
- Optional HTTPS for proxmoxer: `docker compose --profile tls` → `https://localhost:8443/`
- Seeded admin: `root@pam` / `secret`
- Source & docs: https://github.com/sergeyantropoff/proxmox-api-simulator
- Helm chart: `helm/proxmox-api-simulator` in the same repository

### Tags

| Tag | Meaning |
|---|---|
| `0.1.0`, `…` | Immutable release from `pyproject.toml` / `make release` |
| `latest` | Most recent `make release` (when `PUSH_LATEST=1`) |
