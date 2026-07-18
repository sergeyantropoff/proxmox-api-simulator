**Language / Язык:** [English](compatibility-0.1.0.md) | [Русский](ru/compatibility-0.1.0.md)

# Compatibility report — 0.1.0

This report records evidence for simulator release 0.1.0 against the bundled
Proxmox VE API contracts (majors 6–9). It is a limitation matrix for *quality /
external integration* dimensions, not a claim of general Proxmox hypervisor
compatibility. Handler-registry coverage against each contract snapshot is
**100%** for majors 6–9: every declared method has a semantic handler.

For the user-facing overview see [compatibility.md](compatibility.md). Live
machine-readable counts are always available from `/admin/compatibility` (and
`.md` / `.html`). Prefer that endpoint when the simulator is running.

## Summary (PVE 9.2.3 primary contract)

| Level | Methods | Contract share | Evidence |
|---|---:|---:|---|
| Declared and dynamically routed | 675 | 100% | Bundled API Viewer snapshot |
| Stateful semantics implemented | **675** | **100%** | Handler registry ∩ contract |
| Observed / verified surface ledger | **675** | **100%** | `evidence/pve-9.2.3.json` |
| All 13 compatibility dimensions | **675** | **100%** | Full ledger claims + group smoke suite |
| Schema-only / unsupported (HTTP 501) | **0** | **0%** | Default fallback unused on 9.2.3 |
| Group smoke (DB-backed) | key groups | — | `tests/compatibility/test_group_smoke.py` |
| proxmoxer smoke exercised | 9 | 1.33% | Unmodified proxmoxer 2.3 compatibility test |

The smoke set is `POST /access/ticket`, `GET /version`, `GET /nodes`,
`GET /nodes/{node}/qemu`, `GET /nodes/{node}/qemu/{vmid}/status/current`, one of
the two state mutations (`start` or `stop`), and repeated
`GET /nodes/{node}/tasks/{upid}/status`. Both mutations have independent API and
worker tests; a single smoke run chooses the transition valid for current state.

## Coverage by Proxmox major

| Version | Declared | Implemented | Verified | Coverage |
|---|---:|---:|---:|---:|
| 6.4-15 | 504 | 504 | 504 | 100.00% |
| 7.4-16 | 540 | 540 | 540 | 100.00% |
| 8.4.5 | 605 | 605 | 605 | 100.00% |
| 9.2.3 | 675 | 675 | 675 | 100.00% |

**Verified** here means every declared method appears in the per-major surface
ledger (`evidence/pve-{version}.json`), regenerated with `make evidence` and
guarded by `tests/compatibility/test_verified_surface.py`. Hot-swap
(`POST /ui/api/contract/apply?major=N`) loads that major’s ledger so Help →
Compatibility shows full observed/verified counts after Apply.

Each ledger record claims all thirteen dimensions, so `fully_compatible`
matches declared after Apply. Group smoke
(`tests/compatibility/test_group_smoke.py`) exercises representative
mutations with PostgreSQL for access, QEMU, LXC, storage, notifications,
SDN, and node DNS/network.

Older majors reuse the 9.2.3 handlers plus `app/handlers/legacy_aliases.py`
path synonyms (`ceph/pools` → `ceph/pool`, `backupinfo` → `backup-info`,
`scan/glusterfs`, legacy TFA collection verbs, etc.).


## Implemented surface (high level)

- **Core**: version, ticket login, node list/status/index, cluster resources.
- **Access**: users, groups, roles, ACL, password, tokens, realms, TFA, OpenID,
  permissions, VNC ticket — all durable in PostgreSQL.
- **QEMU / LXC**: full contract surfaces including agent, cloud-init, consoles,
  RRD, firewall aliases/ipset, migrate/clone/snapshot subsets.
- **Storage / pools / backup / HA / firewall / Ceph / SDN**: durable handlers
  (`clusters.metadata`, `nodes.metadata.ops`, normalized tables).
- **Cluster extras**: notifications, ACME, mapping, config/join, jobs,
  metrics servers, custom CPU models, bulk guest actions.
- **Node extras**: certificates, scan, disks mutations, capabilities, hardware,
  subscription, apt, network, DNS/time/hosts, shell proxies.
- **Tasks**: leased workers, status, append-only logs.
- **Auth**: ticket + CSRF for mutations; hashed API tokens.

## Persistence principle

Every create/update/delete path writes to PostgreSQL (tables and/or jsonb
metadata). Secrets may be stored but must not be echoed on GET. User-facing
“not supported in the emulator” errors are forbidden — see
`.cursor/rules/durable-simulator.mdc`.

## Known limitations

| Area | Current behavior |
|---|---|
| External systems | LDAP/OpenID/ACME/Ceph do not contact real remotes; state is simulated |
| Realm sync / OpenID login | Durable stamps / pending state / tickets; no live IdP |
| Observation parity | Contract/tests exist; sanitized real-PVE observation corpus is limited |
| TLS | Local nginx gateway with a checked-in self-signed development key only |
| Client certification | proxmoxer 2.3 smoke; Terraform and other clients are not certified |
| Deep HTTP coverage | Not every one of 675 methods is exercised end-to-end; group smokes cover representative paths per domain |

Full registry coverage means HTTP 501 “handler pending” should no longer appear
for methods declared in the active contract after Apply. Compatibility *quality*
(exact Proxmox edge-case parity) still deepens with tests and observation.

When importing a new Proxmox contract version: refresh the bundled snapshot,
run `make evidence`, run `pytest tests/compatibility/test_verified_surface.py`,
and commit the updated `evidence/pve-*.json` ledgers.

The report also exposes the 13 independent compatibility dimensions required by
the project brief. Surface ledgers live in `evidence/pve-{version}.json`; the
historical deep overlay `evidence/pve-9.2.3-0.1.0.json` is merged into the 9.2.3
canon on regenerate. Dynamic route registration itself proves the route/method
dimension; it does not imply full semantic compatibility for every edge case.
