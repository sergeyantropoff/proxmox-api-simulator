**Language / Язык:** [English](../troubleshooting.md) | [Русский](troubleshooting.md)

# Устранение неполадок

## Ready остаётся недоступным

1. Проверьте Postgres: `make logs` / health в Compose.
2. Выполните `make db-migrate`.
3. Снова вызовите `/health/ready`.

Workers могут повторять попытки, пока миграции не догонят после позднего migrate.

## Неожиданный HTTP 501

У объявленных методов на мажорах **6–9** должны быть обработчики. Если видите 501:

- Подтвердите активный runtime (`/api2/json/version` и метка runtime в Web UI).
- Убедитесь, что вызываете path/verb точно как объявлено для этого мажора.
- Проверьте, что `CONTRACT_FALLBACK` в режиме fixture не маскирует другую проблему.
- Сообщите о регрессии — ожидается полное покрытие реестра.

## 401 / 403

- Тикет истёк или cookie не отправлена.
- Мутация без `CSRFPreventionToken` в сессии по тикету.
- API-токен с неверным форматом (`PVEAPIToken=user@realm!id=secret`).
- Отказ ACL (сравните `auditor@pve` и `root@pam`).
- В Web UI при HTTP 401 локальная сессия сбрасывается, в шапке снова **Guest**;
  войдите заново через Environment.

## Ingress отдаёт брендированный HTML 404 / nginx 405 вместо JSON

Симулятор отвечает на ошибки API JSON (`data` / `message` / `errors`). Если
видите HTML «страница не найдена» или страницу nginx **405**, тело ответа
подменил **Ingress / reverse proxy** (часто `custom-http-errors` у
ingress-nginx).

На Ingress этого хоста (см.
`helm/proxmox-api-simulator/values-ingress-example.yaml`):

```yaml
annotations:
  nginx.ingress.kubernetes.io/proxy-intercept-errors: "false"
  nginx.ingress.kubernetes.io/custom-http-errors: "502,503"
```

Проверьте с `Accept: application/json`. Несуществующий узел должен выглядеть так:

```json
{"data": null, "message": "No such node ('pve01')", "errors": {"node": "No such node ('pve01')"}}
```

Имена узлов в seed: профиль `small` → `pve01`; `medium` / `ha-demo` → `pve1`…

### Корректный аутентифицированный POST (как у Proxmox)

Тело form-urlencoded, cookie тикета и CSRF-заголовок (не «голый» JSON POST):

```bash
# после POST /api2/json/access/ticket → ticket + CSRFPreventionToken
curl -sk -X POST "https://HOST/api2/json/nodes/pve01/ceph/osd" \
  -H "CSRFPreventionToken: $CSRF" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -b "PVEAuthCookie=$TICKET" \
  --data-urlencode "dev=/dev/sdb"
```

## Задача никогда не завершается

- Изучите `/nodes/{node}/tasks/{upid}/status` и `/log`.
- Проверьте логи workers (`make logs`).
- Убедитесь, что `TASK_WORKER_CONCURRENCY` > 0 и аренды в базе можно забрать.
- Очень высокий `SIMULATION_TIME_SCALE` даёт необычные замедления (больше = быстрее
  симуляция); чаще виноваты неверно заданные worker leases.

## proxmoxer / сбои TLS

- Реальный PVE использует **HTTPS `:8006`**. К этой лаборатории TLS-клиенты
  ходят на порт хоста **8006** (development-шлюз) с отключённой проверкой
  локального self-signed cert.
- Хост **`:8007` этим стеком не используется** (на железе обычно PBS).
- `verify_ssl=False` **только** для локального self-signed cert.
- Внутри Compose цель — `tls-gateway:8443`.
- Seeded-имя узла для `small` — `pve01`, а не `pve1`.
- Профили `medium` / `ha-demo` используют **`pve1` / `pve2` / `pve3`**.
- Карта портов: [Порты и TLS](configuration.md#порты-и-tls).

## Drift Terraform / Pulumi после reseed

Reseed заменяет гостей в PostgreSQL; state-файлы инструментов — нет. Refresh, import
или пересборка стеков после `make seed`.

## Hot-swap «ничего не сделал»

- Просмотр каталога ≠ apply. Используйте **Apply as runtime** или
  `POST /ui/api/contract/apply?major=N`.
- Подтвердите через `/api2/json/version`.
- Помните: apply локален для процесса; перезапуск Compose восстанавливает
  `CONTRACT_SNAPSHOT`.

## Demo unload удивил

`POST /ui/api/demo/unload` очищает состояние, созданное через API, и загружает
`minimal`. Повторите `make seed PROFILE=small` (или снова загрузите demo), чтобы
восстановить более богатые фикстуры.
