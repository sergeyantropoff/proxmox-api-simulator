**Language / Язык:** [English](../getting-started.md) | [Русский](getting-started.md)

# Быстрый старт

Поднимите локальный лабораторный кластер, пройдите аутентификацию и выполните первый
цикл чтения/мутации против симулятора.

## Требования

- Docker и Docker Compose
- `make` (необязательно, но используется в документированных командах)

Python, линтеры и тесты запускаются **внутри** контейнеров. Для повседневной работы
локальный Python-инструментарий не нужен.

## Выберите путь

| Путь | Когда использовать |
|---|---|
| [Опубликованный образ](#1a-опубликованный-образ-docker-hub) | Самый быстрый старт с `inecs/proxmox-api-simulator` |
| [Helm / Kubernetes](kubernetes.md) | Установка в кластер с Ingress + Let's Encrypt |
| [Checkout для разработки](#1b-checkout-для-разработки) | Вклад в проект / bind-mount исходников / HTTPS-шлюз на `:8006` |

## 1a. Опубликованный образ (Docker Hub)

Используется [`docker-compose.release.yml`](../../docker-compose.release.yml) —
PostgreSQL + runtime-симулятор из Hub + лабораторный HTTPS-шлюз. Нужен checkout
с `docker/tls/` (self-signed материалы). Сборка исходников не требуется.

> Только лаборатория / CI — перед shared или сетевым демо смените
> `TICKET_SIGNING_KEY` и пароль БД. См. [SECURITY.md](../../SECURITY.md).

```bash
# из этого репозитория (compose + docker/tls/)
docker compose -f docker-compose.release.yml pull
docker compose -f docker-compose.release.yml up -d
docker compose -f docker-compose.release.yml run --rm --entrypoint python \
  simulator -m app.simulation.seed_cli
```

Закрепите версию:

```bash
IMAGE_TAG=0.1.0 docker compose -f docker-compose.release.yml up -d
```

Make-цели (git checkout):

```bash
make release-up
make release-seed PROFILE=small
```

| Порт хоста | Сервис |
|---|---|
| `8006` | HTTPS API + Web UI через лабораторный TLS-шлюз (как у реального PVE) |
| `5432` | PostgreSQL (только localhost) |

Миграции выполняются автоматически через одноразовый сервис `migrate`.

Далее переходите к разделу [Дождитесь готовности](#2-дождитесь-готовности).

## 1b. Checkout для разработки

```bash
make install
make up
```

Сервисы:

| Порт хоста | Сервис |
|---|---|
| `8006` | HTTPS API + Web UI через nginx TLS-шлюз (как у реального PVE) |
| `5432` | PostgreSQL (только localhost) |

У реального Proxmox VE REST API доступен **только** как
`https://<host>:8006/api2/json/...`. Лаборатория публикует то же: HTTPS на
хосте `:8006` через development TLS-шлюз; см.
[Порты и TLS](configuration.md#порты-и-tls). Хост **`:8007` не используется**
(на железе это обычно PBS, не API PVE).

Миграции применяются автоматически до того, как симулятор станет готов.

## 2. Дождитесь готовности

```bash
curl -sS http://localhost:8006/health/live
curl -sS http://localhost:8006/health/ready
```

`/health/ready` возвращает HTTP 503, пока PostgreSQL недоступен **и** не применена
последняя упакованная миграция.

## 3. Загрузите профиль seed

```bash
make seed PROFILE=small
```

`small` создаёт узел `pve01`, две QEMU-гостевые ВМ (`100`, `101`), один LXC (`200`),
локальные хранилища и стандартных development-принципалов. Другие размеры — в
[Профилях seed](seed-profiles.md).

## 4. Проверьте версию API

```bash
curl -sS http://localhost:8006/api2/json/version | jq .
```

При холодном старте контракт по умолчанию — встроенный снимок PVE **9.2.3** в Docker
Compose. Переключайте мажорные версии 6–9 из Web UI или через
[Версии API](api-versions.md).

## 5. Пройдите аутентификацию

```bash
curl -sk -X POST \
  -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket | jq .
```

Сохраните `ticket` и `CSRFPreventionToken` из `data`. Для мутаций отправляйте:

- Cookie: `PVEAuthCookie=<ticket>`
- Header: `CSRFPreventionToken: <token>`

Подробнее: [Аутентификация](authentication.md).

## 6. Получите список гостей и запустите одного

```bash
# замените TICKET / CSRF из предыдущего ответа
curl -sk -H "Cookie: PVEAuthCookie=$TICKET" \
  http://localhost:8006/api2/json/nodes/pve01/qemu | jq .

curl -sk -X POST \
  -H "Cookie: PVEAuthCookie=$TICKET" \
  -H "CSRFPreventionToken: $CSRF" \
  http://localhost:8006/api2/json/nodes/pve01/qemu/100/status/start | jq .
```

Асинхронные операции возвращают строку UPID. Опрашивайте, пока задача не завершится:

```bash
curl -s -H "Cookie: PVEAuthCookie=$TICKET" \
  "http://localhost:8006/api2/json/nodes/pve01/tasks/${UPID}/status" | jq .
```

## 7. Откройте Web UI

Перейдите на [http://localhost:8006/](http://localhost:8006/) — интерактивная
консоль, каталог контрактов (PVE 6–9), представление совместимости, применение runtime-
контракта и управление demo-кластером. Скриншоты и полный список возможностей —
в [Web UI](web-ui.md).

## 8. Попробуйте клиентскую библиотеку

```bash
# из корня репозитория после make up + seed
python examples/python/proxmoxer_cookbook.py
```

Другие стеки: [Клиенты](clients.md) и [`examples/`](../../examples/README.ru.md).

## Готово, когда…

- `/health/ready` возвращает `{"status":"ok"}` (или эквивалентное OK-тело)
- `/api2/json/version` сообщает активную версию контракта
- Вход по тикету для `root@pam` успешен
- `nodes/pve01/qemu` перечисляет seeded ВМ
- Хотя бы один путь power или create возвращает UPID, который успешно завершается

## Дальнейшие шаги

- [Конфигурация](configuration.md) — env vars, workers, путь к контракту
- [Версии API](api-versions.md) — горячая замена мажоров 6–9
- [Клиенты](clients.md) — Ansible, Terraform, Pulumi, Go, Java, Perl
- [Эксплуатация](operations.md) — reseed, migrate, обновления
