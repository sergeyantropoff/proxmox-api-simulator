# Implementation plan

This plan turns the roadmap into independently testable increments. A stage is
complete only after formatting, linting, strict type checking, relevant tests,
documentation, and a focused commit succeed. Unsupported behavior remains
explicit throughout development.

## Quality gate used by every code stage

1. Run `make format`.
2. Run `make lint`.
3. Run `make typecheck`.
4. Run the narrow test target while developing, then `make test`.
5. Run `make ci` before committing a stage.
6. Update user-facing and architectural documentation.
7. Commit only the coherent stage changes.

Tests that need PostgreSQL use a dedicated database and are marked
`integration`. Network-dependent research and differential tests are never part
of the default offline unit suite.

## Milestone A: runnable foundation

### A1 — Repository and documentation

- Add architecture, contribution conventions, license, honest README, and this
  implementation plan.
- Define package layout without placeholder functions.
- Verify Markdown links, Mermaid syntax by inspection, and `git diff --check`.

Exit: design boundaries and the staged delivery policy are documented.

### A2 — Python project and test toolchain

- Add Python 3.13 metadata and bounded runtime/development dependency ranges.
- Configure Ruff formatting/linting, strict mypy, pytest-asyncio, coverage, and
  test markers.
- Add the complete Makefile command surface; commands for future features must
  fail with a clear message until implemented rather than silently succeed.
- Add package skeleton only where immediately used.

Exit: dependency installation is reproducible and a minimal unit test passes all
local static checks.

### A3 — Application foundation

- Implement typed Pydantic settings and an application factory.
- Add lifespan-owned resources and explicit dependency injection.
- Implement JSON logs, request-ID middleware, safe error boundary, `/health/live`,
  and `/health/ready`.
- Implement an asyncpg pool adapter with startup timeout, query timeout, readiness
  probe, and graceful close.
- Unit-test configuration and middleware; integration-test readiness against
  PostgreSQL.

Exit: the app starts, readiness reflects database state, shutdown closes all
resources, and standard errors do not leak internal details.

### A4 — Local containers

- Add multi-stage Dockerfile with locked-down non-root runtime and healthcheck.
- Add Docker Compose simulator/PostgreSQL services, named healthchecks, and
  persistent development volume.
- Add `.env.example`, `.dockerignore`, and documented HTTP quick start.
- Test image build, Compose startup, migrations, and both health endpoints.

Exit: `make ci` and the Stage 0 Docker acceptance path both pass.

## Milestone B: authoritative API contracts

### B1 — API Viewer research

- Inspect official HTML and its loaded static resources.
- Identify the real machine-readable artifact and version source without assuming
  an address.
- Record retrieval date, format, limitations, format-change risks, and offline
  fallback in `docs/api-viewer-research.md`.
- Store a small unmodified raw sample plus provenance and checksum.

Exit: the source is documented and the fixture can be parsed without network.

### B2 — Source parser

- Define an importer protocol and adapters for the discovered artifact and local
  files.
- Parse the raw fixture while retaining unknown fields and emitting structured
  warnings for recoverable source variations.
- Add malformed, truncated, and unexpected-field tests.

Exit: one real saved sample parses deterministically and offline.

### B3 — Normalized contract model

- Implement immutable Pydantic models for snapshots, paths, methods, parameters,
  schemas, permissions, formats, constraints, versions, and manifests.
- Implement canonical JSON serialization and SHA-256 for raw artifact,
  normalized snapshot, and each method.
- Preserve source metadata in `extra`; validate counts and references.
- Add determinism, round-trip, unknown-field, and property-based tests.

Exit: repeated normalization produces byte-identical canonical JSON and checksums.

### B4 — Secure asynchronous import CLI

- Add local and remote import commands using async `httpx`.
- Enforce HTTPS, official-domain allowlist, public address resolution, redirect and
  size limits, timeouts, and bounded retries.
- Store immutable raw revisions, normalized snapshots, and manifests atomically.
- Add `import`, `validate`, `list`, and `show`; optionally persist to PostgreSQL.
- Test SSRF defenses and idempotency without internet.

Exit: local and controlled remote imports produce verified, revision-safe assets.

### B5 — Semantic diff

- Compare paths, methods, parameters, schemas, permissions, defaults, constraints,
  and documentation independently.
- Classify changes and render stable text, JSON, Markdown, and HTML reports.
- Add CI exit policy for breaking changes and golden/property tests.

Exit: two snapshots produce deterministic, actionable reports in every format.

## Milestone C: contract-driven HTTP surface

### C1 — Dynamic route registry

- Load and verify the selected snapshot and compatibility profile at startup.
- Register `/api2/json` and `/api2/extjs` methods dynamically with collision
  detection and contract-derived schemas.
- Dispatch through a typed semantic-handler registry.
- Implement explicit `error`, `schema-default`, and `fixture` fallback modes;
  reserve guarded proxy/record modes for a later milestone.

Exit: OpenAPI builds without collisions and a fixture contract drives routes,
parameters, and methods without generated per-endpoint files.

### C2 — Compatible input and output

