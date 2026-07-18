**Language / Язык:** [English](storage-backup.md) | [Русский](../ru/domains/storage-backup.md)

# Storage & backup

## Storage

- Cluster and node storage inventories persist in normalized storage tables.
- Content listings and mutations update `storage_contents` (and related rows).
- `broken-storage` seed marks `local-lvm` unavailable for failure testing.

## Backup

- Backup jobs, metadata, and `vzdump`-style task paths create durable task rows
  and backup records.
- Workers execute leased backup tasks similarly to guest operations.

No real remote backup targets are contacted; object state remains inside
PostgreSQL.
