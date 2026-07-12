# Original prompt gap plan

This is the executable completion checklist for the original 1,985-line project
brief. It starts after release 0.1.0 and supersedes the short “subsequent
releases” list as the source of delivery status. A box is closed only when code,
tests, documentation, container acceptance, and a focused commit exist.

Status at audit time: 0.1.0 is operational, but the overall project is not done.

## G1 — measurable compatibility evidence

- [x] Model all 13 requested compatibility dimensions independently: route and
  method, inputs, requiredness, types and constraints, HTTP status, JSON shape,
  response field types, required response fields, headers and cookies, state
  semantics, long-task behavior, errors and prohibitions, permissions.
- [x] Store test-derived evidence per method/profile instead of deriving strong
  claims merely from handler presence.
- [x] Generate deterministic JSON, Markdown, and HTML reports with totals and
  breakdowns by API group and PVE version.
- [x] Mark declared, schema-only, implemented, observed, partially compatible,
  incompatible, and regression states without claiming unsupported semantics.

Exit: a test fixture can prove different scores for every dimension and the
live admin report renders the same evidence deterministically.

## G2 — persistence model and deterministic datasets

- [ ] Expand normalized tables/repositories for storages and contents, QEMU,
  LXC, disks, NICs, snapshots, backups, pools, users/groups/roles/ACLs/tokens and
  observed contracts. Preserve version, metadata, timestamps, and cluster-wide
  VMID uniqueness.
- [x] Make migration readiness explicit so workers cannot become permanently
  unhealthy before schema creation.
- [x] Match the required `small` profile (one node, two QEMU, one LXC, two
  storages, administrator, completed tasks).
- [x] Implement deterministic `medium`, configurable batch-insert `large`,
  `ha-demo`, and `broken-storage` profiles.

Exit: clean migration plus every seed profile has a stable logical snapshot;
large seeding proves bounded batch operations rather than row-at-a-time inserts.

## G3 — authentication and authorization surface

- [x] Expose API-token lifecycle and authenticate
  `PVEAPIToken=USER@REALM!TOKENID=SECRET` without CSRF.
- [x] Complete pam, pve, and test realm behavior, ticket skew/expiry and
  credential redaction.
- [x] Wire users, groups, roles, ACL propagation, route-derived permissions and
  token privilege separation into every semantic handler.
- [x] Test root, audit-only, VM operator, storage user, separated token,
  inheritance, denial, and existence-hiding behavior.

Exit: the complete credential/permission matrix passes through HTTP and no
plaintext password, ticket, CSRF token, or token secret reaches storage/logs.

## G4 — QEMU 0.2 verticals

- [ ] Create, update, delete, shutdown, reboot, reset, suspend and resume.
- [ ] Snapshots and rollback, clone, local/remote migration, resize and move
  disk, selected agent endpoints, pending/status data.
- [ ] Persist normalized CPU/memory/common fields plus unknown PVE parameters in
  JSONB; simulate usage, uptime, PID, IO/network, lock, template, QMP, HA and
  guest-agent availability.
- [ ] Cover concurrent start/delete, migrate/snapshot, optimistic conflict,
  idempotency and restart recovery.

Exit: each operation is a complete contract/auth/permission/persistence/task/
state/error/test vertical and release 0.2.0 has a generated limitation matrix.

## G5 — LXC, storage, pools, backup and cluster 0.3

- [ ] LXC create/config/lifecycle/clone/migrate/snapshot/resize/delete.
- [ ] Storage list/status/content metadata, allocation/free, upload metadata,
  ISO/template/backup listing and content deletion without large default blobs.
- [ ] Pools and membership, backup metadata/tasks, cluster status/nextid/options/
  tasks/replication, and initial HA model/status.

Exit: release 0.3.0 passes client-level flows for every listed resource family.

## G6 — simulator administration, faults and virtual time 0.4

- [ ] Protected, disableable `/_simulator` API for state, reset, scenarios,
  faults, compatibility and manual clock advancement.
- [ ] Deterministic rules filtered by route, method, principal, node, VMID, call
  count, probability, time interval and scenario.
- [ ] Implement the specified node/storage/task/permission/migration/snapshot/
  backup/HTTP/malformed/agent/lock/quorum/HA failures.
- [ ] Ensure simulation services use injected real, accelerated or manual clocks;
  only lease internals use real monotonic time.

Exit: seeded scenario tests reproduce the same failures and durations across
runs; admin endpoints cannot overlap or weaken the PVE API boundary.

## G7 — safe recorder and differential laboratory 0.5

- [ ] Opt-in async passthrough/record fallbacks with official-lab allowlist,
  production denylist, verified TLS, read-only default and explicit mutation
  authorization.
- [ ] Sanitize credentials, cookies, tickets, CSRF, tokens, people, hosts and IPs
  before fixtures can be persisted.
- [ ] Record request/response/latency/version/time/scenario metadata.
- [ ] Run identical lab/simulator requests using declarative normalization for
  timestamps, UPIDs, PIDs, tokens, node values, uptime and resource usage.
- [ ] Produce JSON/Markdown/HTML reports with compatibility classes, regressions,
  groups and versions.

Exit: secret-scanning fixtures and offline replay tests pass; normal startup has
no dependency on or route to a real Proxmox.

## G8 — profiles, observability and operational packaging

- [ ] Central `CompatibilityCapabilities` profiles for pve-8.4, pve-9.0,
  pve-9.2 and custom; no scattered version-prefix conditions.
- [ ] Prometheus metrics requested by the brief, with bounded-cardinality labels,
  plus optional OpenTelemetry tracing and optional Compose Prometheus/Grafana.
- [ ] Enrich safe structured logs with route template, principal, task/resource
  context and stable error code.
- [ ] Add Docker labels/SBOM-friendly metadata and verify read-only/non-root
  runtime, signals, one uvicorn process and multi-replica task leasing.
- [ ] Add Helm/Kubernetes Deployment, Service, ConfigMap, Secret, probes, PDB,
  NetworkPolicy, hardened security context, resources, topology spread, separate
  migration/seed Jobs and external PostgreSQL production configuration.

Exit: observability tests reject high-cardinality labels; chart lint/render and
multi-replica acceptance pass.

## G9 — client certification, security and 1.0 governance

- [ ] Add contract coverage for every imported route and critical-module
  coverage of at least 90% while maintaining project coverage at least 80%.
- [ ] Certify documented versions of proxmoxer, HTTPX, Terraform provider and
  Ansible modules only for the surfaces their flows exercise.
- [ ] Publish stable compatibility/migration policy and run dependency,
  container, recorder, secret-handling and threat-model review.
- [ ] Expand README with architecture, version/profile choice, every seed,
  scenarios, reports, recorder security, Kubernetes, commands and roadmap.

Exit: release 1.0.0 is reproducible from a clean checkout and all published
claims point to immutable machine-readable evidence.

## Global gate for every G-stage

Run formatting, Ruff, strict mypy, unit/integration/contract/compatibility tests,
coverage, `git diff --check`, relevant clean-container acceptance, documentation,
and a focused commit. No `pass`, TODO, `NotImplementedError`, sync network/DB IO,
`time.sleep`, plaintext secrets, silent error swallowing, or unsupported
compatibility claims may be introduced.
