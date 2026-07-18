**Language / Язык:** [English](../seed-profiles.md) | [Русский](seed-profiles.md)

# Профили seed

Seed **атомарно** заменяет изменяемое состояние симуляции и использует
детерминированные UUIDv5-идентификаторы для воспроизводимости лабораторий.

```bash
make seed PROFILE=small
```

## Профили

| Профиль | Содержимое (кратко) |
|---|---|
| `minimal` | Один узел `pve01`, storage `local` + `local-lvm`. Используется после demo unload в Web UI. |
| `small` | Один узел, QEMU `100`/`101`, LXC `200`, storage, завершённые задачи, полный набор identity. |
| `medium` | Узлы `pve1`/`pve2`/`pve3`, 50 QEMU, 20 LXC, per-node `local-pveN` + storage `shared`, development pool, больше задач. |
| `large` | Настраиваемые узлы/ресурсы (`SEED_LARGE_NODES`, `SEED_LARGE_RESOURCES`, по умолчанию 10 000 гостей). |
| `ha-demo` | `medium` плюс HA resource wiring для VM 100. |
| `broken-storage` | `small` с offline `local-lvm` / симулированной I/O ошибкой. |
| `demo-cluster` | Крупный enterprise-набор для UI (много узлов/гостей/Ceph/HA/history). Предпочтительно загружать через demo-контролы Web UI. |

Каждый профиль seed'ит только durable-состояние — обработчики читают/пишут PostgreSQL и
**не** подмешивают catalog/template defaults на GET:

- `clusters.metadata`: firewall (scopes + macros), SDN, notifications (+ matcher
  catalogs), ACME (accounts/plugins/directories/schema), mappings, replication
  (+ logs), metrics (servers + export), jobs, HA (`ha` / `ha_groups` / `ha_rules`
  + status), Ceph (+ pools/cmd_safety), QEMU CPU flags/models, cluster options/config, quorate
- `nodes.metadata.ops`: network, disks, apt, services, hardware, scan, subscription,
  dns/time/config/status/ip, certificates, capabilities, hosts, journal/syslog/netstat,
  report/rrd/rrddata, oci_tags, cluster_status, node Ceph, aplinfo, vzdump defaults
- guest `resources.state` (via `enrich_guest_state`): agent results/files, rrd/rrddata,
  migrate_preconditions, LXC interfaces, cloudinit dump
- storage `storages.config` (via `enrich_storage_state`): rrd/rrddata, file_restore,
  import_metadata, identity

## Примеры

```bash
make seed PROFILE=small
make seed PROFILE=medium
make seed PROFILE=ha-demo
make seed PROFILE=broken-storage
make seed PROFILE=large
make seed PROFILE=minimal
# demo-cluster большой; для интерактива предпочтительна загрузка demo в Web UI
make seed PROFILE=demo-cluster
```

## Demo-кластер через UI

Интерактивная консоль может загружать и выгружать demo-набор данных:

- `POST /ui/api/demo/load`
- `POST /ui/api/demo/unload` — стирает состояние, созданное через API, затем загружает `minimal`
- `GET /ui/api/demo/state`

Эти helper-эндпоинты UI ориентированы на разработку и сегодня не аутентифицируются
отдельно. Считайте их только лабораторными контролами.

## Reseed vs состояние клиента

Terraform, Pulumi и Ansible могут по-прежнему хранить resource state после reseed.
Обновите или destroy/recreate внешнее состояние после замены содержимого симуляции в
PostgreSQL. См. [Эксплуатация](operations.md) и client cookbook'и.
