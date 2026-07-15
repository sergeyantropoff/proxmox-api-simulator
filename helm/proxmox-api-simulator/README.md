# Helm chart: proxmox-api-simulator

Deploys the published runtime image
[`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)
with optional Bitnami PostgreSQL, migrations, seed Job, Ingress, and
cert-manager Let's Encrypt `ClusterIssuer` resources.

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
