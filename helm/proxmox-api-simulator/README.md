**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Helm chart: proxmox-api-simulator

Deploys the published runtime image
[`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)
with optional official PostgreSQL (`postgres:17.5-bookworm`), migrations, seed Job, Ingress, and
cert-manager Let's Encrypt `ClusterIssuer` resources.

> **Laboratory / CI only.** Chart defaults include weak placeholder secrets
> (`change-me…`, DB password `proxmox`). Always override
> `secret.ticketSigningKey` and `postgresql.auth.password` (as in the install
> example below) before any networked or shared cluster. See
> [SECURITY.md](../../SECURITY.md).

Full guide: [docs/kubernetes.md](../../docs/kubernetes.md).

## Quick install

Prerequisites: Kubernetes, Helm 3, ingress-nginx (or compatible), cert-manager.

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set ingress.hosts[0].host=pve-sim.example.com \
  --set ingress.tls[0].hosts[0]=pve-sim.example.com \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

Point DNS for your host at the Ingress controller, wait for the Certificate to
become Ready, then open `https://pve-sim.example.com/`.

## Values overview

| Key | Default | Meaning |
|---|---|---|
| `image.repository` | `inecs/proxmox-api-simulator` | Hub image |
| `image.tag` | chart `appVersion` | Image tag |
| `postgresql.enabled` | `true` | Bundle official PostgreSQL StatefulSet |
| `secret.databaseUrl` / `externalDatabase.*` | | External DB when postgres disabled |
| `ingress.enabled` | `false` | Expose via Ingress |
| `certManager.enabled` | `false` | Annotate Ingress + optional ClusterIssuers |
| `seed.enabled` | `false` | Post-install seed Job |

See [`values.yaml`](values.yaml) and [`values-ingress-example.yaml`](values-ingress-example.yaml).
