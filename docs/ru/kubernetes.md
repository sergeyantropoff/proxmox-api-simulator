**Language / Язык:** [English](../kubernetes.md) | [Русский](kubernetes.md)

# Kubernetes / Helm

Разверните опубликованный runtime-образ Docker Hub с chart из
[`helm/proxmox-api-simulator`](../../helm/proxmox-api-simulator).

Образ: [`inecs/proxmox-api-simulator`](https://hub.docker.com/r/inecs/proxmox-api-simulator)

> **Только лаборатория / CI.** В defaults чарта слабые placeholder-секреты.
> Перед shared или Internet-facing установкой всегда переопределяйте
> `secret.ticketSigningKey` и `postgresql.auth.password`. См.
> [SECURITY.md](../../SECURITY.md).

## Транспорт (Compose vs Helm)

| Путь | URL клиента |
|---|---|
| Локальный Compose (`docker-compose*.yml`) | **HTTP** `:8006` (процесс симулятора) |
| Helm Service / `kubectl port-forward` | **HTTP** `:8006` (процесс симулятора; TLS на Ingress, если включён) |
| Helm Ingress + cert-manager | **HTTPS** на вашем hostname |

## Предварительные требования

- Kubernetes 1.27+ (или сопоставимый)
- Helm 3.14+
- [Ingress NGINX](https://kubernetes.github.io/ingress-nginx/) (или другой
  IngressClass с поддержкой HTTP-01)
- [cert-manager](https://cert-manager.io/) установлен cluster-wide

Пример установки cert-manager:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.2/cert-manager.yaml
```

## Быстрая установка (Hub release + Ingress + Let's Encrypt)

Из git checkout этого репозитория:

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set 'ingress.hosts[0].host=pve-sim.example.com' \
  --set 'ingress.tls[0].hosts[0]=pve-sim.example.com' \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

Что это делает:

1. Подтягивает `inecs/proxmox-api-simulator:0.1.0` (см. `image.tag` в example
   file).
2. Устанавливает bundled PostgreSQL 17 (`postgres:17.5-bookworm`, как в Compose).
3. Запускает миграции схемы в init container (идемпотентно).
4. Засеивает lab profile `small` (`seed.enabled=true`).
5. Создаёт ресурсы `ClusterIssuer`:
   - `letsencrypt-prod`
   - `letsencrypt-staging`
6. Создаёт Ingress с
   `cert-manager.io/cluster-issuer: letsencrypt-prod` и TLS secret
   `proxmox-api-simulator-tls`.
7. Ставит annotations Ingress, чтобы nginx не подменял JSON 404/405
   брендированными HTML-страницами (`proxy-intercept-errors: false`, узкий
   `custom-http-errors`). См. [Устранение неполадок](troubleshooting.md#ingress-отдаёт-брендированный-html-404--nginx-405-вместо-json).

DNS для `pve-sim.example.com` должен указывать на ваш Ingress controller. Затем:

```bash
kubectl -n proxmox-sim get certificate,ingress,pods
# wait until Certificate READY=True
curl -sS https://pve-sim.example.com/health/ready
open https://pve-sim.example.com/
```

Логин по умолчанию после seed: `root@pam` / `secret`.

### Сначала staging (рекомендуется)

Проверьте HTTP-01 без production rate limits:

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  -f ./helm/proxmox-api-simulator/values-ingress-example.yaml \
  --set certManager.email=you@example.com \
  --set certManager.useStaging=true \
  --set 'ingress.hosts[0].host=pve-sim.example.com' \
  --set 'ingress.tls[0].hosts[0]=pve-sim.example.com' \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set postgresql.auth.password="$(openssl rand -hex 16)"
```

Браузеры не доверяют staging CA — при тестировании используйте `curl -k`.
Переключите `certManager.useStaging=false` и пересоздайте Certificate/TLS secret
для production.

## Минимальная установка (ClusterIP + port-forward)

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set seed.enabled=true

kubectl -n proxmox-sim port-forward svc/pve-sim-proxmox-api-simulator 8006:8006
```

Откройте http://127.0.0.1:8006/ (обычный HTTP — чарт не включает TLS-шлюз из
Compose; для HTTPS используйте Ingress).

## Внешний PostgreSQL

```bash
helm upgrade --install pve-sim ./helm/proxmox-api-simulator \
  -n proxmox-sim --create-namespace \
  --set postgresql.enabled=false \
  --set secret.ticketSigningKey="$(openssl rand -hex 32)" \
  --set secret.databaseUrl='postgresql://user:pass@pg.example.com:5432/proxmox_simulator'
```

Или используйте `secret.existingSecret` с ключами `DATABASE_URL` и
`TICKET_SIGNING_KEY`.

## Как работает выпуск TLS

Когда `certManager.enabled=true` и `certManager.createClusterIssuer=true`, chart
создаёт ACME `ClusterIssuer`, решающие HTTP-01 через ваш Ingress class. Шаблон
Ingress добавляет:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - secretName: proxmox-api-simulator-tls
      hosts: [pve-sim.example.com]
```

cert-manager затем создаёт `Certificate`, завершает HTTP-01 и сохраняет пару
ключей Let's Encrypt в этом TLS secret. Chart **не** устанавливает cert-manager
и Ingress controller — только issuers и Ingress wiring.

Если ClusterIssuers уже существуют cluster-wide, задайте:

```yaml
certManager:
  enabled: true
  createClusterIssuer: false
  issuerName: your-existing-issuer
```

## Локальная проверка chart

Из корня репозитория (нужен Helm 3.14+):

```bash
make helm-lint
make helm-template
```

`helm lint` должен завершаться без failures (информационное замечание про
отсутствие `icon` в Chart.yaml ожидаемо). `helm template` рендерит Deployment
(по умолчанию с migrate initContainer), Service, Secret, PostgreSQL
StatefulSet, опциональный отдельный migrate Job (`migrate.asJob`), seed Job,
Ingress и ClusterIssuers.

## Эксплуатация

```bash
# logs
kubectl -n proxmox-sim logs -l app.kubernetes.io/name=proxmox-api-simulator -c simulator -f

# reseed
kubectl -n proxmox-sim exec deploy/pve-sim-proxmox-api-simulator -- \
  python -m app.simulation.seed_cli
# SEED_PROFILE via: kubectl set env ... or --set seed.profile=medium and upgrade

# uninstall
helm -n proxmox-sim uninstall pve-sim
```

## Справочник values

См. [`helm/proxmox-api-simulator/values.yaml`](../../helm/proxmox-api-simulator/values.yaml)
и README chart. Связанная документация:

- [Начало работы](getting-started.md) — пути Compose
- [Эксплуатация](operations.md) — публикация Docker Hub / release compose
- [Безопасность](security.md) — учётные данные лаборатории и граница доверия
