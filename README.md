# proxmox-api-simulator

Stateful asynchronous Proxmox VE API simulator for testing API clients and
infrastructure tooling without a real hypervisor cluster.

The runnable foundation and authoritative contract toolchain are implemented.
Imported methods can be registered dynamically, but no stateful Proxmox method
is claimed as compatible yet; the vertical slice is tracked in
[the implementation plan](docs/implementation-plan.md).

## Development

Python 3.13 is required.

```bash
make install
make ci
```

Local services use plain HTTP at this stage:

```bash
cp .env.example .env
make docker-up
curl http://localhost:8006/health/live
curl http://localhost:8006/health/ready
make db-migrate
```

Database migrations are ordered SQL files applied transactionally and recorded
with SHA-256 checksums. Re-running `make db-migrate` is safe; changing an already
applied migration is rejected instead of silently drifting the schema.

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
