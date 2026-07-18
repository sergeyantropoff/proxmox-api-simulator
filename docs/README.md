**Language / Язык:** [English](README.md) | [Русский](ru/README.md)

# Documentation

Guides for the Proxmox VE API simulator. Switch language with the header on each
page. Russian mirrors live under [`ru/`](ru/README.md).

![Web UI main](images/web-ui-main.png)

| Guide | Description |
|---|---|
| [Getting started](getting-started.md) | First successful lab session |
| [Configuration](configuration.md) | Environment variables and Compose |
| [Authentication](authentication.md) | Tickets, CSRF, API tokens, ACLs |
| [API versions](api-versions.md) | Contracts 6–9 and hot-swap |
| [Clients & examples](clients.md) | Python, Go, Java, Perl, Ansible, Terraform, Pulumi |
| [Seed profiles](seed-profiles.md) | Deterministic cluster fixtures |
| [API surface](api-surface.md) | Routing, handlers, fallbacks |
| [Domains](domains/README.md) | QEMU, LXC, storage, HA, SDN, … |
| [Web UI](web-ui.md) | Interactive console and catalogs |
| [Operations](operations.md) | Migrate, reseed, upgrade, Hub publish |
| [Docker Hub overview](docker-hub-overview.md) | Paste-ready Hub repository description |
| [Kubernetes / Helm](kubernetes.md) | Hub image + Ingress + Let's Encrypt |
| [Security](security.md) | Lab threat model and credentials |
| [Observability](observability.md) | Health endpoints and logging |
| [Troubleshooting](troubleshooting.md) | Common failure modes |
| [FAQ](faq.md) | Short answers |
| [Architecture](architecture.md) | Component boundaries |
| [Compatibility](compatibility.md) | Evidence model and release matrix |
| [Testing](testing.md) | Suites layout, Make targets, latest results |

Runnable cookbooks: [`examples/`](../examples/README.md).
Integration suites: [`pulumi-tests/`](../pulumi-tests/README.md).
Test map and latest pass notes: [Testing](testing.md).

## See also

- [Web UI](web-ui.md) — interactive console, catalogs, DATA panel, and screenshots
