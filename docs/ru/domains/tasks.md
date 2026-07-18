**Language / Язык:** [English](../../domains/tasks.md) | [Русский](tasks.md)

# Tasks

Долгие операции возвращают **UPID** в стиле Proxmox. Task rows, events,
опциональные resource locks и idempotency metadata фиксируются вместе.

## Паттерн для клиента

1. `POST`/`DELETE` mutation → прочитать UPID из `data`
2. Опрашивать `GET /nodes/{node}/tasks/{upid}/status` до завершения
3. При необходимости запросить `.../log`

## Workers

- Claim через `FOR UPDATE SKIP LOCKED`
- Возобновляемые leases (`TASK_LEASE_SECONDS`)
- Progress + append-only logs
- Recovery после сбоя процесса

Длительность симуляции учитывает `SIMULATION_TIME_SCALE`. Безопасность lease
worker использует wall-clock time, чтобы ускоренный сценарий не нарушал
семантику распределённого claim.

См. [API surface](../api-surface.md) и [Operations](../operations.md).
