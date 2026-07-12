# proxmox-api-simulator

Stateful asynchronous Proxmox VE API simulator for testing API clients and
infrastructure tooling without a real hypervisor cluster.

The project is in its foundation stage. Only liveness and PostgreSQL-backed
readiness endpoints exist. No Proxmox endpoint is claimed as compatible yet; the
official contract importer and stateful vertical slice are tracked in
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
```

See [the architecture](docs/architecture.md) for component boundaries and
durability decisions. Commands for not-yet-implemented milestones intentionally
return a non-zero status instead of pretending to succeed.

