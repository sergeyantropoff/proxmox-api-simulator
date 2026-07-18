**Language / Язык:** [English](lxc.md) | [Русский](../ru/domains/lxc.md)

# LXC

Container APIs mirror the QEMU lifecycle patterns where the contract declares
them: CRUD, power, clone/migrate, snapshots, volume operations, consoles, RRD,
and firewall objects.

Mutations persist to normalized container tables and related metadata. Async
paths return UPIDs under the same leased-worker model as QEMU.

Seed profiles:

- `small` — CT `200` on `pve01`
- `medium` / `large` / `demo-cluster` — many containers
