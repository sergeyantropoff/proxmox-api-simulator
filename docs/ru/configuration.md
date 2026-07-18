**Language / Язык:** [English](../configuration.md) | [Русский](configuration.md)

# Конфигурация

Настройки приложения загружаются из окружения (см. `.env.example`).
Docker Compose подставляет многие из них для сервиса `simulator`; значения,
объявленные в `environment:` в `docker-compose.yml`, переопределяют `.env` для этого
сервиса.

## Основные

| Переменная | По умолчанию / пример | Назначение |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Адрес привязки |
| `APP_PORT` | `8006` | HTTP-порт прослушивания |
| `DATABASE_URL` | `postgresql://proxmox:proxmox@postgres:5432/proxmox_simulator` | asyncpg DSN |
| `DB_POOL_MIN_SIZE` | `1` | Минимум пула |
| `DB_POOL_MAX_SIZE` | `10` | Максимум пула |
| `DB_CONNECT_TIMEOUT_SECONDS` | `10` | Таймаут подключения |
| `DB_COMMAND_TIMEOUT_SECONDS` | `30` | Таймаут команды |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `REQUEST_ID_HEADER` | `X-Request-ID` | Заголовок корреляции запросов |

## Контракт и каталог

| Переменная | Назначение |
|---|---|
| `CONTRACT_SNAPSHOT` | Путь к нормализованному снимку, загружаемому при **холодном старте** |
| `CONTRACT_FALLBACK` | `error` (по умолчанию), `schema-default` или `fixture` — поведение для методов **без** семантического обработчика |
| `COMPATIBILITY_EVIDENCE` | Необязательный evidence JSON для отчётов совместимости |
| `CATALOG_ARTIFACT_URL_6` … `_9` | Официальные URL API Viewer при импорте/кэшировании мажоров каталога |

Горячая замена в runtime (Web UI / `POST /ui/api/contract/apply`) заменяет таблицу
маршрутов в памяти для мажоров **6–9** без перезаписи `CONTRACT_SNAPSHOT`. Перезапуск
процесса восстанавливает снимок холодного старта. См. [Версии API](api-versions.md).

При **100%** покрытии обработчиков на мажорах 6–9 `CONTRACT_FALLBACK` не используется
для объявленных методов активного контракта. В production-подобных лабораториях
оставляйте `error`, чтобы любой случайный пробел проявлялся как HTTP 501.

## Безопасность и задачи

| Переменная | Назначение |
|---|---|
| `TICKET_SIGNING_KEY` | HMAC-ключ для тикетов и CSRF-токенов, привязанных к тикету (**меняйте вне игрушечных лабораторий**) |
| `TASK_WORKER_CONCURRENCY` | Число asyncio workers с арендой (1–32) |
| `TASK_LEASE_SECONDS` | Длительность аренды задачи в PostgreSQL |
| `SIMULATION_TIME_SCALE` | Ускоряет симулируемые длительности задач |

## Seed и хуки клиентских тестов

| Переменная | Назначение |
|---|---|
| `SEED_PROFILE` | Имя профиля для seed CLI (`small`, `medium`, …) |
| `SEED_LARGE_NODES` | Число узлов для `large` |
| `SEED_LARGE_RESOURCES` | Число гостей для `large` (по умолчанию 10 000) |
| `TEST_DATABASE_URL` | DSN для интеграционных тестов |
| `PROXMOXER_HOST` / `PROXMOXER_PORT` | Цель клиента совместимости (`tls-gateway` / `8443` в Compose) |

## Порты и TLS

### Реальный Proxmox VE (справочно)

На физическом / production-узле PVE management API слушает **HTTPS `:8006`**
(`/api2/json/...`). Связанные management-порты (это не отдельные REST API):

| Порт | Протокол | Назначение |
|---|---|---|
| `8006` | TCP, HTTPS | Web UI + REST API |
| `3128` | TCP | SPICE proxy (графическая консоль) |
| `5900–5999` | TCP (WebSocket) | VNC web-консоль |
| `22` | TCP | SSH / кластерные операции |
| `5405–5412` | UDP | Трафик Corosync |

Порт **`8007`** — **не** API PVE: обычно это management-порт Proxmox Backup
Server (PBS). Не направляйте PVE-клиентов на `:8007` на реальном железе.

### Эндпоинты лабораторного симулятора

| Эндпоинт | Использование |
|---|---|
| `http://localhost:8006` | Основной URL клиентов — nginx TLS-шлюз → симулятор (curl, браузеры, proxmoxer, Terraform, …) |

Сам процесс симулятора говорит по **HTTP на `:8006` внутри Docker-сети**. Compose
публикует self-signed HTTPS-фронт на хосте **`:8006`** (тот же порт, что у
реального PVE), чтобы неизменённые TLS-клиенты вели себя как против production
(`https://host:8006/api2/json/...`). Внутри Compose шлюз слушает `8443` и
проксирует на `simulator:8006`. Хост **`:8007` больше не используется** для
лабораторного API (на реальном железе этот порт обычно PBS, не PVE).

Встроенный сертификат в `docker/tls/` — одноразовый материал для разработки.
Никогда не используйте его вне локальных лабораторий. См. [Безопасность](security.md).

## Заметки по Compose

- `migrate` выполняется один раз; `simulator` ждёт успешного migrate.
- Development Compose монтирует репозиторий и включает Uvicorn reload.
- В Compose по умолчанию `CONTRACT_SNAPSHOT` закрепляет встроенную ревизию PVE **9.2.3**
  для холодного старта.

## Открытые и неиспользуемые ключи в примере

`.env.example` может по-прежнему перечислять ключи вроде `PVE_API_VERSION`,
`SIMULATION_SEED`, `SIMULATOR_ADMIN_ENABLED` и `SIMULATOR_ADMIN_TOKEN`, которые
**не** потребляются текущей моделью настроек. Для мажорной версии по умолчанию
используйте `CONTRACT_SNAPSHOT`, для runtime-переключений — Web UI / apply API. Не
предполагайте, что сегодня существует аутентифицированный admin API `/_simulator`.
