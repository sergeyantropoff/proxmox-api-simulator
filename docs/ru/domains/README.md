**Language / Язык:** [English](../../domains/README.md) | [Русский](README.md)

# Руководства по доменам

Эти страницы описывают устойчивую семантику по областям API. Для исчерпывающих
списков методов используйте каталог Web UI или OpenAPI (`/docs`) для активной
major-версии — заявленное покрытие составляет **100%** для PVE 6–9.

| Руководство | Темы |
|---|---|
| [Core и кластер](core-cluster.md) | version, nodes, cluster resources/options/status |
| [Access](access.md) | users, groups, roles, ACL, realms, tokens, TFA, OpenID |
| [QEMU](qemu.md) | guests, power, disks, snapshots, clone/migrate, agent |
| [LXC](lxc.md) | containers and parallel lifecycle operations |
| [Storage и backup](storage-backup.md) | storages, content, vzdump / backup jobs |
| [Firewall](firewall.md) | cluster / node / guest firewall objects |
| [HA](ha.md) | groups, resources, status |
| [Ceph](ceph.md) | simulated Ceph configuration and status |
| [Pools](pools.md) | pools and membership |
| [SDN](sdn.md) | zones, VNets, subnets, controllers, IPAM |
| [Cluster extras](cluster-extras.md) | notifications, ACME, mapping, metrics servers |
| [Tasks](tasks.md) | UPID workers, status, logs |

## Карта персистентности

- Guests / HA / storage / identity → нормализованные таблицы
- Свободная конфигурация кластера → `clusters.metadata` jsonb
- Операции на уровне узла (network, disks, apt, …) → `nodes.metadata` под ключом `ops`
