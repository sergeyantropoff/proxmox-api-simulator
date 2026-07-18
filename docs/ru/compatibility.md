**Language / Язык:** [English](../compatibility.md) | [Русский](compatibility.md)

# Совместимость

Этот документ объясняет, как симулятор заявляет совместимость с Proxmox VE API
majors **6–9**. Предпочитайте live-отчёты, когда процесс запущен.

## Live-отчёты

| URL | Формат |
|---|---|
| `/admin/compatibility` | JSON |
| `/admin/compatibility.md` | Markdown |
| `/admin/compatibility.html` | HTML |

Web UI также показывает панель совместимости через `/ui/api/compatibility?major=N`.

## Реестр и проверенное покрытие поверхности

| Версия | Объявлено | Реализовано | Проверено | Покрытие |
|---|---:|---:|---:|---:|
| 6.4-15 | 504 | 504 | 504 | 100% |
| 7.4-16 | 540 | 540 | 540 | 100% |
| 8.4.5 | 605 | 605 | 605 | 100% |
| 9.2.3 | 675 | 675 | 675 | 100% |

Старые majors сопоставляют legacy path synonyms через `legacy_aliases` с общим
набором обработчиков.

- **Implemented** — зарегистрирован семантический обработчик.
- **Verified / observed** — каждый объявленный метод перечислен в
  `evidence/pve-{version}.json` (surface ledger). Перегенерируйте через
  `make evidence`. Охраняется `tests/compatibility/test_verified_surface.py`.

После **Apply as runtime** (`POST /ui/api/contract/apply?major=N`) live-отчёт
загружает ledger этого major, поэтому Help → Compatibility показывает полные
verified counts.

## Измерения evidence

Оценка совместимости использует тринадцать независимых измерений (routing,
input shape, HTTP status, JSON structure, state semantics, long tasks,
permissions, …). Ledger по majors в `evidence/pve-{version}.json` в настоящее
время заявляют **все тринадцать измерений для каждого объявленного метода**
(перегенерируются через `make evidence`), поэтому Help → Compatibility
Dimensions показывает 100% после Apply.

Исполняемая основа этих заявлений:

| Набор | Роль |
|---|---|
| `tests/compatibility/test_verified_surface.py` | hot-swap + ledger drift + score gates |
| `tests/compatibility/test_group_smoke.py` | access / qemu / lxc / storage / cluster / SDN / node ops with PostgreSQL |
| `tests/compatibility/test_proxmoxer.py` | external proxmoxer HTTPS smoke |

Историческое богатое происхождение из `evidence/pve-9.2.3-0.1.0.json` по-прежнему
сливается в `sources` ledger 9.2.3 при перегенерации.

## Внешний client smoke

`make test-compatibility` запускает неизменённый поток **proxmoxer 2.3** против
Compose TLS gateway (`PROXMOXER_HOST` / `PROXMOXER_PORT`). Проверяются login,
reads, CSRF-protected mutation, token/ACL behaviour и завершение UPID.

Дополнительные cookbooks в [`examples/`](../../examples/README.ru.md) — manual или
CI-optional в зависимости от стека.

## Известные поведенческие ограничения

| Область | Поведение |
|---|---|
| External systems | LDAP / OpenID / ACME / Ceph не обращаются к реальным удалённым системам |
| TLS | Только локальный self-signed development gateway |
| Hypervisor | Нет реального выполнения KVM/LXC |
| Observation corpus | Санитизированные данные наблюдений real-PVE остаются ограниченными |

Исторические release notes:
[compatibility-0.1.0.md](compatibility-0.1.0.md).
