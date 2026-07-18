**Language / Язык:** [English](CONTRIBUTING.md) | [Русский](CONTRIBUTING.ru.md)

# Участие в разработке

Спасибо за помощь с лабораторным симулятором Proxmox VE API.

## Требования

- Docker + Docker Compose
- `make`
- Локальный Python для повседневной работы не нужен (инструменты в Compose)

## Локальный цикл

```bash
cp -n .env.example .env
make install
make up
make seed PROFILE=small
curl -sS http://localhost:8006/health/ready
```

Основной HTTPS-эндпоинт (как у реального PVE): `http://localhost:8006/`
(self-signed — `curl -sk` или принять предупреждение в браузере).

## Quality gates (обязательны перед PR)

```bash
make ci            # ruff format/check + mypy + offline pytest + surface probe
make ci-all        # ещё integration + proxmoxer compatibility
make helm-lint     # lint chart (+ ingress example values)
make pulumi-tests  # Pulumi surface (majors 6–9) + pulumi-proxmoxve lifecycle
```

GitHub Actions на каждый push/PR в `main` запускает `make ci` и проверку
Compose/Helm. Перед крупными API/клиентскими изменениями локально прогоняйте
`make ci-all`, `make helm-lint` и `make pulumi-tests`.

Карта наборов, Make-цели и последние записанные локальные результаты:
[docs/ru/testing.md](docs/ru/testing.md).

## Важные правила проекта

1. Мутации должны **persist в PostgreSQL** (таблицы и/или jsonb metadata).
2. Не добавляйте user-facing сообщения вроде «not supported in the simulator» —
   см. `.cursor/rules/durable-simulator.mdc`.
3. Сохраняйте формы запросов/ответов Proxmox из снимка контракта.
4. При изменении операторского поведения синхронизируйте EN и RU docs.

## Документация

- Индекс: [docs/README.md](docs/README.md) · [docs/ru/README.md](docs/ru/README.md)
- Безопасность / модель угроз лаборатории: [SECURITY.md](SECURITY.md)

## Релизы

Maintainers публикуют runtime-образ так:

```bash
docker login
make release          # пушит inecs/proxmox-api-simulator:<version> (+ :latest)
```

После публичного релиза при необходимости вставьте overview из
[docs/docker-hub-overview.md](docs/docker-hub-overview.md) в описание репозитория
Docker Hub.
