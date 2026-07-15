# Python — proxmoxer

Canonical library path against the HTTPS gateway.

## Run

```bash
make up && make seed PROFILE=small
pip install -r examples/python/requirements.txt
python examples/python/proxmoxer_cookbook.py
```

Environment overrides: `PVE_HOST` (default `localhost`), `PVE_PORT` (default
`8007`), `PVE_USER`, `PVE_PASSWORD`, or token via `PVE_TOKEN_NAME` /
`PVE_TOKEN_VALUE`.

## Notes

- `verify_ssl=False` is required only for the disposable local certificate.
- Ticket mutations handled by proxmoxer include CSRF automatically.
- Default node for `small` is `pve01`.
