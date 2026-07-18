**Language / Язык:** [English](../../examples/terraform.md) | [Русский](terraform.md)

# Terraform

Пример использует провайдер Proxmox, направленный на локальный HTTPS-шлюз
(`http://localhost:8006`) с `insecure = true` для разработческого сертификата.

```bash
cd examples/terraform
terraform init
terraform apply
```

Версии плагинов провайдера меняются быстро — зафиксируйте версии в `versions.tf` на
те, что вы протестировали. После `make seed` обновите или пересоздайте state, чтобы
предположения о VMID и узле оставались согласованными.

Этот cookbook — отправная точка для лабораторного CI, а не сертификация каждого
ресурса провайдера по всем четырём major API. Зафиксируйте major симулятора перед
apply (`CONTRACT_SNAPSHOT` или hot-swap + проверка `/version`).
