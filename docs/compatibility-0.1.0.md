# Compatibility report — 0.1.0

This report records evidence for simulator release 0.1.0 against the bundled
Proxmox VE 9.2.3 API contract. It is a limitation matrix, not a claim of general
Proxmox compatibility.

## Summary

| Level | Methods | Contract share | Evidence |
|---|---:|---:|---|
| Declared and dynamically routed | 675 | 100% | Imported immutable API Viewer artifact |
| Stateful semantics implemented on current main | 27 | 4.00% | Handler registry and unit/integration tests |
| Schema-only or explicitly unsupported | 648 | 96.00% | Default 501 fallback |
| proxmoxer smoke exercised | 9 | 1.33% | Unmodified proxmoxer 2.3 compatibility test |

The smoke set is `POST /access/ticket`, `GET /version`, `GET /nodes`,
`GET /nodes/{node}/qemu`, `GET /nodes/{node}/qemu/{vmid}/status/current`, one of
the two state mutations (`start` or `stop`), and repeated
`GET /nodes/{node}/tasks/{upid}/status`. Both mutations have independent API and
worker tests; a single smoke run chooses the transition valid for current state.

## Implemented surface

- Core: version, ticket login, node list/status, and cluster resources.
- QEMU: list, configuration, current status, start, and stop.
- Tasks: node task list, status, and append-only log.
- Authentication: ticket cookie and ticket-bound CSRF validation for mutations,
  plus hashed API-token authentication without CSRF and token privilege
  separation at the contract-derived ACL boundary.
- Persistence: PostgreSQL resources, durable leased tasks, and deterministic
  `small` seed data.

## Known limitations

| Area | 0.1.0 behavior |
|---|---|
| Other imported endpoints | Registered, but return explicit unsupported errors |
| API tokens and broad ACL administration | Primitives exist; public management surface is incomplete |
| QEMU lifecycle | No create, update, delete, snapshots, clone, or migration |
| LXC, storage, pools, backup, HA | Contract-only; no stateful semantics yet |
| Observation parity | Responses are contract-tested, but no sanitized real-PVE observation corpus exists |
| TLS | Local nginx gateway with a checked-in self-signed development key only |
| Client certification | proxmoxer 2.3 smoke only; Terraform and other clients are not certified |

The live `/admin/compatibility` endpoint is the machine-readable source for
declared and implemented counts. Unsupported methods remain failures by default
so the simulator cannot silently overstate compatibility.

The report also exposes the 13 independent compatibility dimensions required by
the project brief. Evidence is loaded from the immutable
`evidence/pve-9.2.3-0.1.0.json` manifest, where every method/dimension claim cites
the tests that support it. Dynamic route registration itself proves only the
route/method dimension; it does not imply semantic compatibility. Markdown and
HTML renderings are available at `/admin/compatibility.md` and
`/admin/compatibility.html`.
