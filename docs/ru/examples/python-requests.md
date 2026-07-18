**Language / Язык:** [English](../../examples/python-requests.md) | [Русский](python-requests.md)

# Python — requests

Сырой HTTP к `:8006` без proxmoxer.

```bash
pip install -r examples/python/requirements.txt
python examples/python/requests_cookbook.py
```

Скрипт демонстрирует аутентификацию по токену (без CSRF) и по ticket (с CSRF) для
общего потока create → wait → start → stop → delete.
