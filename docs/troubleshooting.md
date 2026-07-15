# Troubleshooting

## Ready stays unavailable

1. Confirm Postgres: `make logs` / Compose health.
2. Run `make db-migrate`.
3. Hit `/health/ready` again.

Workers may retry until migrations catch up after a late migrate.

## Unexpected HTTP 501

Declared methods on majors **6–9** should have handlers. If you see 501:

- Confirm the active runtime (`/api2/json/version` and Web UI runtime label).
- Confirm you are calling the path/verb exactly as declared for that major.
- Check `CONTRACT_FALLBACK` is not masking a different issue with fixture mode.
- Report a regression — full registry coverage is expected.

## 401 / 403

- Ticket expired or cookie not sent.
- Mutation missing `CSRFPreventionToken` on a ticket session.
- API token malformed (`PVEAPIToken=user@realm!id=secret`).
- ACL denial (try `auditor@pve` vs `root@pam` to compare).

## Task never finishes

- Inspect `/nodes/{node}/tasks/{upid}/status` and `/log`.
- Check worker logs (`make logs`).
- Verify `TASK_WORKER_CONCURRENCY` > 0 and database leases can be claimed.
- Extremely high `SIMULATION_TIME_SCALE` slowdowns are unusual (higher = faster
  simulation); mis-set worker leases are more common culprits.

## proxmoxer / TLS failures

- Use host port **8007** (gateway), not 8006, for TLS clients.
- Set `verify_ssl=False` **only** for the local self-signed cert.
- Inside Compose, target `tls-gateway:8443`.
- Seeded node name for `small` is `pve01`, not `pve1`.

## Terraform / Pulumi drift after reseed

Reseed replaces PostgreSQL guests; tool state files do not. Refresh, import, or
rebuild stacks after `make seed`.

## Hot-swap “did nothing”

- Catalog browse ≠ apply. Use **Apply as runtime** or
  `POST /ui/api/contract/apply?major=N`.
- Confirm with `/api2/json/version`.
- Remember apply is process-local; Compose restart restores `CONTRACT_SNAPSHOT`.

## Demo unload surprised you

`POST /ui/api/demo/unload` clears API-created state and loads `minimal`. Re-run
`make seed PROFILE=small` (or load demo again) to restore richer fixtures.
