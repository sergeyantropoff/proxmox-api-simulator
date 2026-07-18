**Language / Язык:** [English](testing.md) | [Русский](ru/testing.md)

# Testing

How the repository is tested and where each suite lives.

## Layout

| Location | Role |
|---|---|
| `tests/unit/` | Offline unit tests (handlers, contracts, seed, workers, …) |
| `tests/integration/` | PostgreSQL-backed tests (migrations, durable task leases) |
| `tests/compatibility/` | Surface probe, group smoke, proxmoxer HTTPS, verified-surface ledgers |
| `pulumi-tests/` | Pulumi surface matrix (majors 6–9) + `pulumi-proxmoxve` lifecycle; HTML report |

Seed used by most suites: `app/simulation/seed.py` (`lab` for in-process surface CI, `small` for Compose / Pulumi).

## Make targets

```bash
make test-unit              # pytest: unit only
make test-integration       # pytest -m integration (needs Postgres)
make test-surface           # every declared method on majors 6–9
make test-compatibility     # proxmoxer smoke (Compose --profile tls)
make ci                     # ruff + mypy + offline pytest + surface
make ci-all                 # ci + remaining integration + proxmoxer
make pulumi-tests           # Pulumi surface + lifecycle; writes HTML report
```

GitHub Actions on push/PR to `main` runs `make ci` plus Compose/Helm validation.
Run `make ci-all` and `make pulumi-tests` locally before larger API changes.

Pulumi report (after a suite run):
`pulumi-tests/pulumi/reports/report.html` — see [`pulumi-tests/README.md`](../pulumi-tests/README.md).

## Latest local results (2026-07-18)

Full unrestricted run on this checkout:

| Gate | Result |
|---|---|
| `make ci-all` | **PASS** (exit 0) |
| — unit (offline pytest) | 193 passed |
| — surface probe (majors 6–9) | PASS |
| — integration | 12 passed |
| — proxmoxer compatibility | PASS |
| `make pulumi-tests` | **PASS** (exit 0), suite ~28s |
| — lifecycle (`pulumi-proxmoxve`) | PASS |
| — surface PVE 6.4-15 / 7.4-16 / 8.4.5 / 9.2.3 | PASS, `critical=0` |
| — coverage | **2324 / 2324** methods across majors 6–9 |

Report artifact: `pulumi-tests/pulumi/reports/report.html` (also `results.json`, `junit.xml`).
