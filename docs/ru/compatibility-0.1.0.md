**Language / Язык:** [English](../compatibility-0.1.0.md) | [Русский](compatibility-0.1.0.md)

# Отчёт о совместимости — 0.1.0

Этот отчёт фиксирует evidence для релиза симулятора 0.1.0 относительно bundled
контрактов Proxmox VE API (majors 6–9). Это матрица ограничений для измерений
*качества / внешней интеграции*, а не заявление общей совместимости с
гипервизором Proxmox. Покрытие реестра обработчиков относительно каждого
contract snapshot — **100%** для majors 6–9: у каждого объявленного метода есть
семантический обработчик.

Обзор для пользователя — в [compatibility.md](compatibility.md). Актуальные
machine-readable counts всегда доступны из `/admin/compatibility` (и `.md` /
`.html`). Предпочитайте этот endpoint, когда симулятор запущен.

## Сводка (основной контракт PVE 9.2.3)

| Уровень | Методы | Доля контракта | Evidence |
|---|---:|---:|---|
| Declared and dynamically routed | 675 | 100% | Bundled API Viewer snapshot |
| Stateful semantics implemented | **675** | **100%** | Handler registry ∩ contract |
| Observed / verified surface ledger | **675** | **100%** | `evidence/pve-9.2.3.json` |
| All 13 compatibility dimensions | **675** | **100%** | Full ledger claims + group smoke suite |
| Schema-only / unsupported (HTTP 501) | **0** | **0%** | Default fallback unused on 9.2.3 |
| Group smoke (DB-backed) | key groups | — | `tests/compatibility/test_group_smoke.py` |
| proxmoxer smoke exercised | 9 | 1.33% | Unmodified proxmoxer 2.3 compatibility test |

Smoke set: `POST /access/ticket`, `GET /version`, `GET /nodes`,
`GET /nodes/{node}/qemu`, `GET /nodes/{node}/qemu/{vmid}/status/current`, одна из
двух state mutations (`start` или `stop`) и повторные
`GET /nodes/{node}/tasks/{upid}/status`. Обе мутации имеют независимые API- и
worker-тесты; один smoke run выбирает переход, допустимый для текущего состояния.

## Покрытие по Proxmox major

| Версия | Объявлено | Реализовано | Проверено | Покрытие |
|---|---:|---:|---:|---:|
| 6.4-15 | 504 | 504 | 504 | 100.00% |
| 7.4-16 | 540 | 540 | 540 | 100.00% |
| 8.4.5 | 605 | 605 | 605 | 100.00% |
| 9.2.3 | 675 | 675 | 675 | 100.00% |

**Verified** здесь означает, что каждый объявленный метод присутствует в
per-major surface ledger (`evidence/pve-{version}.json`), перегенерируемом через
`make evidence` и охраняемом `tests/compatibility/test_verified_surface.py`.
Hot-swap (`POST /ui/api/contract/apply?major=N`) загружает ledger этого major,
поэтому Help → Compatibility показывает полные observed/verified counts после
Apply.

Каждая запись ledger заявляет все тринадцать измерений, поэтому
`fully_compatible` совпадает с declared после Apply. Group smoke
(`tests/compatibility/test_group_smoke.py`) проверяет репрезентативные
мутации с PostgreSQL для access, QEMU, LXC, storage, notifications, SDN и node
DNS/network.

Старые majors переиспользуют обработчики 9.2.3 плюс path synonyms из
`app/handlers/legacy_aliases.py` (`ceph/pools` → `ceph/pool`,
`backupinfo` → `backup-info`, `scan/glusterfs`, legacy TFA collection verbs и
т. д.).

## Реализованная поверхность (высокий уровень)

- **Core**: version, ticket login, node list/status/index, cluster resources.
- **Access**: users, groups, roles, ACL, password, tokens, realms, TFA, OpenID,
  permissions, VNC ticket — всё durable в PostgreSQL.
- **QEMU / LXC**: полные contract surfaces, включая agent, cloud-init, consoles,
  RRD, firewall aliases/ipset, migrate/clone/snapshot subsets.
- **Storage / pools / backup / HA / firewall / Ceph / SDN**: durable handlers
  (`clusters.metadata`, `nodes.metadata.ops`, normalized tables).
- **Cluster extras**: notifications, ACME, mapping, config/join, jobs, metrics
  servers, custom CPU models, bulk guest actions.
- **Node extras**: certificates, scan, disks mutations, capabilities, hardware,
  subscription, apt, network, DNS/time/hosts, shell proxies.
- **Tasks**: leased workers, status, append-only logs.
- **Auth**: ticket + CSRF для mutations; hashed API tokens.

## Принцип персистентности

Каждый create/update/delete path записывает в PostgreSQL (таблицы и/или jsonb
metadata). Секреты могут храниться, но не должны возвращаться в GET.
Пользовательские ошибки «not supported in the emulator» запрещены — см.
`.cursor/rules/durable-simulator.mdc`.

## Известные ограничения

| Область | Текущее поведение |
|---|---|
| External systems | LDAP/OpenID/ACME/Ceph не обращаются к реальным удалённым системам; состояние симулируется |
| Realm sync / OpenID login | Durable stamps / pending state / tickets; нет live IdP |
| Observation parity | Contract/tests существуют; санитизированный real-PVE observation corpus ограничен |
| TLS | Локальный nginx gateway только с checked-in self-signed development key |
| Client certification | proxmoxer 2.3 smoke; Terraform и другие клиенты не сертифицированы |
| Deep HTTP coverage | Не каждый из 675 методов прогоняется end-to-end; group smokes покрывают репрезентативные paths по доменам |

Полное покрытие реестра означает, что HTTP 501 «handler pending» больше не
должен появляться для методов, объявленных в активном контракте после Apply.
*Качество* совместимости (точный parity edge-case Proxmox) по-прежнему углубляется
тестами и observation.

При импорте новой версии контракта Proxmox: обновите bundled snapshot, выполните
`make evidence`, запустите `pytest tests/compatibility/test_verified_surface.py`
и закоммитьте обновлённые ledger `evidence/pve-*.json`.

Отчёт также раскрывает 13 независимых измерений совместимости, требуемых project
brief. Surface ledgers живут в `evidence/pve-{version}.json`; исторический deep
overlay `evidence/pve-9.2.3-0.1.0.json` сливается в canon 9.2.3 при
перегенерации. Сама динамическая регистрация маршрутов доказывает измерение
route/method; это не означает полную семантическую совместимость для каждого
edge case.
