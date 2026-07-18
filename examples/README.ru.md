**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Запускаемые cookbook клиентов

Сопровождающий код к [docs/ru/clients.md](../docs/ru/clients.md).

## Предварительные требования

```bash
make up
make seed PROFILE=small
```

## Структура

| Путь | Стек |
|---|---|
| `python/` | proxmoxer + requests |
| `go/` | Go stdlib |
| `java/` | Java 11+ HttpClient |
| `perl/` | HTTP::Tiny |
| `ansible/` | ansible-playbook |
| `terraform/` | Terraform + Proxmox provider |
| `pulumi/` | Pulumi (Python) |

Нода по умолчанию: **`pve01`**. Токен по умолчанию:
`root@pam!automation=automation-secret`.

Гайды: [docs/examples/](../docs/ru/examples/overview.md).
