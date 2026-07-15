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

| Stack | Transport | Notes | Docs | Code |
|---|---|---|---|---|
| Python (proxmoxer) | HTTPS `:8007` | Unmodified library; `verify_ssl=False` for local cert | [guide](examples/python-proxmoxer.md) | [`examples/python`](../examples/python) |
| Python (requests) | HTTP `:8006` | Raw `/api2/json` | [guide](examples/python-requests.md) | [`examples/python`](../examples/python) |
| Go | HTTP `:8006` | stdlib `net/http` | [guide](examples/go.md) | [`examples/go`](../examples/go) |
| Java | HTTP `:8006` | Java 11+ `HttpClient` | [guide](examples/java.md) | [`examples/java`](../examples/java) |
| Perl | HTTP `:8006` | `HTTP::Tiny` + JSON | [guide](examples/perl.md) | [`examples/perl`](../examples/perl) |
| Ansible | HTTP `:8006` | `uri` module cookbook | [guide](examples/ansible.md) | [`examples/ansible`](../examples/ansible) |
| Terraform | HTTPS `:8007` | Provider + insecure TLS for local gateway | [guide](examples/terraform.md) | [`examples/terraform`](../examples/terraform) |
| Pulumi | HTTPS `:8007` | Python program against the API | [guide](examples/pulumi.md) | [`examples/pulumi`](../examples/pulumi) |

Shared prerequisites: [examples overview](examples/overview.md).

## Credentials (seed)

| Use | Value |
|---|---|
| User | `root@pam` |
| Password | `secret` |
| Token | `root@pam!automation=automation-secret` |
| Default node (`small`) | `pve01` |

## API major

Pin the major before long runs:

- Cold start: `CONTRACT_SNAPSHOT`
- Runtime: Web UI apply or `POST /ui/api/contract/apply?major=N`

Confirm with `GET /api2/json/version`. Coverage is **100%** for declared methods
on majors 6–9.

## Troubleshooting clients

See [troubleshooting-clients](examples/troubleshooting-clients.md) and the
global [Troubleshooting](troubleshooting.md) guide.
