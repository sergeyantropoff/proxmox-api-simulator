**Language / Язык:** [English](../observability.md) | [Русский](observability.md)

# Наблюдаемость

## Health

| Путь | Назначение |
|---|---|
| `GET /health/live` | Liveness процесса |
| `GET /health/ready` | База доступна **и** миграции актуальны; HTTP 503 при невыполнении |

Пример:

```bash
curl -s http://localhost:8006/health/live
curl -s http://localhost:8006/health/ready
```

## Корреляция запросов

Входящие запросы принимают или генерируют ID через `REQUEST_ID_HEADER`
(по умолчанию `X-Request-ID`). Структурированные логи включают поля корреляции и
редактируют известные шаблоны секретов.

## Метрики / трейсинг

В текущем приложении **нет** scrape-эндпоинта Prometheus `/metrics` и **нет**
встроенного экспортёра OpenTelemetry. Архитектурные заметки, где они упоминаются,
описывают целевой дизайн, а не поставляемую телеметрию.

Не путайте пути Proxmox API под `/cluster/metrics` с телеметрией процесса
симулятора — эти обработчики симулируют состояние конфигурации metrics-server PVE
внутри PostgreSQL.

## Evidence совместимости

Операционные отчёты совместимости:

- `/admin/compatibility`
- `/admin/compatibility.md`
- `/admin/compatibility.html`

Также доступны через панель совместимости Web UI.
