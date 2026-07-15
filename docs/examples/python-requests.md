# Python — requests

Raw HTTP against `:8006` without proxmoxer.

```bash
pip install -r examples/python/requirements.txt
python examples/python/requests_cookbook.py
```

The script demonstrates token auth (no CSRF) and ticket auth (with CSRF) for the
shared create → wait → start → stop → delete flow.
