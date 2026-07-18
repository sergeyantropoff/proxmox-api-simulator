**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Pulumi integration suite

Docker-only suite against the Proxmox API simulator.

| Layer | What it covers |
|---|---|
| **Surface** | **100%** of declared contract methods for PVE majors **6–9** (every path+verb) via HTTP (`pvelib/surface.py`). Suite PASS requires `declared == probed` per major and zero critical failures (501, “not supported” messages, 5xx, exceptions, unknown verbs). |
| **Lifecycle** | **`pulumi-proxmoxve` only** (BPG Terraform bridge) — Provider, inventory data sources, `VmLegacy` + non-empty checks. Negative auth via httpx. This is **not** full API coverage; the provider exposes dozens of resources, not thousands of contract methods. Provider uses internal HTTPS gateway; surface stays HTTP. |

Reports (`pulumi/reports/report.html`, `results.json`, `junit.xml`) include a **Full contract coverage** summary with per-major and total `declared`/`probed` counts (e.g. `Coverage: 2324/2324 methods across majors 6–9`).

## Layout

```
pulumi-tests/
  pulumi/
    run_suite.py
    report.py
    pvelib/                 # httpx client + surface probe
    programs/lifecycle/     # pulumi-proxmoxve program
  docker/docker-compose.yml
  Makefile
```

## Run

From the repository root:

```bash
make pulumi-tests
```

Or:

```bash
cd pulumi-tests
make up
make test-smoke
make test
open pulumi/reports/report.html
make down
```

Provider env (set by Compose): `PROXMOX_VE_ENDPOINT=https://tls-gateway:8443/`
(internal suite TLS — `pulumi-proxmoxve` rejects `http://`), plus username/password
/`INSECURE`. Surface probe uses `API_URL=http://simulator:8006`. Host lab URL
remains plain `http://localhost:8006/` (Kubernetes HTTPS is Ingress-only).
