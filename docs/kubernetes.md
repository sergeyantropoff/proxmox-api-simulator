**Language / Язык:** [English](kubernetes.md) | [Русский](ru/kubernetes.md)

# Kubernetes / Helm

Deploy the published Docker Hub runtime image with the chart in
[`helm/proxmox-api-simulator`](../helm/proxmox-api-simulator).

Image: [`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)

> **Laboratory / CI only.** Chart defaults include weak placeholder secrets.
> Always override `secret.ticketSigningKey` and `postgresql.auth.password`
> before any shared or Internet-facing install. See [SECURITY.md](../SECURITY.md).

## Transport note (Compose vs Helm)

| Path | Client URL |
|---|---|
| Local Compose (`docker-compose*.yml`) | **HTTP** `:8006` (simulator process) |
| Helm Service / `kubectl port-forward` | **HTTP** `:8006` (simulator process; TLS terminates at Ingress if enabled) |
| Helm Ingress + cert-manager | **HTTPS** on your hostname |

## Prerequisites

- Kubernetes 1.27+ (or comparable)
- Helm 3.14+
- [Ingress NGINX](https://kubernetes.github.io/ingress-nginx/) (or another
  IngressClass that supports HTTP-01)
- [cert-manager](https://cert-manager.io/) installed cluster-wide

Example cert-manager install:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.2/cert-manager.yaml
```

## Quick install (Hub release + Ingress + Let's Encrypt)

From a git checkout of this repository:

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set 'ingress.hosts[0].host=pve-sim.example.com' \
  --set 'ingress.tls[0].hosts[0]=pve-sim.example.com' \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

What this does:

1. Pulls `inecs/proxmox-api-simulator:0.1.0` (see `image.tag` in the example file).
2. Installs bundled PostgreSQL 17 (`postgres:17.5-bookworm`, same as Compose).
3. Runs schema migrations in an init container (idempotent).
4. Seeds the `small` lab profile (`seed.enabled=true`).
5. Creates `ClusterIssuer` resources:
   - `letsencrypt-prod`
   - `letsencrypt-staging`
6. Creates an Ingress with
   `cert-manager.io/cluster-issuer: letsencrypt-prod` and a TLS secret
   `proxmox-api-simulator-tls`.

DNS for `pve-sim.example.com` must point at your Ingress controller. Then:

```bash
kubectl -n proxmox-sim get certificate,ingress,pods
# wait until Certificate READY=True
curl -sS https://pve-sim.example.com/health/ready
open https://pve-sim.example.com/
```

Default seeded login: `root@pam` / `secret`.

### Staging first (recommended)

Validate HTTP-01 without hitting production rate limits:

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set certManager.useStaging=true \
  --set 'ingress.hosts[0].host=pve-sim.example.com' \
  --set 'ingress.tls[0].hosts[0]=pve-sim.example.com' \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

Browsers will not trust the staging CA — use `curl -k` while testing. Flip
`certManager.useStaging=false` and recreate the Certificate/TLS secret for
production.

## Minimal install (ClusterIP + port-forward)

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set seed.enabled=true

kubectl -n proxmox-sim port-forward svc/pve-sim-proxmox-api-simulator 8006:8006
```

Open http://127.0.0.1:8006/ (plain HTTP — the chart does not ship the Compose
TLS gateway; use Ingress for HTTPS).

## External PostgreSQL

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  --set postgresql.enabled=false \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set secret.databaseUrl='postgresql://user:pass@pg.example.com:5432/proxmox_simulator'
```

Or use `secret.existingSecret` with keys `DATABASE_URL` and `TICKET_SIGNING_KEY`.

## How TLS issuance works

When `certManager.enabled=true` and `certManager.createClusterIssuer=true`, the
chart creates ACME `ClusterIssuer` objects that solve HTTP-01 through your
Ingress class. The Ingress template adds:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - secretName: proxmox-api-simulator-tls
      hosts: [pve-sim.example.com]
```

cert-manager then creates a `Certificate`, completes HTTP-01, and stores the
Let's Encrypt key pair in that TLS secret. The chart does **not** install
cert-manager or the Ingress controller — only the issuers + Ingress wiring.

If ClusterIssuers already exist cluster-wide, set:

```yaml
certManager:
  enabled: true
  createClusterIssuer: false
  issuerName: your-existing-issuer
```

## Local chart validation

From the repository root (requires Helm 3.14+):

```bash
make helm-lint
make helm-template
```

`helm lint` should report 0 failures (an informational note that Chart.yaml has no
`icon` is expected). `helm template` renders Deployment (with a migrate
initContainer by default), Service, Secret, PostgreSQL StatefulSet, optional
standalone migrate Job (`migrate.asJob`), seed Job, Ingress, and ClusterIssuers.

## Operations

```bash
# logs
kubectl -n proxmox-sim logs -l app.kubernetes.io/name=proxmox-api-simulator -c simulator -f

# reseed
kubectl -n proxmox-sim exec deploy/pve-sim-proxmox-api-simulator -- \
  python -m app.simulation.seed_cli
# SEED_PROFILE via: kubectl set env ... or --set seed.profile=medium and upgrade

# uninstall
helm -n proxmox-sim uninstall pve-sim
```

## Values reference

See [`helm/proxmox-api-simulator/values.yaml`](../helm/proxmox-api-simulator/values.yaml)
and the chart README. Related docs:

- [Getting started](getting-started.md) — Compose paths
- [Operations](operations.md) — Docker Hub publish / release compose
- [Security](security.md) — lab credentials and trust boundary
