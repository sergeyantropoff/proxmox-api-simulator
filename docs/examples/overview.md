**Language / Язык:** [English](overview.md) | [Русский](../ru/examples/overview.md)

# Client examples overview

## Bring-up checklist

```bash
make up
curl -sf http://localhost:8006/health/ready
make seed PROFILE=small
curl -s http://localhost:8006/api2/json/version
```

Optional — pin major 8 for the session:

```bash
curl -s -X POST 'http://localhost:8006/ui/api/contract/apply?major=8'
```

## Endpoints

| URL | When |
|---|---|
| `http://localhost:8006` | curl, Go, Java, Perl, Ansible, requests |
| `http://localhost:8006` | proxmoxer, many Terraform/Pulumi TLS clients |

## Auth quick reference

**Ticket**

```bash
RESP=$(curl -s -X POST -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket)
TICKET=$(echo "$RESP" | jq -r .data.ticket)
CSRF=$(echo "$RESP" | jq -r .data.CSRFPreventionToken)
```

**Token header**

```text
Authorization: PVEAPIToken=root@pam!automation=automation-secret
```

## UPID waiting

Never treat the mutation HTTP response alone as “VM running”. Poll
`/nodes/{node}/tasks/{upid}/status` until `data.status` is terminal (typically
`stopped` with exit status OK for completed tasks — match Proxmox fields your
client already understands).

## Reseed warning

`make seed` replaces PostgreSQL guests. Refresh Terraform/Pulumi/Ansible state
afterwards.

## Runnable tree

See [`examples/README.md`](../../examples/README.md).
