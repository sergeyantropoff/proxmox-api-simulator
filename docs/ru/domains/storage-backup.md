**Language / Язык:** [English](../../domains/storage-backup.md) | [Русский](storage-backup.md)

# Storage и backup

## Storage

- Cluster и node storage inventories сохраняются в нормализованных storage tables.
- Content listings и мутации обновляют `storage_contents` (и связанные строки).
- Seed `broken-storage` помечает `local-lvm` недоступным для тестирования сбоев.

## Backup

- Backup jobs, metadata и task-пути в стиле `vzdump` создают устойчивые task rows
  и backup records.
- Workers выполняют leased backup tasks аналогично guest operations.

Реальные удалённые backup targets не вызываются; состояние объектов остаётся
внутри PostgreSQL.
