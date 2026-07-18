**Language / Язык:** [English](../operations.md) | [Русский](operations.md)

# Эксплуатация

## Команды day-2

```bash
make up                 # start stack
make down               # stop stack
make restart
make logs
make dev                # foreground reload-oriented workflow
make db-migrate         # idempotent migrations
make seed PROFILE=small # atomic reseed
make shell              # interactive tools container
```

## Миграции

Упорядоченные SQL-файлы применяются транзакционно и записывают SHA-256
checksum. Повторный запуск `make db-migrate` безопасен. Изменение уже
применённой миграции отклоняется. `/health/ready` остаётся недоступным, пока
не применена последняя упакованная миграция. Воркеры задач повторяют захват
после того, как миграции догонят актуальное состояние.

## Reseed

```bash
make seed PROFILE=medium
```

Reseed заменяет изменяемое состояние симуляции. Внешнее состояние автоматизации
(Terraform state files, Pulumi stacks, Ansible inventories с закодированными
VMID) может после этого рассинхронизироваться — обновите или пересоздайте эти
боковые каналы.

## Восстановление воркеров

Воркеры используют аренды PostgreSQL. После сбоя или перезапуска просроченные
аренды перехватываются, а незавершённая работа может безопасно продолжиться.
Настраиваемые параметры: `TASK_WORKER_CONCURRENCY`, `TASK_LEASE_SECONDS`,
`SIMULATION_TIME_SCALE`.

## Смена API major по умолчанию

1. Предпочтительно задайте `CONTRACT_SNAPSHOT` на нужный bundled/normalized
   snapshot для холодного старта (Compose / k8s / OpenShift).
2. Используйте Web UI apply или `POST /ui/api/contract/apply?major=N` для
   временных переключений в пределах процесса.

## Резервное копирование состояния лаборатории

PostgreSQL — система записи. Используйте обычное резервное копирование и
восстановление Postgres (pg_dump / снимки томов), если нужно сохранить
засеянную лабораторию. Контейнеры приложения одноразовые, пока сохранён том БД.

## Публикация в Docker Hub

`make release` собирает **runtime**-образ (production target — не локальный
bind-mounted образ `dev`) и публикует его в Docker Hub:

```bash
docker login   # once; account must own or can push to DOCKERHUB_USER
make release
```

Значения по умолчанию:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DOCKERHUB_USER` | `inecs` | Namespace/org в Docker Hub |
| `IMAGE_NAME` | `proxmox-api-simulator` | Имя репозитория |
| `VERSION` | from `pyproject.toml` | Тег образа |
| `PUSH_LATEST` | `1` | Также тегировать/пушить `:latest` |

Примеры:

```bash
make release
make release VERSION=0.2.0
make release DOCKERHUB_USER=myorg PUSH_LATEST=0
make release-build   # build/tag locally without pushing
```

Опубликованные теги:

- `inecs/proxmox-api-simulator:<version>`
- `inecs/proxmox-api-simulator:latest` (если не `PUSH_LATEST=0`)

После публикации при необходимости вставьте
[обзор Docker Hub](../docker-hub-overview.md) в описание репозитория Hub и
держите GitHub About в одном стиле («stateful Proxmox VE API simulator», а не
тонкий mock).

CI в GitHub Actions на каждый push/PR в `main` запускает `make ci` и проверку
Compose/Helm (см. `.github/workflows/ci.yml`).

## Быстрый старт с опубликованным compose-файлом

[`docker-compose.release.yml`](../../docker-compose.release.yml) подтягивает
runtime-образ из Hub и запускает PostgreSQL + migrate + simulator:

```bash
docker compose -f docker-compose.release.yml up -d
docker compose -f docker-compose.release.yml run --rm --entrypoint python \
  simulator -m app.simulation.seed_cli

curl http://localhost:8006/health/ready
open http://localhost:8006/
```

Вспомогательные команды из git checkout:

```bash
make release-up
make release-seed PROFILE=small
make release-down
```

Полезные переопределения:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DOCKER_IMAGE` | `inecs/proxmox-api-simulator` | Репозиторий образа |
| `IMAGE_TAG` | `latest` | Тег для pull |
| `SIMULATOR_PORT` | `8006` | HTTPS-порт на хосте (TLS-шлюз) |
| `TICKET_SIGNING_KEY` | lab default | Меняйте вне игрушечных лаб |
| `POSTGRES_PASSWORD` | `proxmox` | Пароль БД |

Development и release Compose публикуют **HTTPS `:8006`** на хосте через nginx
TLS-шлюз (тот же порт, что у реального PVE). Процесс симулятора остаётся HTTP
на `:8006` внутри Docker-сети. См.
[Порты и TLS](configuration.md#порты-и-tls).

Для Kubernetes с публичным TLS (cert-manager / Let's Encrypt) используйте Helm
chart — см. [Kubernetes / Helm](kubernetes.md).

## Обновления

1. Подтяните / пересоберите образы (`make install` / `make docker-build` по
   необходимости).
2. Выполните миграции.
3. Подтвердите `/health/ready`.
4. Повторно проверьте `/admin/compatibility` и `/api2/json/version`.
5. Повторно запустите `make test-compatibility`, если в CI проверяете внешних
   клиентов (засеивает профиль **medium** — `pve1`/`pve2`/`pve3` — для migration
   smoke).

## Сброс лаборатории

```bash
make seed PROFILE=small
# or via UI: unload demo → minimal, then seed again
```

Для жёсткого сброса БД используйте `make db-reset` (разрушительно — см. help
Makefile).
