**Language / Язык:** [English](../api-surface.md) | [Русский](api-surface.md)

# Поверхность API

## Путь запроса

1. Middleware назначает или пробрасывает request ID.
2. Активный снимок контракта выбирает объявленные пути и схемы.
3. Аутентификация разрешает принципала (тикет или API-токен).
4. Проверки ACL / привилегий выполняются до раскрытия или изменения ресурсов.
5. Path, query и body валидируются по схемам, производным от контракта.
6. Семантический обработчик выполняется против состояния в PostgreSQL.
7. Долгие операции создают durable-задачу (+ lock при необходимости) и возвращают UPID.
8. Ответы используют Proxmox-конверт под `/api2/json` или `/api2/extjs`.

## Два рендерера

Каждый метод контракта регистрируется под обоими:

- `/api2/json/...`
- `/api2/extjs/...`

Клиенты и Web UI обычно используют JSON-рендерер.

## Обработчики vs контракты

- **Declared** — присутствует во импортированном снимке API Viewer для мажора.
- **Implemented** — для этого verb + path зарегистрирован семантический обработчик.
- Мажорные версии **6–9** имеют **100%** implemented-покрытие для объявленных методов.

Обработчики должны сохранять эффекты create/update/delete. Пустые no-op мутации не
входят в продуктовый контракт. См. workspace durable-simulator rule.

## OpenAPI и исследование

- Интерактивная документация FastAPI: `/docs`
- Инспектор методов Web UI: `/` → catalog → method
- UI API: `/ui/api/versions`, `/ui/api/catalog`, `/ui/api/method`,
  `/ui/api/compatibility`, `/ui/api/contract/apply`, `/ui/api/demo/*`

## Эндпоинты совместимости

| Путь | Формат |
|---|---|
| `/admin/compatibility` | JSON |
| `/admin/compatibility.md` | Markdown |
| `/admin/compatibility.html` | HTML |

Отчёты следуют активному runtime-контракту после горячей замены.

## Задачи (UPID)

Асинхронная работа (power гостя, clone, migrate, многие delete, backup, …)
возвращает UPID. Опрашивайте:

```text
GET /nodes/{node}/tasks/{upid}/status
GET /nodes/{node}/tasks/{upid}/log
```

Workers забирают задачи через `FOR UPDATE SKIP LOCKED`, продлевают аренды и
восстанавливаются после перезапуска процесса. HTTP 200 на запрос мутации означает
«принято», а не «гость уже в финальном состоянии».

## Ошибки (типичные)

| Статус | Типичная причина |
|---|---|
| 401 | Отсутствует/невалидный тикет или токен |
| 403 | Отказ ACL или отсутствует CSRF при мутации по тикету |
| 409 | Конфликт VMID, недопустимый переход состояния, contention lock |
| 501 | Обработчик отсутствует (не должно появляться для объявленных методов на 6–9) |
| 503 | Сбой готовности (database / migrations) |

## Импорт контрактов

```bash
make shell
proxmox-api-contract validate path/to/source.json
proxmox-api-contract --store contracts import --file path/to/source.json --version 9.2.3
proxmox-api-contract --store contracts list
proxmox-api-contract diff old.json new.json --format markdown
```

Удалённый импорт требует HTTPS, allowlist официальных хостов, лимиты
size/redirect/timeout и неизменяемые ревизии с checksum.
