**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Интеграционный набор Pulumi

Suite только в Docker против симулятора Proxmox API.

| Слой | Покрытие |
|---|---|
| **Surface** | **100%** объявленных методов контракта majors **6–9** (каждый path+verb) по HTTP (`pvelib/surface.py`). PASS только при `declared == probed` на каждый major и нуле критичных сбоев (501, «not supported», 5xx, exceptions, неизвестные verb). |
| **Lifecycle** | Только **`pulumi-proxmoxve`** (мост BPG) — Provider, data sources инвентаря, `VmLegacy` + проверки непустых outputs. Это **не** полное покрытие API: в провайдере десятки ресурсов, не тысячи contract methods. HTTPS через lab TLS-шлюз; surface — HTTP. |

В отчётах (`pulumi/reports/report.html`, `results.json`, `junit.xml`) — блок **Full contract coverage** с итогами `declared`/`probed` по major и суммой (например `Coverage: 2324/2324 methods across majors 6–9`).

## Структура

```
pulumi-tests/
  pulumi/
    run_suite.py
    report.py
    pvelib/                 # httpx + surface probe
    programs/lifecycle/     # программа pulumi-proxmoxve
  docker/docker-compose.yml
  Makefile
```

## Запуск

Из корня репозитория:

```bash
make pulumi-tests
```

Или:

```bash
cd pulumi-tests
make up
make test-smoke
make test
open pulumi/reports/report.html
make down
```

Env провайдера (Compose): `PROXMOX_VE_ENDPOINT=https://tls-gateway:8443/`
(внутренний TLS suite — `pulumi-proxmoxve` не принимает `http://`), плюс
username/password/`INSECURE`. Surface probe: `API_URL=http://simulator:8006`.
Хостовый lab URL — plain `http://localhost:8006/` (HTTPS в K8s — только Ingress).
