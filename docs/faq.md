**Language / Язык:** [English](faq.md) | [Русский](ru/faq.md)

# FAQ

## Is this a real Proxmox hypervisor?

No. It is an API and state simulator. Guests, storages, Ceph, and HA are durable
PostgreSQL models, not KVM/LXC processes.

## Do you really cover API versions 6, 7, 8, and 9?

Yes — **100%** of declared methods for each bundled major have registered
semantic handlers. Switch majors via cold-start snapshot or runtime hot-swap.
See [API versions](api-versions.md) and [Compatibility](compatibility.md).

## Can I use this in CI for Terraform / Ansible / custom clients?

Yes. That is a primary use case. Pin the API major, seed a profile, and point
clients at **HTTP `:8006`** (Compose) or your Ingress **HTTPS** hostname on
Kubernetes. See [Clients](clients.md). For the
Pulumi surface suite see [`pulumi-tests/`](../pulumi-tests/README.md).
Full test map and latest recorded results: [Testing](testing.md).

## Why do some OpenID / LDAP / ACME / Ceph calls “succeed” without remotes?

Those domains persist **local** simulator state. They intentionally do not call
real external systems.

## Does registry coverage mean perfect Proxmox parity?

It means every declared route has a durable handler and is subject to the
project’s verification suites for majors 6–9. Exact edge-case parity with a
physical cluster can still differ; use evidence endpoints and your own client
tests for certification claims.

## Where is the Web UI?

[http://localhost:8006/](http://localhost:8006/) after `make up`.

## Can I deploy on Kubernetes?

Yes. Use the Helm chart under `helm/proxmox-api-simulator` with the published
Hub image. Ingress + cert-manager Let's Encrypt is supported — see
[Kubernetes / Helm](kubernetes.md).

## Which node name does the small seed use?

`pve01`. Profiles `medium` and `ha-demo` use **`pve1` / `pve2` / `pve3`**.

## What ports does real Proxmox VE use vs this simulator?

Real PVE serves the Web UI and REST API on **HTTPS `:8006`** only. Related
management ports include SPICE `:3128`, VNC `:5900–5999`, SSH `:22`, and
Corosync UDP `:5405–5412`. Port `:8007` on real hardware is typically
**Proxmox Backup Server**, not PVE.

This lab publishes plain **HTTP `:8006`** in Compose (same port number as real
PVE). HTTPS belongs on Kubernetes Ingress. Optional proxmoxer TLS:
`docker compose --profile tls` on `:8443`. Host `:8007` is **not** used. Details:
[Ports and TLS](configuration.md#ports-and-tls).
