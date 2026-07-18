**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Pulumi integration suite

Docker-only suite against the Proxmox API simulator.

| Layer | What it covers |
|---|---|
| **A — Surface (HTTP contract matrix)** | **100%** means every declared contract method for PVE majors **6–9** (path+verb: GET/PUT/POST/DELETE), plus **synthetic HEAD on each GET path**. Ticket + CSRF on mutations; form-urlencoded bodies; Proxmox `{ "data": … }` envelope. PASS requires `declared == probed` per major **and** aggregate, `critical=0` (501, “not supported”, 5xx, exceptions, empty/wrong 2xx envelopes). HEAD is in the verb histogram but **not** in the declared/probed denominator. |
| **B — Lifecycle** | **`pulumi-proxmoxve` smoke only** (BPG Terraform bridge) — Provider, inventory data sources, `VmLegacy` + non-empty checks. **Not** 100% API and **not** provider resource-count coverage. HTTPS via lab TLS gateway; surface stays HTTP. |

Reports (`pulumi/reports/report.html`, `results.json`, `junit.xml`) include **Full contract coverage**, a **verb histogram (incl. HEAD)**, and a line like:

`Coverage: N/N methods across majors 6–9 (critical=0)`

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

### Quick curl (ticket → GET/POST + report)

Against a running suite stack (`http://localhost:8006`):

```bash
TICKET=$(curl -s -c /tmp/pve.ck -b /tmp/pve.ck \
  -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket)
echo "$TICKET" | jq .
CSRF=$(echo "$TICKET" | jq -r .data.CSRFPreventionToken)
curl -s -b /tmp/pve.ck http://localhost:8006/api2/json/version | jq .
curl -s -b /tmp/pve.ck -H "CSRFPreventionToken: $CSRF" \
  -d 'vmid=100&name=demo' \
  http://localhost:8006/api2/json/nodes/pve1/qemu | jq .
```

Open the HTML report: `pulumi-tests/pulumi/reports/report.html`.

Provider env (set by Compose): `PROXMOX_VE_ENDPOINT=https://tls-gateway:8443/`
(internal suite TLS — `pulumi-proxmoxve` rejects `http://`), plus username/password
/`INSECURE`. Surface probe uses `API_URL=http://simulator:8006`. Host lab URL
remains plain `http://localhost:8006/` (Kubernetes HTTPS is Ingress-only).
Seed for CI/suite: `SEED_PROFILE=small` (Compose default). Default node name in
that profile is **`pve1`** (not `pve01`).

## Latest local results (2026-07-18)

`make pulumi-tests` → **Suite PASS** (~28s): lifecycle OK; surface majors
6.4-15 / 7.4-16 / 8.4.5 / 9.2.3 with `critical=0`; coverage **2324/2324**.
Report: `pulumi/reports/report.html`. Broader CI notes:
[docs/testing.md](../docs/testing.md).
