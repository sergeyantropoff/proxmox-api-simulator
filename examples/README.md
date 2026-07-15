# Runnable client cookbooks

Companion code for [docs/clients.md](../docs/clients.md).

## Prerequisites

```bash
make up
make seed PROFILE=small
```

## Layout

| Path | Stack |
|---|---|
| `python/` | proxmoxer + requests |
| `go/` | Go stdlib |
| `java/` | Java 11+ HttpClient |
| `perl/` | HTTP::Tiny |
| `ansible/` | ansible-playbook |
| `terraform/` | Terraform + Proxmox provider |
| `pulumi/` | Pulumi (Python) |

Default node: **`pve01`**. Default token:
`root@pam!automation=automation-secret`.

Guides: [docs/examples/](../docs/examples/overview.md).
