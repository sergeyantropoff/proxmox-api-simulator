**Language / Язык:** [English](../../domains/lxc.md) | [Русский](lxc.md)

# LXC

Container API повторяют паттерны жизненного цикла QEMU там, где это заявлено
контрактом: CRUD, power, clone/migrate, snapshots, volume operations, consoles,
RRD и firewall objects.

Мутации сохраняются в нормализованные container tables и связанные metadata.
Асинхронные пути возвращают UPID по той же модели leased-worker, что и QEMU.

Seed-профили:

- `small` — CT `200` на `pve01`
- `medium` / `large` / `demo-cluster` — множество containers
