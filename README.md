# proxmox-api-simulator

Stateful asynchronous Proxmox VE API simulator for testing API clients and
infrastructure tooling without a real hypervisor cluster.

Release 0.1.0 provides a deliberately narrow, stateful vertical slice backed by
the authoritative imported PVE 9.2.3 contract. Compatibility claims and known
limits are recorded in [the 0.1.0 compatibility report](docs/compatibility-0.1.0.md).

The bundled PVE 9.2.3 declared contract contains 444 paths and 675 methods.
Implemented semantics currently include version, ticket login, node listing and
status, cluster resources, basic QEMU list/config/status/start/stop, and task
list/status/log, QEMU create/sync-update/async-update/delete, plus API-token
list/create/read/update/delete. Mutations require the ticket-bound CSRF header
and execute through PostgreSQL-leased workers; all other declared methods return
an explicit unsupported error.

QEMU create, asynchronous config update, and delete return durable UPIDs and use
the same PostgreSQL resource lock as lifecycle operations. Synchronous config
PUT uses optimistic versioning. Common fields and unknown version-dependent
parameters are retained in JSONB; duplicate VMIDs and overlapping operations
fail with 409.

## Development

Python 3.13 is required.

```bash
make install
make ci
```

Local services expose internal HTTP on port 8006 and a development-only HTTPS
gateway on port 8007. The checked-in certificate and key are disposable local
test credentials and must never be used in production:

```bash
cp .env.example .env
make docker-up
curl http://localhost:8006/health/live
curl http://localhost:8006/health/ready
make db-migrate
make seed
curl http://localhost:8006/api2/json/version
curl -X POST -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket
```

Unmodified proxmoxer 2.3 clients use the HTTPS gateway:

```python
from proxmoxer import ProxmoxAPI

proxmox = ProxmoxAPI(
    "localhost",
    port=8007,
    user="root@pam",
    password="secret",
    verify_ssl=False,  # local self-signed development certificate
)
print(proxmox.version.get())
print(proxmox.nodes("pve1").qemu.get())
```

The deterministic seed also provides hashed development API tokens. For token
authentication use proxmoxer `token_name="automation"` and
`token_value="automation-secret"` with user `root@pam`. The readonly
`auditor@pve!readonly` token proves privilege separation: authenticated reads
work, while QEMU power operations return 403. API-token requests do not require
CSRF; ticket-authenticated mutations still do. These are disposable local test
credentials only.

The permission acceptance matrix additionally seeds an audit-only user through
an inherited group ACL, a VM operator, and a storage-scoped user. Compatibility
tests verify root access, inherited `Sys.Audit`/`VM.Audit`, operator power
management, token privilege intersection, denial, and identical denial for an
existing and a nonexistent VM when the principal lacks `VM.Audit`.

Token lifecycle is available at
`/access/users/{userid}/token[/{tokenid}]`. A generated secret is returned only
by create or explicit regenerate; only its scrypt hash is stored. List/read never
return token values, and deletion immediately invalidates authentication.

Run the external-client smoke flow against the Compose network with
`PROXMOXER_HOST=tls-gateway`, `PROXMOXER_PORT=8443`, and pytest marker
`compatibility`. It covers login, reads, CSRF-protected mutation, and UPID task
completion.

Machine-readable evidence is served at `/admin/compatibility`; deterministic
Markdown and HTML variants use `/admin/compatibility.md` and
`/admin/compatibility.html`. Scores are separated across all 13 contract,
response, state, task, error, and permission dimensions.

Database migrations are ordered SQL files applied transactionally and recorded
with SHA-256 checksums. Re-running `make db-migrate` is safe; changing an already
applied migration is rejected instead of silently drifting the schema. Readiness
stays unavailable until the latest packaged migration is present; task workers
retry claims and recover automatically when migrations are applied after process
startup.
Seed profiles are deterministic and replace the previously seeded simulation
state atomically. `small` creates one node, two QEMU guests, one LXC, two
storages, an administrator, and completed task history. `medium` creates three
nodes, 50 QEMU guests, 20 LXC guests, shared/local storage and a pool;
`ha-demo` adds HA state, while `broken-storage` makes one storage unavailable.
`large` uses bounded asyncpg batch operations and is configurable through
`SEED_LARGE_NODES` and `SEED_LARGE_RESOURCES` (10,000 resources by default):

```bash
make seed PROFILE=small
make seed PROFILE=medium
make seed PROFILE=large
make seed PROFILE=ha-demo
make seed PROFILE=broken-storage
```

All stable simulation identifiers use UUIDv5. Migration 004 adds normalized
cluster, QEMU, LXC, storage/content, snapshot, backup, pool, identity,
observation and fault-rule tables while generic resources remain the current
0.1 compatibility boundary.

Contract artifacts can be validated and imported into immutable local revisions:

```bash
.venv/bin/proxmox-api-contract validate tests/fixtures/api-viewer/pve-9.2.3-version.json
.venv/bin/proxmox-api-contract --store contracts import \
  --file tests/fixtures/api-viewer/pve-9.2.3-version.json --version 9.2.3
.venv/bin/proxmox-api-contract --store contracts list
```

Remote imports accept HTTPS URLs on the explicit official-domain allowlist and
reject private address resolution, unsafe redirects, oversized responses, and
unbounded retries. Imported revisions are addressed by their normalized
snapshot checksum and are never overwritten.

Normalized snapshots can be compared in text, JSON, Markdown, or HTML. The diff
command exits with status 1 when it finds a breaking change, making it suitable
for CI policy checks:

```bash
.venv/bin/proxmox-api-contract diff old-snapshot.json new-snapshot.json \
  --format markdown
```

Set `CONTRACT_SNAPSHOT` to a normalized snapshot file to register its methods
under both `/api2/json` and `/api2/extjs`. Routes without a semantic handler
return an explicit 501 by default. `CONTRACT_FALLBACK=schema-default` enables
schema-only exploration; `fixture` serves only values explicitly embedded in a
method contract.

See [the architecture](docs/architecture.md) for component boundaries and
durability decisions. Commands for not-yet-implemented milestones intentionally
return a non-zero status instead of pretending to succeed.
