# Access

Durable identity and authorization: users, groups, roles, ACL entries, realms,
passwords, API tokens, permissions queries, tickets, TFA, OpenID, VNC tickets.

## Highlights

- Ticket login and CSRF — see [Authentication](../authentication.md).
- Token create returns the secret once; only hashes are stored.
- ACL inheritance and token ∩ owner privilege intersection.
- Realm / TFA / OpenID state is **local**; no live directory or IdP calls.

## Seeded personas

`root@pam`, `auditor@pve`, `operator@pve`, `storage@pve` — see the
authentication guide for passwords and tokens.
