**Language / Язык:** [English](authentication.md) | [Русский](ru/authentication.md)

# Authentication

The simulator implements Proxmox-compatible ticket and API-token authentication
with ACL evaluation for non-root principals.

## Ticket login

```http
POST /api2/json/access/ticket
Content-Type: application/x-www-form-urlencoded

username=root@pam&password=secret
```

Successful responses include:

- `ticket` — also set as HttpOnly cookie `PVEAuthCookie` (SameSite=Strict)
- `CSRFPreventionToken` — required for ticket-authenticated mutations
- `username` and related identity fields

Tickets are HMAC-signed with `TICKET_SIGNING_KEY`, expire after two hours by
default, and tolerate a small amount of future clock skew.

### CSRF rules

| Request | Ticket session | API token |
|---|---|---|
| `GET` / `HEAD` / `OPTIONS` | Cookie (or ticket) enough | `Authorization` header |
| Other methods | Cookie **and** `CSRFPreventionToken` header | CSRF **not** required |

```bash
curl -X POST \
  -H "Cookie: PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  -d '...' \
  http://localhost:8006/api2/json/nodes/pve01/qemu/100/status/start
```

## API tokens

Header format:

```http
Authorization: PVEAPIToken=USER@REALM!TOKENID=SECRET
```

Secrets are stored only as scrypt hashes. Create and explicit regenerate return
the plaintext secret **once**; list and read never echo it. Deleting a token
invalidates it immediately.

Token privileges are the **intersection** of the token’s privileges and the
owning principal’s effective (direct + inherited) ACLs. A token cannot escalate
beyond its owner.

## Seeded development principals

Seeded for **every** profile — including `minimal` and after Web UI demo unload.
Unload shrinks guests/nodes/storages; lab principals and tokens are still
inserted by `apply_seed`:

| Principal | Password | Token | Notes |
|---|---|---|---|
| `root@pam` | `secret` | `automation` / `automation-secret` | Full access via ticket; token still constrained if privileges limited |
| `auditor@pve` | `auditor-secret` | `readonly` / `readonly-secret` | Inherited auditor ACL — reads OK, power ops denied |
| `operator@pve` | `operator@pve-password` | `operator` / `operator-secret` | VM audit/power on `/vms` |
| `storage@pve` | `storage@pve-password` | `storage` / `storage-secret` | Datastore scope on `/storage` |

These credentials are **lab-only**. Change or disable them before exposing any
network beyond your workstation.

## Root vs ACL

Root ticket sessions bypass normal ACL checks in the Proxmox-compatible way used
by this simulator. Separated API tokens remain constrained. Compatibility tests
assert privilege separation for auditor/operator/storage personas.

## Related paths

- Ticket: `/access/ticket`
- Users / groups / roles / ACL / realms / permissions
- Tokens: `/access/users/{userid}/token[/{tokenid}]`
- TFA and OpenID: durable local state; **no live IdP** calls

See domain guide [Access](domains/access.md).
