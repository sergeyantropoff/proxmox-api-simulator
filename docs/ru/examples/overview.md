**Language / Язык:** [English](../../examples/overview.md) | [Русский](overview.md)

# Обзор примеров клиентов

## Чеклист запуска

```bash
make up
curl -sf http://localhost:8006/health/ready
make seed PROFILE=small
curl -s http://localhost:8006/api2/json/version
```

Опционально — зафиксировать major 8 на время сессии:

```bash
curl -s -X POST 'http://localhost:8006/ui/api/contract/apply?major=8'
```

## Эндпоинты

| URL | Когда использовать |
|---|---|
| `http://localhost:8006` | curl, Go, Java, Perl, Ansible, requests |
| `http://localhost:8006` | proxmoxer, многие TLS-клиенты Terraform/Pulumi |

## Краткая справка по аутентификации

**Ticket**

```bash
RESP=$(curl -s -X POST -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket)
TICKET=$(echo "$RESP" | jq -r .data.ticket)
CSRF=$(echo "$RESP" | jq -r .data.CSRFPreventionToken)
```

**Заголовок токена**

```text
Authorization: PVEAPIToken=root@pam!automation=automation-secret
```

## Ожидание UPID

Никогда не считайте, что ВМ уже запущена, только по HTTP-ответу мутации. Опрашивайте
`/nodes/{node}/tasks/{upid}/status`, пока `data.status` не станет терминальным (обычно
`stopped` с кодом выхода OK для завершённых задач — используйте поля Proxmox, которые
ваш клиент уже понимает).

## Предупреждение о повторном seed

`make seed` заменяет гостей в PostgreSQL. После этого обновите состояние
Terraform/Pulumi/Ansible.

## Запускаемое дерево примеров

См. [`examples/README.ru.md`](../../../examples/README.ru.md).