- Parse path, query, form, and supported JSON inputs according to contract rules.
- Render the `/api2/json` data envelope without coercing scalar or null data.
- Map validation, routing, authorization, domain, and database exceptions through
  centralized versioned Proxmox error templates.
- Add golden tests for the required validation and routing cases.

Exit: native FastAPI validation bodies never escape and unsupported semantics are
unambiguous.

### C3 — Compatibility accounting

- Track declared, schema-only, implemented, observed, and verified methods.
- Score each required compatibility level separately and by API group/version.
- Expose initial JSON/Markdown reports and simulator admin read endpoint.

Exit: claims in documentation are generated from test evidence.

## Milestone D: persistent simulation core

### D1 — Migrations and database primitives

- Implement an asynchronous, checksummed migration runner without an ORM.
- Create contract, cluster/resource, identity/ACL, task, scenario, and audit
  tables with constraints and indexes.
- Implement typed pool, transaction/savepoint context, error mapping, query
  timeout, affected-row checks, and safe transient retry policy.
- Test clean migration, repeat invocation, rollback, and constraint behavior.

Exit: a clean PostgreSQL database reaches the expected schema deterministically.

### D2 — Deterministic seed

- Implement idempotent `small` profile first using a seeded data generator and
  batch operations.
- Add logical-state snapshot assertions independent of generated UUID/timestamps.
- Add medium, large, HA, and failure profiles only after the vertical slice.

Exit: identical seeds yield identical logical small clusters.

### D3 — Authentication and authorization

- Implement password hashing, signed expiring tickets, cookies, CSRF tokens, and
  API-token hashing/parsing with log redaction.
- Implement realms, principals, roles, privileges, ACL propagation, and token
  privilege separation.
- Map contract permissions to centralized capability-driven evaluation.

Exit: authentication/CSRF/permission matrices pass without storing plaintext
secrets.

### D4 — Durable task engine

- Implement and property-test UPID formatting and parsing.
- Atomically create tasks and resource locks; claim with `SKIP LOCKED` leases.
- Implement progress, append-only logs/events, cancellation, recovery, bounded
  lifespan workers, and idempotency rules.
- Test two-worker exclusion, process restart recovery, lease expiry, and shutdown.

Exit: no acknowledged task is lost or executed concurrently by two workers.

### D5 — State machines and clocks

- Implement explicit VM states/transitions and PostgreSQL resource locks.
- Inject real, accelerated, and manual clocks into simulation services; reserve
  monotonic real time for worker leases and document the distinction.
- Add deterministic fault/scenario evaluation and concurrency tests.

Exit: valid asynchronous transitions finish predictably and incompatible
operations conflict without corrupting state.

## Milestone E: release 0.1.0 vertical slice

### E1 — Read endpoints and login

- Implement `/version`, `/access/ticket`, `/nodes`, `/nodes/{node}/status`, and
  `/cluster/resources` through semantic services.
- Verify headers, cookies, envelope, required fields, permissions, and errors
  against the selected contract/observations.

Exit: authenticated HTTPX and curl smoke flows pass from a seeded database.

### E2 — Basic QEMU and tasks

- Implement QEMU list, config, current status, start, and stop.
- Return persistent UPIDs for mutations and expose task list/status/log.
- Drive VM intermediate/final states through worker-executed transitions.
- Test duplicate and conflicting operations plus restart recovery.

Exit: a stopped seeded VM becomes running only after its successful task.

### E3 — Client and packaging acceptance

- Add proxmoxer smoke test and document supported client settings.
- Run the complete container acceptance sequence from a clean volume.
- Generate the first evidence-based compatibility report and limitation matrix.
- Tag the supported surface as release `0.1.0` after all gates pass.

Exit: every command and request in the first-result Definition of Done succeeds.

## Subsequent releases

- **0.2.0:** QEMU create/update/delete, tokens/complete ACLs, snapshots, clone, and
  migration.
- **0.3.0:** LXC, storage metadata/content operations, pools, and backups.
- **0.4.0:** administrative scenarios, fault injection, virtual-time controls, and
  large-cluster profiles.
- **0.5.0:** sanitized recorder, differential lab tests, HTML reports, and multiple
  verified PVE profiles.
- **1.0.0:** stable compatibility contract, published matrix, Kubernetes/Helm,
  client certification, migration policy, and security review.

Each later endpoint is delivered as a narrow vertical increment: imported
contract, handler, domain semantics, persistence, permissions, task behavior when
applicable, golden/compatibility evidence, and documentation are completed
together.

## Known delivery risks and mitigations

- **API Viewer format changes:** keep raw immutable artifacts, multiple adapters,
  parser warnings, and fixture-based offline tests.
- **Documentation differs from reality:** store declared and observed contracts
  separately and bind observations to exact versions.
- **Error text varies by release:** assert structural compatibility first and use
  exact golden text only when observed.
- **PostgreSQL concurrency complexity:** establish leases, locks, and transaction
  tests before exposing mutation endpoints.
- **False compatibility confidence:** default unsupported routes to errors and
  generate claims only from recorded tests.
- **Large scope:** never advance a partially passing stage; prefer a complete
  vertical slice over breadth.
