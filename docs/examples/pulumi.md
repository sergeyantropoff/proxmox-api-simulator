# Pulumi

Python Pulumi program that drives the simulator over HTTPS using token auth via
the Pulumi Command/provider patterns documented in `examples/pulumi`.

```bash
cd examples/pulumi
pulumi stack init dev   # once
pulumi up
```

Same reseed caution as Terraform: simulator PostgreSQL state and Pulumi state
are independent. Pin the API major for reproducible CI.
