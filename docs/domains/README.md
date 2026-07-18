**Language / Язык:** [English](README.md) | [Русский](../ru/domains/README.md)

# Domain guides

These pages summarize durable semantics by area. For exhaustive method lists,
use the Web UI catalog or OpenAPI (`/docs`) against the active major — declared
coverage is **100%** for PVE 6–9.

| Guide | Topics |
|---|---|
| [Core & cluster](core-cluster.md) | version, nodes, cluster resources/options/status |
| [Access](access.md) | users, groups, roles, ACL, realms, tokens, TFA, OpenID |
| [QEMU](qemu.md) | guests, power, disks, snapshots, clone/migrate, agent |
| [LXC](lxc.md) | containers and parallel lifecycle operations |
| [Storage & backup](storage-backup.md) | storages, content, vzdump / backup jobs |
| [Firewall](firewall.md) | cluster / node / guest firewall objects |
| [HA](ha.md) | groups, resources, status |
| [Ceph](ceph.md) | simulated Ceph configuration and status |
| [Pools](pools.md) | pools and membership |
| [SDN](sdn.md) | zones, VNets, subnets, controllers, IPAM |
| [Cluster extras](cluster-extras.md) | notifications, ACME, mapping, metrics servers |
| [Tasks](tasks.md) | UPID workers, status, logs |

## Persistence map

- Guests / HA / storage / identity → normalized tables
- Loose cluster config → `clusters.metadata` jsonb
- Per-node ops (network, disks, apt, …) → `nodes.metadata` under `ops`
