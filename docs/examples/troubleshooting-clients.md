# Troubleshooting clients

| Symptom | Fix |
|---|---|
| TLS certificate errors | Use `:8007` with verify disabled **only** locally, or use HTTP `:8006` |
| CSRF failure | Send `CSRFPreventionToken` with ticket mutations; prefer token auth in scripts |
| Node not found | `small` seed uses `pve01` |
| 403 on power | You may be using `auditor@pve` / readonly token — switch to root or operator |
| Provider create vs UPID | Poll tasks; many providers already wait — raw HTTP clients often forget |
| Drift after reseed | Refresh/recreate Terraform/Pulumi/Ansible state |
| Wrong schema fields | Hot-swap or cold-start the intended major; confirm `/version` |
