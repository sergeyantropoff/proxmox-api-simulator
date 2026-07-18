**Language / Язык:** [English](../../examples/troubleshooting-clients.md) | [Русский](troubleshooting-clients.md)

# Устранение неполадок клиентов

| Симптом | Решение |
|---|---|
| Ошибки TLS-сертификата | Используйте `http://localhost:8006` с отключённой проверкой **только** локально (`curl -sk`, `verify_ssl=False`, `insecure=true`) |
| Ошибка CSRF | Передавайте `CSRFPreventionToken` при мутациях по ticket; в скриптах предпочитайте аутентификацию по токену |
| Узел не найден | Профиль `small` использует `pve01` |
| 403 на power | Возможно, используется `auditor@pve` / readonly-токен — переключитесь на root или operator |
| Создание провайдером vs UPID | Опрашивайте задачи; многие провайдеры уже ждут — сырые HTTP-клиенты часто забывают |
| Расхождение после reseed | Обновите/пересоздайте состояние Terraform/Pulumi/Ansible |
| Неверные поля схемы | Hot-swap или cold-start нужного major; проверьте `/version` |
