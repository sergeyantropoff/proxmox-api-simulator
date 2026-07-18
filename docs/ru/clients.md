**Language / Язык:** [English](../clients.md) | [Русский](clients.md)

# Клиенты

Используйте симулятор из обычных стеков автоматизации. Каждый cookbook стремится
к одному лабораторному сценарию, где инструмент это позволяет:

1. Аутентификация (ticket + CSRF **или** API token)
2. Чтение `version` / nodes / списка QEMU
3. Создание VM (принять UPID)
4. Опрос статуса задачи
5. Start / stop
6. Чтение статуса
7. Delete / cleanup

## Матрица подключений

Клиенты реального Proxmox VE ходят на **HTTPS `:8006`**. Compose в этой
лаборатории публикует plain **HTTP `:8006`** (тот же номер порта). HTTPS —
на **Kubernetes Ingress** (cert-manager). Клиенты без HTTP (proxmoxer):
`docker compose --profile tls` → `https://localhost:8443/` (см.
[Порты и TLS](configuration.md#порты-и-tls)).

| Стек | Транспорт Compose | Заметки | Docs | Code |
|---|---|---|---|---|
| Python (proxmoxer) | HTTPS `:8443` (`--profile tls`) | Только HTTPS; `verify_ssl=False` для lab cert | [руководство](examples/python-proxmoxer.md) | [`examples/python`](../../examples/python) |
| Python (requests) | HTTP `:8006` | Сырой `/api2/json` | [руководство](examples/python-requests.md) | [`examples/python`](../../examples/python) |
| Go | HTTP `:8006` | stdlib `net/http` | [руководство](examples/go.md) | [`examples/go`](../../examples/go) |
| Java | HTTP `:8006` | Java 11+ `HttpClient` | [руководство](examples/java.md) | [`examples/java`](../../examples/java) |
| Perl | HTTP `:8006` | `HTTP::Tiny` + JSON | [руководство](examples/perl.md) | [`examples/perl`](../../examples/perl) |
| Ansible | HTTP `:8006` | Cookbook модуля `uri` | [руководство](examples/ansible.md) | [`examples/ansible`](../../examples/ansible) |
| Terraform | HTTP `:8006` (или TLS `:8443`) | Предпочитайте HTTP; `insecure` только с `--profile tls` | [руководство](examples/terraform.md) | [`examples/terraform`](../../examples/terraform) |
| Pulumi | HTTP `:8006` | `pulumi-proxmoxve` или HTTP cookbooks | [руководство](examples/pulumi.md) | [`examples/pulumi`](../../examples/pulumi) |

В Kubernetes с Ingress + cert-manager направляйте клиентов на
`https://<ваш-хост>/`.

## Дальше

- Индекс cookbook: [examples/overview.md](examples/overview.md)
- Troubleshooting: [examples/troubleshooting-clients.md](examples/troubleshooting-clients.md)
- Полный Pulumi suite: [`pulumi-tests/`](../../pulumi-tests/README.ru.md)
