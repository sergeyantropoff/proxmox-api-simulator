# API versions (PVE 6–9)

The simulator ships authoritative imported contracts for four Proxmox VE majors.
Handler registry coverage is **100% verified** for each:

| Major | Source version | Declared methods | Handler coverage |
|---|---|---:|---:|
| 6 | 6.4-15 | 504 | 100% |
| 7 | 7.4-16 | 540 | 100% |
| 8 | 8.4.5 | 605 | 100% |
| 9 | 9.2.3 | 675 | 100% |

Older majors reuse the current semantic handlers plus path synonyms registered
in `app/handlers/legacy_aliases.py` (for example historical Ceph and backup path
spellings).

## Cold start

Set `CONTRACT_SNAPSHOT` to a normalized snapshot path. Docker Compose pins the
bundled PVE **9.2.3** revision by default.

`GET /api2/json/version` reports fields derived from the **active** snapshot’s
`source_version`.

## Hot-swap (runtime)

Browse any major in the Web UI catalog, then **Apply as runtime**, or call:

```http
POST /ui/api/contract/apply?major=7
```

Effects:

- In-memory `/api2/json` and `/api2/extjs` routes are replaced under an
  application lock.
- `/version`, OpenAPI, implementation metadata, and compatibility state refresh
  for the new major.
- The change is **process-local** and **not persisted**.
- Restart restores `CONTRACT_SNAPSHOT`.

Catalog browse (`GET /ui/api/catalog?major=N`) does **not** by itself change the
runtime; only apply does.

### Client guidance

- Pin the major explicitly in CI (cold-start env **or** apply + assert
  `/version` before the suite).
- Mid-flight hot-swap can invalidate in-progress client assumptions about
  schemas and paths — avoid during long Terraform/Ansible runs unless the run
  owns the switch.
- After apply, re-check `/admin/compatibility` for the active runtime.

## Fallback modes

`CONTRACT_FALLBACK` controls undeclared-handler behaviour:

| Value | Behaviour |
|---|---|
| `error` (default) | HTTP 501 with an explicit pending-handler style message |
| `schema-default` | Synthesize a return value from the contract schema |
| `fixture` | Return only fixture data embedded in the method contract |

With full handler coverage on the active contract, declared methods should not
hit the fallback. Keep `error` so regressions remain visible.

## Evidence vs registry

**Registry coverage** means every declared method has a registered semantic
handler (no systematic 501 for that contract).

**Verified** in this project’s sense means the majors are exercised through the
compatibility and automated suites for handler presence across 6–9. Multi-
dimension evidence JSON can still expand over time for deeper edge-case claims;
prefer live `/admin/compatibility` when the process is running.

See [Compatibility](compatibility.md).
