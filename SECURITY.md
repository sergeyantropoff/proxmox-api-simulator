**Language / Язык:** [English](SECURITY.md) | [Русский](docs/ru/security.md)

# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` (latest) | Yes — security reports accepted |
| older / untagged | Best-effort only |

## Threat model (read this first)

This repository is a **local / CI laboratory simulator**, not a hardened
multi-tenant public Proxmox deployment.

Default Compose and Helm values intentionally ship convenient lab secrets,
seeded passwords, open Web UI helper routes (`/ui/api/*`), and compatibility
endpoints (`/admin/compatibility*`). Treat network reachability as the trust
boundary.

**Do not** expose host port `8006` (or a public Ingress) to untrusted networks
without replacing every default secret and adding controls you own.

Full lab notes: [docs/security.md](docs/security.md) ·
[docs/ru/security.md](docs/ru/security.md).

## Reporting a vulnerability

Please **do not** open a public GitHub issue for sensitive reports.

Email the maintainer privately (account that owns the GitHub repository /
Docker Hub `inecs` namespace), or use GitHub
[ privately reported vulnerabilities](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
if enabled on the repository.

Include:

- Affected version / image tag (`inecs/proxmox-api-simulator:…`)
- Reproduction steps against a **local** lab (not third-party instances)
- Impact assessment (auth bypass, secret leak, RCE, etc.)

You should receive an acknowledgement within a few business days.

## Lab secrets that must be rotated outside toy labs

| Secret | Where |
|---|---|
| `TICKET_SIGNING_KEY` | Compose / Helm |
| PostgreSQL password | Compose / Helm |
| Seeded `root@pam` / API tokens | After `seed` |
| `docker/tls/server.key` | Checked-in self-signed material — never reuse outside local Compose |
