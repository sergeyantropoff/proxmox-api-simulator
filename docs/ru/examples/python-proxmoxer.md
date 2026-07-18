**Language / Язык:** [English](../../examples/python-proxmoxer.md) | [Русский](python-proxmoxer.md)

# Python — proxmoxer

Канонический путь через библиотеку к HTTPS-шлюзу.

## Запуск

```bash
make up && make seed PROFILE=small
pip install -r examples/python/requirements.txt
python examples/python/proxmoxer_cookbook.py
```

Переопределение через переменные окружения: `PVE_HOST` (по умолчанию `localhost`),
`PVE_PORT` (по умолчанию `8007`), `PVE_USER`, `PVE_PASSWORD`, либо токен через
`PVE_TOKEN_NAME` / `PVE_TOKEN_VALUE`.

## Заметки

- `verify_ssl=False` нужен только для одноразового локального сертификата.
- Мутации по ticket, которые обрабатывает proxmoxer, автоматически включают CSRF.
- Узел по умолчанию для профиля `small` — `pve01`.
