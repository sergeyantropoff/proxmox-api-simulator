**Language / Язык:** [English](troubleshooting.md) | [Русский](ru/troubleshooting.md)

# Troubleshooting

## Ready stays unavailable

1. Confirm Postgres: `make logs` / Compose health.
2. Run `make db-migrate`.
3. Hit `/health/ready` again.

Workers may retry until migrations catch up after a late migrate.

## Unexpected HTTP 501

Declared methods on majors **6–9** should have handlers. If you see 501:

- Confirm the active runtime (`/api2/json/version` and Web UI runtime label).
- Confirm you are calling the path/verb exactly as declared for that major.
- Check `CONTRACT_FALLBACK` is not masking a different issue with fixture mode.
- Report a regression — full registry coverage is expected.

## 401 / 403

- Ticket expired or cookie not sent.
- Mutation missing `CSRFPreventionToken` on a ticket session.
- API token malformed (`PVEAPIToken=user@realm!id=secret`).
- ACL denial (try `auditor@pve` vs `root@pam` to compare).
- In the Web UI, HTTP 401 clears the local session and shows **Guest** in the
  header; sign in again from Environment.

## Ingress returns branded HTML 404 / nginx 405 instead of JSON

The simulator answers API errors as JSON (`data` / `message` / `errors`). If
you see a site HTML “page not found” or plain nginx **405** page, the
**Ingress / reverse proxy** replaced the upstream body (often via
`custom-http-errors` on the ingress-nginx controller).

Fix on the Ingress for this host (see
`helm/proxmox-api-simulator/values-ingress-example.yaml`):

```yaml
annotations:
  nginx.ingress.kubernetes.io/proxy-intercept-errors: "false"
  nginx.ingress.kubernetes.io/custom-http-errors: "502,503"
```

Then re-check with `Accept: application/json`. A missing node should look like:

```json
{"data": null, "message": "No such node ('pve01')", "errors": {"node": "No such node ('pve01')"}}
```

Seeded node names: profile `small` → `pve01`; `medium` / `ha-demo` → `pve1`…

### Correct authenticated POST (Proxmox-style)

Use form-urlencoded body, ticket cookie, and CSRF header (not bare JSON POST):

```bash
# after POST /api2/json/access/ticket → ticket + CSRFPreventionToken
curl -sk -X POST "https://HOST/api2/json/nodes/pve01/ceph/osd" \
  -H "CSRFPreventionToken: $CSRF" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -b "PVEAuthCookie=$TICKET" \
  --data-urlencode "dev=/dev/sdb"
```

## Task never finishes

- Inspect `/nodes/{node}/tasks/{upid}/status` and `/log`.
- Check worker logs (`make logs`).
- Verify `TASK_WORKER_CONCURRENCY` > 0 and database leases can be claimed.
- Extremely high `SIMULATION_TIME_SCALE` slowdowns are unusual (higher = faster
  simulation); mis-set worker leases are more common culprits.

## proxmoxer / TLS failures

- Compose default is plain **HTTP `:8006`**. proxmoxer is HTTPS-only — enable
  `docker compose --profile tls` and use `https://localhost:8443/` with
  `verify_ssl=False` for the lab self-signed cert.
- Inside Compose, target `tls-gateway:8443` when the `tls` profile is on.
- Host `:8007` is **not** used by this stack (on hardware it is usually PBS).
- On Kubernetes, use your Ingress HTTPS hostname (cert-manager).
- Seeded node name for `small` is `pve01`, not `pve1`.
- Profiles `medium` / `ha-demo` use **`pve1` / `pve2` / `pve3`**.
- Port map: [Ports and TLS](configuration.md#ports-and-tls).

## Terraform / Pulumi drift after reseed

Reseed replaces PostgreSQL guests; tool state files do not. Refresh, import, or
rebuild stacks after `make seed`.

## Hot-swap “did nothing”

- Catalog browse ≠ apply. Use **Apply as runtime** or
  `POST /ui/api/contract/apply?major=N`.
- Confirm with `/api2/json/version`.
- Remember apply is process-local; Compose restart restores `CONTRACT_SNAPSHOT`.

## Demo unload surprised you

`POST /ui/api/demo/unload` clears API-created state and loads `minimal`. Re-run
`make seed PROFILE=small` (or load demo again) to restore richer fixtures.
