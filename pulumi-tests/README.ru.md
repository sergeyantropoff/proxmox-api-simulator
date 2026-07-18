**Language / Язык:** [English](README.md) | [Русский](README.ru.md)

# Интеграционный набор Pulumi

Suite только в Docker против симулятора Proxmox API.

| Слой | Покрытие |
|---|---|
| **A — Surface (HTTP contract matrix)** | **100%** = каждый объявленный метод контракта majors **6–9** (path+verb: GET/PUT/POST/DELETE) плюс **синтетический HEAD на каждый GET path**. Ticket + CSRF на мутациях; form-urlencoded; оболочка `{ "data": … }`. PASS при `declared == probed` на major и в сумме, `critical=0` (501, «not supported», 5xx, exceptions, пустые/неверные 2xx envelope). HEAD — в гистограмме глаголов, **не** в знаменателе declared/probed. |
| **B — Lifecycle** | Только smoke **`pulumi-proxmoxve`** (мост BPG) — Provider, data sources инвентаря, `VmLegacy` + непустые outputs. Это **не** 100% API и **не** покрытие по числу ресурсов провайдера. HTTPS через lab TLS-шлюз; surface — HTTP. |

В отчётах (`pulumi/reports/report.html`, `results.json`, `junit.xml`) — **Full contract coverage**, **verb histogram (вкл. HEAD)** и строка вида:

`Coverage: N/N methods across majors 6–9 (critical=0)`

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

### Короткий curl (ticket → GET/POST + отчёт)

При поднятом стеке (`http://localhost:8006`):

```bash
TICKET=$(curl -s -c /tmp/pve.ck -b /tmp/pve.ck \
  -d 'username=root@pam&password=secret' \
  http://localhost:8006/api2/json/access/ticket)
echo "$TICKET" | jq .
CSRF=$(echo "$TICKET" | jq -r .data.CSRFPreventionToken)
curl -s -b /tmp/pve.ck http://localhost:8006/api2/json/version | jq .
curl -s -b /tmp/pve.ck -H "CSRFPreventionToken: $CSRF" \
  -d 'vmid=100&name=demo' \
  http://localhost:8006/api2/json/nodes/pve01/qemu | jq .
```

Отчёт: `pulumi-tests/pulumi/reports/report.html`.

Env провайдера (Compose): `PROXMOX_VE_ENDPOINT=https://tls-gateway:8443/`
(внутренний TLS suite — `pulumi-proxmoxve` не принимает `http://`), плюс
username/password/`INSECURE`. Surface probe: `API_URL=http://simulator:8006`.
Хостовый lab URL — plain `http://localhost:8006/` (HTTPS в K8s — только Ingress).
Seed для CI/suite: `SEED_PROFILE=small` (default Compose).
