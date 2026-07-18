**Language / Язык:** [English](../authentication.md) | [Русский](authentication.md)

# Аутентификация

Симулятор реализует аутентификацию Proxmox-совместимыми тикетами и API-токенами
с проверкой ACL для не-root принципалов.

## Вход по тикету

```http
POST /api2/json/access/ticket
Content-Type: application/x-www-form-urlencoded

username=root@pam&password=secret
```

Успешный ответ включает:

- `ticket` — также устанавливается как HttpOnly cookie `PVEAuthCookie` (SameSite=Strict)
- `CSRFPreventionToken` — обязателен для мутаций с аутентификацией по тикету
- `username` и связанные поля идентичности

Тикеты подписываются HMAC с `TICKET_SIGNING_KEY`, по умолчанию истекают через два часа
и допускают небольшой сдвиг часов в будущее.

### Правила CSRF

| Запрос | Сессия по тикету | API-токен |
|---|---|---|
| `GET` / `HEAD` / `OPTIONS` | Достаточно cookie (или тикета) | Заголовок `Authorization` |
| Другие методы | Cookie **и** заголовок `CSRFPreventionToken` | CSRF **не** требуется |

```bash
curl -X POST \
  -H "Cookie: PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  -d '...' \
  http://localhost:8006/api2/json/nodes/pve01/qemu/100/status/start
```

## API-токены

Формат заголовка:

```http
Authorization: PVEAPIToken=USER@REALM!TOKENID=SECRET
```

Секреты хранятся только как scrypt-хеши. Создание и явная регенерация возвращают
plaintext-секрет **один раз**; list и read его никогда не выводят. Удаление токена
немедленно его инвалидирует.

Привилегии токена — **пересечение** привилегий токена и эффективных (прямых +
унаследованных) ACL владельца. Токен не может эскалировать права выше владельца.

## Seeded development-принципалы

Сидятся **каждым** профилем — включая `minimal` и после demo unload в Web UI.
Unload уменьшает guests/nodes/storages; лабораторные принципалы и токены
`apply_seed` всё равно вставляет:

| Принципал | Пароль | Токен | Примечания |
|---|---|---|---|
| `root@pam` | `secret` | `automation` / `automation-secret` | Полный доступ по тикету; токен всё равно ограничен при ограниченных привилегиях |
| `auditor@pve` | `auditor-secret` | `readonly` / `readonly-secret` | Унаследованный auditor ACL — чтение OK, power ops запрещены |
| `operator@pve` | `operator@pve-password` | `operator` / `operator-secret` | VM audit/power на `/vms` |
| `storage@pve` | `storage@pve-password` | `storage` / `storage-secret` | Область datastore на `/storage` |

Эти учётные данные **только для лаборатории**. Смените или отключите их перед
выходом в сеть за пределы вашей рабочей станции.

## Root vs ACL

Root-сессии по тикету обходят обычные проверки ACL в Proxmox-совместимом смысле,
используемом этим симулятором. Отдельные API-токены остаются ограниченными. Тесты
совместимости проверяют разделение привилегий для персон auditor/operator/storage.

## Связанные пути

- Тикет: `/access/ticket`
- Пользователи / группы / роли / ACL / realm'ы / permissions
- Токены: `/access/users/{userid}/token[/{tokenid}]`
- TFA и OpenID: durable локальное состояние; **без** живых вызовов IdP

См. доменное руководство [Access](../domains/access.md).
