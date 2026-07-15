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
clients at HTTP `:8006` or HTTPS `:8007`. See [Clients](clients.md).

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

`pve01`.
