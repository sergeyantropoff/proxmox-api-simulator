**Language / Язык:** [English](../../domains/access.md) | [Русский](access.md)

# Access

Устойчивая идентификация и авторизация: users, groups, roles, ACL entries,
realms, passwords, API tokens, permissions queries, tickets, TFA, OpenID,
VNC tickets.

## Основное

- Ticket login и CSRF — см. [Authentication](../authentication.md).
- При создании token секрет возвращается один раз; в хранилище сохраняются только
  хеши.
- Наследование ACL и пересечение привилегий token ∩ owner.
- Состояние realm / TFA / OpenID **локальное**; живые вызовы каталога или IdP не
  выполняются.

## Предзаполненные персоны

`root@pam`, `auditor@pve`, `operator@pve`, `storage@pve` — пароли и tokens см. в
руководстве по authentication.
