**Language / Язык:** [English](clients.md) | [Русский](ru/clients.md)

# Clients

Use the simulator from common automation stacks. Each cookbook aims for the
same laboratory flow where the tool allows it:

1. Authenticate (ticket + CSRF **or** API token)
2. Read `version` / nodes / QEMU list
3. Create a VM (accept UPID)
4. Poll task status
5. Start / stop
6. Read status back
7. Delete / cleanup

## Connection matrix

Real Proxmox VE clients talk to **HTTPS `:8006`**. This lab’s Compose stack
publishes plain **HTTP `:8006`** (same port number). HTTPS belongs on
**Kubernetes Ingress** (cert-manager). Clients that cannot speak HTTP
(proxmoxer) use the optional profile: `docker compose --profile tls` →
`https://localhost:8443/` (see [Ports and TLS](configuration.md#ports-and-tls)).

| Stack | Compose transport | Notes | Docs | Code |
|---|---|---|---|---|
| Python (proxmoxer) | HTTPS `:8443` (`--profile tls`) | HTTPS-only library; `verify_ssl=False` for lab cert | [guide](examples/python-proxmoxer.md) | [`examples/python`](../examples/python) |
| Python (requests) | HTTP `:8006` | Raw `/api2/json` | [guide](examples/python-requests.md) | [`examples/python`](../examples/python) |
| Go | HTTP `:8006` | stdlib `net/http` | [guide](examples/go.md) | [`examples/go`](../examples/go) |
| Java | HTTP `:8006` | Java 11+ `HttpClient` | [guide](examples/java.md) | [`examples/java`](../examples/java) |
| Perl | HTTP `:8006` | `HTTP::Tiny` + JSON | [guide](examples/perl.md) | [`examples/perl`](../examples/perl) |
| Ansible | HTTP `:8006` | `uri` module cookbook | [guide](examples/ansible.md) | [`examples/ansible`](../examples/ansible) |
| Terraform | HTTP `:8006` (or TLS `:8443`) | Prefer HTTP; use `insecure` only with `--profile tls` | [guide](examples/terraform.md) | [`examples/terraform`](../examples/terraform) |
| Pulumi | HTTP `:8006` | `pulumi-proxmoxve` or HTTP cookbooks | [guide](examples/pulumi.md) | [`examples/pulumi`](../examples/pulumi) |

On Kubernetes with Ingress + cert-manager, point every client at
`https://<your-host>/` instead.

## More

- Cookbooks index: [examples/overview.md](examples/overview.md)
- Troubleshooting: [examples/troubleshooting-clients.md](examples/troubleshooting-clients.md)
- Pulumi full suite: [`pulumi-tests/`](../pulumi-tests/README.md)
