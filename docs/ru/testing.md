**Language / Язык:** [English](../testing.md) | [Русский](testing.md)

# Тесты

Где живут наборы и как их запускать.

## Структура

| Путь | Назначение |
|---|---|
| `tests/unit/` | Офлайн unit-тесты (handlers, контракты, seed, workers, …) |
| `tests/integration/` | Тесты с PostgreSQL (миграции, lease задач) |
| `tests/compatibility/` | Surface probe, group smoke, proxmoxer HTTPS, verified-surface |
| `pulumi-tests/` | Pulumi surface (majors 6–9) + lifecycle `pulumi-proxmoxve`; HTML-отчёт |

Seed: `app/simulation/seed.py` (`lab` для in-process surface CI, `small` для Compose / Pulumi).

## Цели Make

```bash
make test-unit              # pytest: только unit
make test-integration       # pytest -m integration (нужен Postgres)
make test-surface           # каждый объявленный метод majors 6–9
make test-compatibility     # proxmoxer smoke (Compose --profile tls)
make ci                     # ruff + mypy + offline pytest + surface
make ci-all                 # ci + остальной integration + proxmoxer
make pulumi-tests           # Pulumi surface + lifecycle; HTML-отчёт
```

GitHub Actions на push/PR в `main` запускает `make ci` и проверку Compose/Helm.
Перед крупными API-изменениями локально: `make ci-all` и `make pulumi-tests`.

Отчёт Pulumi: `pulumi-tests/pulumi/reports/report.html` — см.
[`pulumi-tests/README.ru.md`](../../pulumi-tests/README.ru.md).

## Последний локальный прогон (2026-07-18)

Полный прогон без ограничений на этом checkout:

| Gate | Результат |
|---|---|
| `make ci-all` | **PASS** (exit 0) |
| — unit (offline pytest) | 193 passed |
| — surface probe (majors 6–9) | PASS |
| — integration | 12 passed |
| — proxmoxer compatibility | PASS |
| `make pulumi-tests` | **PASS** (exit 0), ~28 с |
| — lifecycle (`pulumi-proxmoxve`) | PASS |
| — surface PVE 6.4-15 / 7.4-16 / 8.4.5 / 9.2.3 | PASS, `critical=0` |
| — coverage | **2324 / 2324** методов majors 6–9 |

Артефакты: `pulumi-tests/pulumi/reports/report.html` (также `results.json`, `junit.xml`).
