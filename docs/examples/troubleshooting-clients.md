**Language / Язык:** [English](troubleshooting-clients.md) | [Русский](../ru/examples/troubleshooting-clients.md)

# Troubleshooting clients

| Symptom | Fix |
|---|---|
| TLS certificate errors | Compose default is `http://localhost:8006` (no TLS). For proxmoxer use `docker compose --profile tls` and `https://localhost:8443` with verify disabled **only** locally (`curl -sk`, `verify_ssl=False`, `insecure=true`). On Kubernetes use your Ingress hostname with cert-manager TLS. |
| CSRF failure | Send `CSRFPreventionToken` with ticket mutations; prefer token auth in scripts |
| Node not found | `small` seed uses `pve01` |
| 403 on power | You may be using `auditor@pve` / readonly token — switch to root or operator |
| Provider create vs UPID | Poll tasks; many providers already wait — raw HTTP clients often forget |
| Drift after reseed | Refresh/recreate Terraform/Pulumi/Ansible state |
| Wrong schema fields | Hot-swap or cold-start the intended major; confirm `/version` |
