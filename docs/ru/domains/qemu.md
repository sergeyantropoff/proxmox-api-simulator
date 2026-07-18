**Language / Язык:** [English](../../domains/qemu.md) | [Русский](qemu.md)

# QEMU

Полная contract-поверхность для QEMU guests на активной major, включая:

- Create / sync & async config update / delete (UPID для async)
- Power: start, stop, shutdown, reboot, reset, suspend, resume
- Явная state machine + per-VM PostgreSQL lock
- Snapshots (create/delete/rollback как tasks)
- Clone и local migration (UPID)
- Disk resize (sync; shrink отклоняется) и disk move (task)
- Pending config view
- Guest agent read-only subset (info, OS/hostname, network, time, ping) при
  `agent=1` и запущенном guest
- Cloud-init, consoles, RRD, guest firewall objects — как заявлено в контракте

Индексированные поля контракта, такие как `scsi[n]`, принимают конкретные имена
(`scsi0`, …). Неизвестные version-dependent parameters сохраняются в JSONB.
