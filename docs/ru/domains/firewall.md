**Language / Язык:** [English](../../domains/firewall.md) | [Русский](firewall.md)

# Firewall

Конфигурация firewall на уровне cluster, node и guest — rules, aliases, IP sets,
security groups — в основном сохраняется через cluster/node metadata и связанные
структуры.

Handlers покрывают заявленную firewall-поверхность для major 6–9. Примените
нужную major-версию перед проверкой имён полей, специфичных для версии.
