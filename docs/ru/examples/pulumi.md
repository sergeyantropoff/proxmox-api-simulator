**Language / Язык:** [English](../../examples/pulumi.md) | [Русский](pulumi.md)

# Pulumi

Python-программа Pulumi, управляющая симулятором по HTTPS с аутентификацией по токену
через паттерны Pulumi Command/provider, описанные в `examples/pulumi`.

```bash
cd examples/pulumi
pulumi stack init dev   # один раз
pulumi up
```

Та же осторожность, что и с Terraform: состояние PostgreSQL симулятора и состояние Pulumi
независимы. Зафиксируйте major API для воспроизводимого CI.
