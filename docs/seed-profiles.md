# Seed profiles

Seeds replace mutable simulation state **atomically** and use deterministic
UUIDv5 identifiers so labs are reproducible.

```bash
make seed PROFILE=small
```

## Profiles

| Profile | Contents (summary) |
|---|---|
| `minimal` | One node `pve01`, `local` + `local-lvm` storage. Used after Web UI demo unload. |
| `small` | One node, QEMU `100`/`101`, LXC `200`, storages, completed tasks, full identity set. |
| `medium` | Three nodes, 50 QEMU, 20 LXC, local + shared storage, development pool, more tasks. |
| `large` | Configurable nodes/resources (`SEED_LARGE_NODES`, `SEED_LARGE_RESOURCES`, default 10 000 guests). |
| `ha-demo` | `medium` plus HA resource wiring for VM 100. |
| `broken-storage` | `small` with `local-lvm` offline / simulated I/O error. |
| `demo-cluster` | Large UI-oriented enterprise dataset (many nodes/guests/Ceph/HA/history). Prefer loading via the Web UI demo controls. |

## Examples

```bash
make seed PROFILE=small
make seed PROFILE=medium
make seed PROFILE=ha-demo
make seed PROFILE=broken-storage
make seed PROFILE=large
```

## Demo cluster via UI

The interactive console can load and unload the demo dataset:

- `POST /ui/api/demo/load`
- `POST /ui/api/demo/unload` — wipes API-created state then loads `minimal`
- `GET /ui/api/demo/state`

These UI helper endpoints are development-oriented and are not separately
authenticated today. Treat them as lab controls only.

## Reseed vs client state

Terraform, Pulumi, and Ansible may still hold resource state after a reseed.
Refresh or destroy/recreate external state after replacing the PostgreSQL
simulation contents. See [Operations](operations.md) and client cookbooks.
