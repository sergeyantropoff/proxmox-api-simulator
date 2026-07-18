**Language / Язык:** [English](security.md) | [Русский](ru/security.md)

# Security

Repository policy and reporting: [SECURITY.md](../SECURITY.md).

## Lab threat model

This project is a **local / CI laboratory simulator**. It is not hardened as a
multi-tenant public Proxmox service. Default credentials, UI demo controls, and
compatibility endpoints are convenient for development and intentionally open
in the default Compose stack.

Do not expose port `8006` to untrusted networks without additional controls you
supply yourself. Host `:8006` is plain HTTP in Compose (real PVE uses HTTPS on
that port). Host `:8007` is **not** used by this stack (on hardware it is
typically PBS). See [Ports and TLS](configuration.md#ports-and-tls).

## Credentials and secrets

- Passwords and API-token secrets are stored as scrypt hashes.
- Ticket values are HMAC-signed and short-lived.
- CSRF binds mutations to ticket sessions.
- Logs redact recognized ticket, password, and token representations.
- Create/regenerate token responses show the secret once; GET never echoes it.

Change `TICKET_SIGNING_KEY` for any shared lab. Replace seeded passwords and
tokens before demoing to others.

## TLS materials

`docker/tls/` contains a checked-in self-signed certificate for the optional
Compose TLS gateway (`--profile tls` on `:8443`). It exists so unmodified TLS
clients (e.g. proxmoxer) can connect when that profile is enabled. **Never**
reuse these files in production.

## Simulator administration

There is currently **no** separately authenticated `/_simulator` control plane.
Web UI helper routes under `/ui/api/*` and `/admin/compatibility*` are available
whenever the process is reachable. Treat network exposure as the trust
boundary.

## Simulated remotes

LDAP sync stamps, OpenID pending state, ACME, and Ceph endpoints persist local
simulator state only. They do not open real connections to external IdPs or
clusters. Do not rely on the simulator for testing live credential exfiltration
defenses against real providers.
