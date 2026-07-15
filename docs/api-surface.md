# API surface

## Request path

1. Middleware assigns or forwards a request ID.
2. The active contract snapshot selects declared paths and schemas.
3. Authentication resolves a principal (ticket or API token).
4. ACL / privilege checks run before revealing or mutating resources.
5. Path, query, and body inputs are validated against contract-derived schemas.
6. A semantic handler executes against PostgreSQL-backed state.
7. Long operations create a durable task (+ lock when required) and return a UPID.
8. Responses use the Proxmox envelope under `/api2/json` or `/api2/extjs`.

## Dual renderers

Every contract method is registered under both:

- `/api2/json/...`
- `/api2/extjs/...`

Clients and the Web UI typically use the JSON renderer.

## Handlers vs contracts

- **Declared** — present in the imported API Viewer snapshot for the major.
- **Implemented** — a semantic handler is registered for that verb + path.
- Majors **6–9** have **100%** implemented coverage for declared methods.

Handlers must persist create/update/delete effects. Empty no-op mutations are
not part of the product contract. See the workspace durable-simulator rule.

## OpenAPI and exploration

- Interactive FastAPI docs: `/docs`
- Web UI method inspector: `/` → catalog → method
- UI APIs: `/ui/api/catalog`, `/ui/api/method`, `/ui/api/compatibility`

## Compatibility endpoints

| Path | Format |
|---|---|
| `/admin/compatibility` | JSON |
| `/admin/compatibility.md` | Markdown |
| `/admin/compatibility.html` | HTML |

Reports follow the active runtime contract after hot-swap.

## Tasks (UPID)

Async work (guest power, clone, migrate, many deletes, backups, …) returns a
UPID. Poll:

```text
GET /nodes/{node}/tasks/{upid}/status
GET /nodes/{node}/tasks/{upid}/log
```

Workers claim tasks with `FOR UPDATE SKIP LOCKED`, renew leases, and recover
after process restart. HTTP 200 on the mutation request means “accepted”, not
“guest already in final state”.

## Errors (common)

| Status | Typical cause |
|---|---|
| 401 | Missing/invalid ticket or token |
| 403 | ACL denial or missing CSRF on ticket mutation |
| 409 | VMID conflict, illegal state transition, lock contention |
| 501 | Handler missing (should not appear for declared methods on 6–9) |
| 503 | Readiness failure (database / migrations) |

## Importing contracts

```bash
make shell
proxmox-api-contract validate path/to/source.json
proxmox-api-contract --store contracts import --file path/to/source.json --version 9.2.3
proxmox-api-contract --store contracts list
proxmox-api-contract diff old.json new.json --format markdown
```

Remote import enforces HTTPS, an official-host allowlist, size/redirect/timeout
limits, and checksummed immutable revisions.
