**Language / Язык:** [English](terraform.md) | [Русский](../ru/examples/terraform.md)

# Terraform

Example uses a Proxmox provider pointed at the local HTTPS gateway
(`http://localhost:8006`) with `insecure = true` for the development
certificate.

```bash
cd examples/terraform
terraform init
terraform apply
```

Provider plugin versions move quickly — pin versions in `versions.tf` to what
you have tested. After `make seed`, refresh or recreate state so VMID/node
assumptions stay aligned.

This cookbook is a starting point for lab CI, not a certification of every
provider resource against all four API majors. Pin the simulator major before
apply (`CONTRACT_SNAPSHOT` or hot-swap + `/version` assert).
