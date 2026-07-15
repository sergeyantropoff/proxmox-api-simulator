# Web UI

Open [http://localhost:8006/](http://localhost:8006/) after `make up`.

The UI is a laboratory console for the simulator — not a full Proxmox VE
management interface. It supports light and dark themes, PVE majors **6–9**,
request/response editing, history, and runtime contract apply.

## Screenshots

Light theme — `GET /cluster/resources` on PVE 9.2.3:

![Web UI light theme](images/web-ui-light.png)

Dark theme — same console with theme toggle:

![Web UI dark theme](images/web-ui-dark.png)

## Features

- Endpoint tree and method selector driven by the selected catalog major
- Contract-derived parameters and example payloads
- Request editor, response viewer, and history
- Password login with cookie + CSRF handling
- Environment summary (runtime version, nodes, guests, storage)
- Curl / request previews
- PVE **6–9** API catalog with implementation coverage
- **Apply as runtime** hot-swap for the active contract
- Compatibility and readiness views
- Demo-cluster load / unload / refresh
- Link to OpenAPI at `/docs`

## Backend helpers

| Method | Path | Purpose |
|---|---|---|
| GET | `/ui/api/versions` | Catalog majors vs runtime |
| GET | `/ui/api/catalog?major=N` | Catalog for major 6–9 |
| GET | `/ui/api/method?...` | Single method metadata |
| GET | `/ui/api/compatibility?major=N` | Coverage payload |
| POST | `/ui/api/contract/apply?major=N` | Hot-swap runtime contract |
| GET | `/ui/api/demo/state` | Demo dataset state |
| POST | `/ui/api/demo/load` | Load `demo-cluster` |
| POST | `/ui/api/demo/unload` | Unload → `minimal` |

## Version workflow

1. Pick major **6 / 7 / 8 / 9** in the catalog.
2. Inspect methods and coverage.
3. **Apply as runtime** when you want live `/api2/*` routes to match that major.
4. Confirm with `/api2/json/version` and `/admin/compatibility`.

Hot-swap is memory-only; restart restores `CONTRACT_SNAPSHOT`. Details:
[API versions](api-versions.md).

## Security note

UI and demo endpoints are intended for local development. They are not gated by
a separate admin token in the current build. Do not expose the simulator port to
untrusted networks.
