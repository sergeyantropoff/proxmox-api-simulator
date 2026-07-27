**Language / Язык:** [English](ci-cd.md) | [Русский](ru/ci-cd.md)

# CI/CD (Jenkins + Gitea)

SemVer lives in [`VERSION`](../VERSION). Bump locally with `make bump-patch` /
`make bump-minor` (also syncs `pyproject.toml` and Helm chart/values). Jenkins
does **not** bump — it builds whatever is in the commit.

Public lab URL after deploy: **https://proxmox.devops.org.ru/**

## Pipeline

Single [`Jenkinsfile`](../Jenkinsfile) on `main` / `master`:

1. **Build & push** (agent `docker` / DinD) — multi-arch `linux/amd64,linux/arm64`
   to Harbor and Docker Hub with tags **`:{VERSION}`** and **`:latest`** only.
2. **Deploy** — `kubectl set image` on `simulators/simulators-proxmox` (main
   container `simulator` + initContainer `migrate`), then rollout status.

First cluster install (Ingress, Postgres, secrets) is **not** this job — use
`make addon-simulators` in DevOpsTools/K3S (`simulators_proxmox_host:
proxmox.devops.org.ru`).

### Images

| Registry | Repository |
|---|---|
| Harbor | `hub.antropoff.ru/devops-tools/proxmox-api-simulator` |
| Docker Hub | `inecs/proxmox-api-simulator` |

### Credentials (Jenkins Global)

| ID | Type | Use |
|---|---|---|
| `harbor-devops-tools-push-pull-access` | Username/password | Harbor robot push |
| `docker-hub` | Username/password | Docker Hub `inecs` |
| `k3s-kubeconfig` | Secret file | Kubeconfig for deploy |
| `ssh-gitea-key` | SSH private key | Gitea SCM checkout |

## Gitea setup

1. Ensure the repo is on Gitea (mirror or primary) with branch `main`.
2. Deploy key / Jenkins credential `ssh-gitea-key` can clone the repo
   (`git@…:…/proxmox_api_simulator.git` or your path).
3. Optional: webhook from Gitea → Jenkins Multibranch (or rely on Jenkins SCM
   polling / Organization Folder).

## Jenkins setup

1. **Credentials** — create the four IDs above if missing (same as Wrapped).
2. **Agent** — Kubernetes cloud pod template with label `docker` and a
   `docker` container (DinD / buildx), same as Wrapped.
3. **Job** — Multibranch Pipeline (or Pipeline from SCM):
   - Script Path: `Jenkinsfile`
   - Branch discover: `main` (and `master` if needed)
   - SCM: Gitea SSH URL + credential `ssh-gitea-key`
4. **Harbor project** — `devops-tools` must allow the robot to push
   `proxmox-api-simulator` (create the repository on first push or pre-create).
5. **Docker Hub** — `inecs/proxmox-api-simulator` exists / push rights for
   credential `docker-hub`.
6. **Cluster** — release `simulators` in namespace `simulators` already
   installed (`make addon-simulators`). Deployment name must be
   `simulators-proxmox`.
7. Run once on `main` after bumping `VERSION` and pushing. Confirm:
   - Harbor/Hub tags `:0.x.y` and `:latest`
   - `kubectl -n simulators get deploy,ing`
   - Help → About shows badge `v0.x.y` on https://proxmox.devops.org.ru/

## Local release (without Jenkins)

```bash
make bump-patch          # or bump-minor
make version-commit
git push origin HEAD
# or manual Hub-only:
make release             # DOCKER_IMAGE=inecs/proxmox-api-simulator
```
