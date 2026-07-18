**Language / Язык:** [English](../../domains/core-cluster.md) | [Русский](core-cluster.md)

# Core и кластер

## Version

`GET /version` отражает `source_version` **активного** контракта (cold-start
snapshot или hot-swapped major).

## Nodes

- Endpoints списка и статуса устойчивы и формируются из seeded / созданных nodes.
- Имя node по умолчанию в seed-профиле `small`: **`pve01`**.
- Операционные мутации node (network, apt, disks, services, DNS/time/hosts,
  certificates, …) сохраняются в `nodes.metadata.ops`.

## Cluster

- `/cluster/resources` и связанные inventory views читают guests и storages из
  PostgreSQL.
- Cluster options, status, tasks, logs, replication, config/join helpers
  сохраняют cluster metadata и связанные таблицы.

Работает для всех заявленных методов на major 6–9 для этих путей. Используйте
каталог Web UI, чтобы проверить различия параметров между версиями.
