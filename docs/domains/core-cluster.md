**Language / Язык:** [English](core-cluster.md) | [Русский](../ru/domains/core-cluster.md)

# Core & cluster

## Version

`GET /version` reflects the **active** contract’s `source_version` (cold-start
snapshot or hot-swapped major).

## Nodes

- List and status endpoints are durable and driven by seeded / created nodes.
- Default `small` seed node name: **`pve01`**.
- Node operational mutations (network, apt, disks, services, DNS/time/hosts,
  certificates, …) persist under `nodes.metadata.ops`.

## Cluster

- `/cluster/resources` and related inventory views read PostgreSQL-backed guests
  and storages.
- Cluster options, status, tasks, logs, replication, config/join helpers persist
  cluster metadata and related tables.

Works for all declared methods on majors 6–9 for these paths. Use the Web UI
catalog to inspect version-specific parameter differences.
