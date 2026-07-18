# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-17

### Added

- Stateful Proxmox VE API simulator backed by PostgreSQL with durable UPID task
  workers.
- Imported official API contracts for PVE majors **6.4-15**, **7.4-16**,
  **8.4.5**, and **9.2.3** with full handler registration for declared methods.
- Interactive Web UI (catalog, runtime contract Apply, task monitor).
- Development Compose stack with plain HTTP on host `:8006` (real PVE port; real
  PVE uses HTTPS). Optional TLS gateway via `--profile tls` on `:8443`.
- Published runtime image workflow (`make release`) for
  [`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator).
- `docker-compose.release.yml` + Helm chart with optional Ingress / cert-manager.
- Bilingual documentation (English + Russian) and client cookbooks.
- GitHub Actions CI (`make ci`, Compose/Helm validation).

### Security

- Explicit lab-only threat model: default secrets and open `/ui` / `/admin`
  helpers are for local/CI use. See [SECURITY.md](SECURITY.md).

[0.1.0]: https://github.com/sergeyantropoff/proxmox-api-simulator/releases/tag/v0.1.0
