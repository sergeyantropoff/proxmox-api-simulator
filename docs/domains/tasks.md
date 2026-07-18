**Language / Язык:** [English](tasks.md) | [Русский](../ru/domains/tasks.md)

# Tasks

Long-running operations return a Proxmox-style **UPID**. Task rows, events,
optional resource locks, and idempotency metadata commit together.

## Client pattern

1. `POST`/`DELETE` mutation → read UPID from `data`
2. Poll `GET /nodes/{node}/tasks/{upid}/status` until finished
3. Optionally fetch `.../log`

## Workers

- Claim with `FOR UPDATE SKIP LOCKED`
- Renewable leases (`TASK_LEASE_SECONDS`)
- Progress + append-only logs
- Recovery after process failure

Simulation durations honour `SIMULATION_TIME_SCALE`. Worker lease safety uses
wall-clock time so an accelerated scenario cannot invalidate distributed claim
semantics.

See [API surface](../api-surface.md) and [Operations](../operations.md).
