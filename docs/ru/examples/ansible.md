**Language / Язык:** [English](../../examples/ansible.md) | [Русский](ansible.md)

# Ansible

Playbook использует модуль `uri` для HTTP `:8006` с аутентификацией по токену, затем
ticket+CSRF для пути мутации.

```bash
cd examples/ansible
ansible-playbook -i inventory.ini playbook.yml
```

Перед использованием фиксированных VMID из предыдущего запуска выполните повторный seed
симулятора.
