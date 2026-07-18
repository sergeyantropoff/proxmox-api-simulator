**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Helm-чарт: proxmox-api-simulator

Развёртывает опубликованный runtime-образ
[`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)
с опциональным официальным PostgreSQL (`postgres:17.5-bookworm`), миграциями, seed Job, Ingress и ресурсами
cert-manager Let's Encrypt `ClusterIssuer`.

> **Только лаборатория / CI.** В defaults чарта слабые placeholder-секреты
> (`change-me…`, пароль БД `proxmox`). Перед сетевым или shared-кластером всегда
> переопределяйте `secret.ticketSigningKey` и `postgresql.auth.password` (как в
> примере установки ниже). См. [SECURITY.md](../../SECURITY.md).

Полное руководство: [docs/kubernetes.md](../../docs/ru/kubernetes.md).

## Быстрая установка

Требования: Kubernetes, Helm 3, ingress-nginx (или совместимый), cert-manager.

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set ingress.hosts[0].host=pve-sim.example.com \
  --set ingress.tls[0].hosts[0]=pve-sim.example.com \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

Направьте DNS хоста на Ingress-контроллер, дождитесь Ready у Certificate,
затем откройте `https://pve-sim.example.com/`.

## Обзор values

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `image.repository` | `inecs/proxmox-api-simulator` | Образ Hub |
| `image.tag` | chart `appVersion` | Тег образа |
| `postgresql.enabled` | `true` | Встроенный PostgreSQL StatefulSet |
| `secret.databaseUrl` / `externalDatabase.*` | | Внешняя БД при отключённом postgres |
| `ingress.enabled` | `false` | Публикация через Ingress |
| `certManager.enabled` | `false` | Аннотации Ingress + опциональные ClusterIssuers |
| `seed.enabled` | `false` | Post-install seed Job |

См. [`values.yaml`](values.yaml) и [`values-ingress-example.yaml`](values-ingress-example.yaml).
