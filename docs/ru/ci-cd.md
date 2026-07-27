**Language / Язык:** [English](../ci-cd.md) | [Русский](ci-cd.md)

# CI/CD (Jenkins + Gitea)

SemVer хранится в [`VERSION`](../../VERSION). Локальный bump:
`make bump-patch` / `make bump-minor` (синхронизирует `pyproject.toml` и Helm).
Jenkins версию **не** поднимает — собирает то, что в коммите.

Публичный URL после деплоя: **https://proxmox.devops.org.ru/**

## Pipeline

Один [`Jenkinsfile`](../../Jenkinsfile) на ветках `main` / `master`:

1. **Build & push** (agent `docker` / DinD) — multi-arch `linux/amd64,linux/arm64`
   в Harbor и Docker Hub, теги только **`:{VERSION}`** и **`:latest`**.
2. **Deploy** — `kubectl set image` для `simulators/simulators-proxmox`
   (контейнер `simulator` + initContainer `migrate`), затем rollout status.

Первый install в кластере (Ingress, Postgres, секреты) — **не** этот job, а
`make addon-simulators` в DevOpsTools/K3S (`simulators_proxmox_host:
proxmox.devops.org.ru`).

### Образы

| Registry | Repository |
|---|---|
| Harbor | `hub.antropoff.ru/devops-tools/proxmox-api-simulator` |
| Docker Hub | `inecs/proxmox-api-simulator` |

### Credentials (Jenkins Global)

| ID | Тип | Назначение |
|---|---|---|
| `harbor-devops-tools-push-pull-access` | Username/password | Push в Harbor |
| `docker-hub` | Username/password | Docker Hub `inecs` |
| `k3s-kubeconfig` | Secret file | Kubeconfig для deploy |
| `ssh-gitea-key` | SSH private key | Checkout из Gitea |

## Что сделать в Gitea

1. Репозиторий на Gitea (зеркало или primary), ветка `main`.
2. Deploy key / credential Jenkins `ssh-gitea-key` с правом clone
   (`git@…:…/proxmox_api_simulator.git`).
3. По желанию: webhook Gitea → Jenkins Multibranch (или polling / Organization
   Folder).

## Что сделать в Jenkins

1. **Credentials** — четыре ID выше (как у Wrapped), если ещё нет.
2. **Agent** — pod template label `docker` с контейнером `docker` (DinD /
   buildx), как у Wrapped.
3. **Job** — Multibranch Pipeline (или Pipeline from SCM):
   - Script Path: `Jenkinsfile`
   - Ветки: `main` (и `master` при необходимости)
   - SCM: SSH URL Gitea + `ssh-gitea-key`
4. **Harbor** — проект `devops-tools`, robot может push
   `proxmox-api-simulator`.
5. **Docker Hub** — репозиторий `inecs/proxmox-api-simulator`, права у
   `docker-hub`.
6. **Кластер** — релиз `simulators` в ns `simulators` уже установлен
   (`make addon-simulators`). Deployment: `simulators-proxmox`.
7. После bump `VERSION` и push в `main` — прогнать job и проверить:
   - теги `:0.x.y` и `:latest` в Harbor/Hub
   - `kubectl -n simulators get deploy,ing`
   - Help → About: badge `v0.x.y` на https://proxmox.devops.org.ru/

## Локальный релиз без Jenkins

```bash
make bump-patch          # или bump-minor
make version-commit
git push origin HEAD
# или только Hub вручную:
make release
```
