**Language / Язык:** [English](ansible.md) | [Русский](../ru/examples/ansible.md)

# Ansible

Playbook uses the `uri` module against HTTP `:8006` with token auth, then
ticket+CSRF for a mutation path.

```bash
cd examples/ansible
ansible-playbook -i inventory.ini playbook.yml
```

Reseed the simulator before relying on fixed VMIDs from a previous run.
