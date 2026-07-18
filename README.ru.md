**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# proxmox-api-simulator

Stateful-асинхронный симулятор API [Proxmox VE](https://www.proxmox.com/) для
тестирования API-клиентов и инфраструктурных инструментов без реального
гипервизорного кластера.

> **Только лаборатория / CI.** Учётные данные, signing keys и открытые UI/admin
> helpers по умолчанию — намеренные лабораторные значения. **Не** выставляйте
> стек в публичный Интернет без замены секретов и своих сетевых ограничений.
> См. [SECURITY.md](SECURITY.md) и [Безопасность](docs/ru/security.md).

Симулятор работает на PostgreSQL, опирается на импортированные официальные
контракты API и предоставляет те же поверхности `/api2/json` и `/api2/extjs`,
что и Proxmox VE. Семантические обработчики сохраняют мутации; длительные
операции возвращают устойчивые UPID, которые выполняют воркеры с арендой задач.

## Проверенное покрытие API

Реестр обработчиков и верифицированные ledger поверхности — **100%** для каждого
включённого major:

| Контракт | Declared | Implemented | Verified |
|---|---:|---:|---:|
| PVE 6.4-15 | 504 | 504 | 504 |
| PVE 7.4-16 | 540 | 540 | 540 |
| PVE 8.4.5 | 605 | 605 | 605 |
| PVE 9.2.3 | 675 | 675 | 675 |

Переключение активного контракта в runtime — из Web UI (**Apply as runtime**) или
`POST /ui/api/contract/apply?major=N` — каждый Apply загружает
`evidence/pve-{version}.json`, чтобы observed/verified следовали выбранному
major. После импорта нового контракта перегенерируйте ledger: `make evidence`.
Живые отчёты: `/admin/compatibility` (также `.md` / `.html`). См.
[Совместимость](docs/ru/compatibility.md) и [Версии API](docs/ru/api-versions.md).

> Это измеримое покрытие контракта и обработчиков лабораторного симулятора —
> не утверждение, что каждый краевой случай Proxmox или удалённая интеграция
> ведёт себя идентично продакшен-железу.

## Быстрый старт (опубликованный образ)

Образ: [`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)

### Docker Compose

Нужен checkout с `docker-compose.release.yml`. Не публикуйте хост `:8006` за
пределы доверенной лаборатории без ротации `TICKET_SIGNING_KEY` / пароля БД.

```bash
docker compose -f docker-compose.release.yml up -d
docker compose -f docker-compose.release.yml run --rm --entrypoint python \
  simulator -m app.simulation.seed_cli

curl -sS http://localhost:8006/health/ready
curl -sS http://localhost:8006/api2/json/version
```

Или: `make release-up && make release-seed PROFILE=small`

### Helm (Kubernetes + Ingress + Let's Encrypt)

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set ingress.hosts[0].host=pve-sim.example.com \
  --set ingress.tls[0].hosts[0]=pve-sim.example.com \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

Нужны Ingress-контроллер и cert-manager. Service чарта говорит по **HTTP**
`:8006`; TLS — на Ingress. Compose тоже отдаёт plain HTTP на `:8006`; опциональный
HTTPS для proxmoxer — `docker compose --profile tls` на хосте `:8443`.
Подробности: [Kubernetes / Helm](docs/ru/kubernetes.md).

- HTTP API и Web UI (Compose): [http://localhost:8006/](http://localhost:8006/)
- Схема FastAPI: [http://localhost:8006/docs](http://localhost:8006/docs)
- Админ по умолчанию после seed: `root@pam` / `secret`

## Быстрый старт (разработка из репозитория)

Сборка и запуск development-стека с bind-mount из этого репозитория:

```bash
make install
make up
make seed PROFILE=small

curl -sS http://localhost:8006/health/ready
curl -sS http://localhost:8006/api2/json/version
curl -sS -X POST -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket
```

- HTTP API и Web UI: [http://localhost:8006/](http://localhost:8006/)
  (реальный PVE — **HTTPS** на `:8006`; лаборатория — plain HTTP на том же
  порту. Опциональный TLS для proxmoxer: `docker compose --profile tls` →
  `https://localhost:8443/`)
- Карта портов и TLS: [Порты и TLS](docs/ru/configuration.md#порты-и-tls).
- Схема FastAPI: [http://localhost:8006/docs](http://localhost:8006/docs)

### Web UI

Интерактивная консоль со светлой/тёмной темой, каталогом эндпоинтов PVE 6–9,
горячей сменой runtime-контракта и монитором задач UPID.

![Web UI, главный экран](docs/images/web-ui-main.png)

Больше экранов и подробностей: [Web UI](docs/ru/web-ui.md).

## Документация

Документация двуязычная. Переключатель **Language / Язык** — в шапке каждой
страницы; английский корень — [README.md](README.md). Индекс:
[docs/README.md](docs/README.md) · [docs/ru/README.md](docs/ru/README.md).

| Руководство | Описание |
|---|---|
| [Начало работы](docs/ru/getting-started.md) | Первая успешная лабораторная сессия |
| [Конфигурация](docs/ru/configuration.md) | Переменные окружения и Compose |
| [Аутентификация](docs/ru/authentication.md) | Тикеты, CSRF, API-токены, ACL |
| [Версии API](docs/ru/api-versions.md) | Контракты 6–9 и hot-swap |
| [Клиенты и примеры](docs/ru/clients.md) | Python, Go, Java, Perl, Ansible, Terraform, Pulumi |
| [Профили seed](docs/ru/seed-profiles.md) | Детерминированные фикстуры кластера |
| [Поверхность API](docs/ru/api-surface.md) | Маршрутизация, обработчики, fallback |
| [Домены](docs/ru/domains/README.md) | QEMU, LXC, storage, HA, SDN, … |
| [Web UI](docs/ru/web-ui.md) | Интерактивная консоль и каталоги |
| [Эксплуатация](docs/ru/operations.md) | Миграции, reseed, обновления |
| [Kubernetes / Helm](docs/ru/kubernetes.md) | Образ Hub + Ingress + Let's Encrypt |
| [Безопасность](docs/ru/security.md) | Модель угроз лаборатории и учётные данные |
| [Наблюдаемость](docs/ru/observability.md) | Health-эндпоинты и логирование |
| [Устранение неполадок](docs/ru/troubleshooting.md) | Типичные сбои |
| [FAQ](docs/ru/faq.md) | Краткие ответы |
| [Архитектура](docs/ru/architecture.md) | Границы компонентов |
| [Совместимость](docs/ru/compatibility.md) | Модель evidence и матрица релиза |

Индекс гайдов: [`docs/ru/README.md`](docs/ru/README.md).
Запускаемые cookbook: [`examples/`](examples/README.ru.md).
Интеграционный набор Pulumi (surface majors 6–9 + lifecycle, HTML-отчёт):
[`pulumi-tests/`](pulumi-tests/README.ru.md) (`make pulumi-tests`).

## proxmoxer (HTTPS-шлюз)

```python
from proxmoxer import ProxmoxAPI

proxmox = ProxmoxAPI(
    "localhost",
    port=8006,
    user="root@pam",
    password="secret",
    verify_ssl=False,  # только локальный self-signed сертификат разработки
)
print(proxmox.version.get())
print(proxmox.nodes("pve01").qemu.get())
```

Пример API-токена: пользователь `root@pam`, `token_name="automation"`,
`token_value="automation-secret"`. Запросам с токеном CSRF не нужен; мутациям
по тикету — нужен.

## Частые цели Make

```bash
make up / make down / make logs / make dev
make test                 # unit + contract (включая verified surface)
make test-integration     # с PostgreSQL
make test-surface         # все глаголы × majors 6-9 (0x501 / 0xexception)
make test-compatibility   # proxmoxer против Compose
make evidence             # перегенерация evidence/pve-*.json
make seed PROFILE=small
make db-migrate
make shell
make ci                   # ruff + mypy + offline pytest + surface probe
make release              # сборка + push runtime-образа в Docker Hub
make release-up           # pull/start docker-compose.release.yml
make release-seed PROFILE=small
```

Релиз в Docker Hub (нужен `docker login` владельца Hub; см.
[Эксплуатация](docs/ru/operations.md)):

```bash
make release                          # inecs/proxmox-api-simulator:<версия pyproject> + :latest
make release VERSION=0.2.0            # переопределить тег
make release-build                    # только build/tag, без push
make release-up && make release-seed  # запустить опубликованный стек локально
```

## Участие / безопасность / changelog

- [CONTRIBUTING.md](CONTRIBUTING.md) · [CONTRIBUTING.ru.md](CONTRIBUTING.ru.md)
- [SECURITY.md](SECURITY.md)
- [CHANGELOG.md](CHANGELOG.md)

## Чем это не является

- Не гипервизор: нет выполнения KVM/LXC на железе или nested-хостах.
- Не drop-in замена мультиарендного продакшен-Proxmox.
- Удалённые IdP / LDAP / live Ceph / live ACME эндпоинты симулируются локально;
  к реальным внешним системам они не обращаются.

## См. также

- [Web UI](docs/ru/web-ui.md) — интерактивная консоль, каталоги, панель DATA и скриншоты
