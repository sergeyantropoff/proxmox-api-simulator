# QEMU

Full contract surface for QEMU guests on the active major, including:

- Create / sync & async config update / delete (UPID where async)
- Power: start, stop, shutdown, reboot, reset, suspend, resume
- Explicit state machine + per-VM PostgreSQL lock
- Snapshots (create/delete/rollback as tasks)
- Clone and local migration (UPID)
- Disk resize (sync; shrink rejected) and disk move (task)
- Pending config view
- Guest agent read-only subset (info, OS/hostname, network, time, ping) when
  `agent=1` and the guest is running
- Cloud-init, consoles, RRD, guest firewall objects as declared

Indexed contract fields such as `scsi[n]` accept concrete names (`scsi0`, …).
Unknown version-dependent parameters are retained in JSONB.
