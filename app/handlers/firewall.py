"""Firewall handlers backed by cluster metadata."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import database, require_node, state, subdirs, values
from app.simulation.seed import CLUSTER_ID

ScopeFn = Callable[[dict[str, Any]], str]


async def _load_firewall(request: Request) -> dict[str, Any]:
    row = await database(request).pool.fetchrow(
        "SELECT metadata FROM clusters WHERE id=$1",
        CLUSTER_ID,
    )
    metadata = state(row["metadata"]) if row is not None else {}
    firewall = metadata.get("firewall")
    return dict(firewall) if isinstance(firewall, dict) else {}


async def _save_firewall(request: Request, firewall: dict[str, Any]) -> None:
    await database(request).pool.execute(
        """UPDATE clusters SET metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb), '{firewall}', $2::jsonb, true
        ), updated_at=now() WHERE id=$1""",
        CLUSTER_ID,
        json.dumps(firewall, sort_keys=True),
    )


def _empty_scope() -> dict[str, Any]:
    return {
        "options": {},
        "rules": [],
        "aliases": {},
        "ipset": {},
        "groups": {},
        "log": [],
    }


def _get_scope(firewall: dict[str, Any], scope: str) -> dict[str, Any] | None:
    scopes = firewall.get("scopes")
    if not isinstance(scopes, dict):
        return None
    section = scopes.get(scope)
    return cast(dict[str, Any], section) if isinstance(section, dict) else None


def _ensure_scope(firewall: dict[str, Any], scope: str) -> dict[str, Any]:
    """Create an empty durable scope on mutation; never injects catalog defaults."""
    scopes = firewall.setdefault("scopes", {})
    if not isinstance(scopes, dict):
        scopes = {}
        firewall["scopes"] = scopes
    section = scopes.get(scope)
    if not isinstance(section, dict):
        section = _empty_scope()
        scopes[scope] = section
    section.setdefault("options", {})
    section.setdefault("rules", [])
    section.setdefault("aliases", {})
    section.setdefault("ipset", {})
    section.setdefault("groups", {})
    section.setdefault("log", [])
    return cast(dict[str, Any], section)


def _scope_data(firewall: dict[str, Any], scope: str) -> dict[str, Any]:
    """Mutation helper — ensure scope exists without template defaults."""
    return _ensure_scope(firewall, scope)


def register_firewall_handlers(registry: HandlerRegistry) -> None:
    def register_scope(
        base: str,
        scope_fn: ScopeFn,
        *,
        require_node_name: bool = False,
        include_macros: bool = False,
        include_groups: bool = False,
    ) -> None:
        async def _ready(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            payload = values(inputs)
            if require_node_name:
                await require_node(request, str(payload["node"]))
            return payload

        async def index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
            await _ready(request, inputs)
            names = ["aliases", "ipset", "log", "options", "refs", "rules"]
            if include_groups:
                names.insert(2, "groups")
            if include_macros:
                names.append("macros")
            return subdirs(*names)

        async def options_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            if section is None:
                return {}
            options = section.get("options", {})
            return dict(options) if isinstance(options, dict) else {}

        async def options_put(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _ensure_scope(firewall, scope_fn(payload))
            current = dict(section.get("options") or {})
            for key, value in payload.items():
                if key in {"node", "vmid", "delete", "digest"}:
                    continue
                current[key] = value
            section["options"] = current
            await _save_firewall(request, firewall)
            return current

        async def rules_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            if section is None:
                return []
            rules = section.get("rules", [])
            return list(rules) if isinstance(rules, list) else []

        async def rules_create(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _scope_data(firewall, scope_fn(payload))
            rules = section.setdefault("rules", [])
            if not isinstance(rules, list):
                rules = section["rules"] = []
            rule = {
                key: value for key, value in payload.items() if key not in {"node", "vmid", "pos"}
            }
            rule["pos"] = len(rules)
            rules.append(rule)
            await _save_firewall(request, firewall)

        async def rule_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            pos = int(values(inputs)["pos"])
            rules = await rules_list(request, inputs)
            if pos < 0 or pos >= len(rules):
                raise ApiError(404, "firewall rule does not exist")
            return dict(rules[pos])

        async def rule_update(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            pos = int(payload["pos"])
            firewall = await _load_firewall(request)
            rules = _scope_data(firewall, scope_fn(payload)).setdefault("rules", [])
            if not isinstance(rules, list) or pos < 0 or pos >= len(rules):
                raise ApiError(404, "firewall rule does not exist")
            rules[pos] = {
                **rules[pos],
                **{k: v for k, v in payload.items() if k not in {"node", "vmid"}},
            }
            await _save_firewall(request, firewall)

        async def rule_delete(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            pos = int(payload["pos"])
            firewall = await _load_firewall(request)
            rules = _scope_data(firewall, scope_fn(payload)).setdefault("rules", [])
            if not isinstance(rules, list) or pos < 0 or pos >= len(rules):
                raise ApiError(404, "firewall rule does not exist")
            del rules[pos]
            for index, rule in enumerate(rules):
                if isinstance(rule, dict):
                    rule["pos"] = index
            await _save_firewall(request, firewall)

        async def aliases_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            aliases = section.get("aliases", {}) if section else {}
            if not isinstance(aliases, dict):
                return []
            return [
                {"name": name, **{k: v for k, v in data.items() if k != "name"}}
                for name, data in sorted(aliases.items())
                if isinstance(data, dict)
            ]

        async def aliases_create(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            section = _scope_data(firewall, scope_fn(payload))
            aliases = section.setdefault("aliases", {})
            if name in aliases:
                raise ApiError(400, f"alias '{name}' already exists")
            aliases[name] = {
                "name": name,
                "cidr": str(payload.get("cidr") or ""),
                "comment": str(payload.get("comment") or ""),
            }
            await _save_firewall(request, firewall)

        async def aliases_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            alias = _scope_data(firewall, scope_fn(payload)).get("aliases", {}).get(name)
            if not isinstance(alias, dict):
                raise ApiError(404, "alias does not exist")
            return dict(alias)

        async def aliases_update(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            aliases = _scope_data(firewall, scope_fn(payload)).setdefault("aliases", {})
            if name not in aliases or not isinstance(aliases[name], dict):
                raise ApiError(404, "alias does not exist")
            current = dict(aliases[name])
            if payload.get("rename"):
                new_name = str(payload["rename"])
                if new_name in aliases and new_name != name:
                    raise ApiError(400, f"alias '{new_name}' already exists")
                del aliases[name]
                name = new_name
                current["name"] = new_name
            for key in ("cidr", "comment"):
                if key in payload:
                    current[key] = payload[key]
            aliases[name] = current
            await _save_firewall(request, firewall)

        async def aliases_delete(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            aliases = _scope_data(firewall, scope_fn(payload)).setdefault("aliases", {})
            if name not in aliases:
                raise ApiError(404, "alias does not exist")
            del aliases[name]
            await _save_firewall(request, firewall)

        async def ipset_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            ipsets = section.get("ipset", {}) if section else {}
            if not isinstance(ipsets, dict):
                return []
            return [
                {"name": name, "comment": data.get("comment", "")}
                for name, data in sorted(ipsets.items())
                if isinstance(data, dict)
            ]

        async def ipset_create(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            ipsets = _scope_data(firewall, scope_fn(payload)).setdefault("ipset", {})
            if name in ipsets:
                raise ApiError(400, f"ipset '{name}' already exists")
            ipsets[name] = {
                "name": name,
                "comment": str(payload.get("comment") or ""),
                "entries": {},
            }
            await _save_firewall(request, firewall)

        async def ipset_get(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            ipset = _scope_data(firewall, scope_fn(payload)).get("ipset", {}).get(name)
            if not isinstance(ipset, dict):
                raise ApiError(404, "ipset does not exist")
            entries = ipset.get("entries", {})
            if not isinstance(entries, dict):
                return []
            return [
                {"cidr": cidr, **{k: v for k, v in data.items() if k != "cidr"}}
                for cidr, data in sorted(entries.items())
                if isinstance(data, dict)
            ]

        async def ipset_delete(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            firewall = await _load_firewall(request)
            ipsets = _scope_data(firewall, scope_fn(payload)).setdefault("ipset", {})
            if name not in ipsets:
                raise ApiError(404, "ipset does not exist")
            del ipsets[name]
            await _save_firewall(request, firewall)

        async def ipset_entry_create(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            cidr = str(payload["cidr"])
            firewall = await _load_firewall(request)
            ipsets = _scope_data(firewall, scope_fn(payload)).setdefault("ipset", {})
            if name not in ipsets or not isinstance(ipsets[name], dict):
                raise ApiError(404, "ipset does not exist")
            entries = ipsets[name].setdefault("entries", {})
            if cidr in entries:
                raise ApiError(400, f"ip '{cidr}' already exists in ipset")
            entries[cidr] = {
                "cidr": cidr,
                "comment": str(payload.get("comment") or ""),
                "nomatch": int(bool(payload.get("nomatch"))),
            }
            await _save_firewall(request, firewall)

        async def ipset_entry_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            cidr = str(payload["cidr"])
            firewall = await _load_firewall(request)
            ipset = _scope_data(firewall, scope_fn(payload)).get("ipset", {}).get(name)
            if not isinstance(ipset, dict):
                raise ApiError(404, "ipset does not exist")
            entry = ipset.get("entries", {}).get(cidr)
            if not isinstance(entry, dict):
                raise ApiError(404, "ipset entry does not exist")
            return dict(entry)

        async def ipset_entry_update(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            cidr = str(payload["cidr"])
            firewall = await _load_firewall(request)
            ipsets = _scope_data(firewall, scope_fn(payload)).setdefault("ipset", {})
            if name not in ipsets or not isinstance(ipsets[name], dict):
                raise ApiError(404, "ipset does not exist")
            entries = ipsets[name].setdefault("entries", {})
            if cidr not in entries:
                raise ApiError(404, "ipset entry does not exist")
            current = dict(entries[cidr])
            if "comment" in payload:
                current["comment"] = payload["comment"]
            if "nomatch" in payload:
                current["nomatch"] = int(bool(payload.get("nomatch")))
            entries[cidr] = current
            await _save_firewall(request, firewall)

        async def ipset_entry_delete(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            name = str(payload["name"])
            cidr = str(payload["cidr"])
            firewall = await _load_firewall(request)
            ipsets = _scope_data(firewall, scope_fn(payload)).setdefault("ipset", {})
            if name not in ipsets or not isinstance(ipsets[name], dict):
                raise ApiError(404, "ipset does not exist")
            entries = ipsets[name].setdefault("entries", {})
            if cidr not in entries:
                raise ApiError(404, "ipset entry does not exist")
            del entries[cidr]
            await _save_firewall(request, firewall)

        async def refs_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            if section is None:
                return []
            refs: list[dict[str, Any]] = []
            for name in section.get("aliases", {}) or {}:
                refs.append({"type": "alias", "name": name})
            for name in section.get("ipset", {}) or {}:
                refs.append({"type": "ipset", "name": name})
            return refs

        async def log_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            if section is None:
                return []
            log = section.get("log", [])
            return list(log) if isinstance(log, list) else []

        async def macros_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
            from app.handlers.common import cluster_metadata

            metadata = await cluster_metadata(request)
            macros = metadata.get("firewall_macros")
            if isinstance(macros, list):
                return [dict(item) for item in macros if isinstance(item, dict)]
            firewall = await _load_firewall(request)
            nested = firewall.get("macros")
            if isinstance(nested, list):
                return [dict(item) for item in nested if isinstance(item, dict)]
            return []

        async def groups_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            firewall = await _load_firewall(request)
            section = _get_scope(firewall, scope_fn(payload))
            groups = section.get("groups", {}) if section else {}
            if not isinstance(groups, dict):
                return []
            return [
                {"group": name, "comment": data.get("comment", "")}
                for name, data in sorted(groups.items())
                if isinstance(data, dict)
            ]

        async def groups_create(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            group = str(payload["group"])
            firewall = await _load_firewall(request)
            groups = _scope_data(firewall, scope_fn(payload)).setdefault("groups", {})
            if group in groups:
                raise ApiError(400, f"security group '{group}' already exists")
            groups[group] = {"comment": str(payload.get("comment") or ""), "rules": []}
            await _save_firewall(request, firewall)

        async def group_rules(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            payload = await _ready(request, inputs)
            group = str(payload["group"])
            firewall = await _load_firewall(request)
            groups = _scope_data(firewall, scope_fn(payload)).get("groups", {})
            if group not in groups or not isinstance(groups[group], dict):
                raise ApiError(404, "security group does not exist")
            rules = groups[group].get("rules", [])
            return list(rules) if isinstance(rules, list) else []

        async def group_delete(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            group = str(payload["group"])
            firewall = await _load_firewall(request)
            groups = _scope_data(firewall, scope_fn(payload)).setdefault("groups", {})
            if group not in groups:
                raise ApiError(404, "security group does not exist")
            del groups[group]
            await _save_firewall(request, firewall)

        async def group_rule_create(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            group = str(payload["group"])
            firewall = await _load_firewall(request)
            groups = _scope_data(firewall, scope_fn(payload)).setdefault("groups", {})
            if group not in groups or not isinstance(groups[group], dict):
                raise ApiError(404, "security group does not exist")
            rules = groups[group].setdefault("rules", [])
            if not isinstance(rules, list):
                rules = groups[group]["rules"] = []
            rule = {
                key: value
                for key, value in payload.items()
                if key not in {"node", "vmid", "group", "pos"}
            }
            rule["pos"] = len(rules)
            rules.append(rule)
            await _save_firewall(request, firewall)

        async def group_rule_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            rules = await group_rules(request, inputs)
            pos = int(values(inputs)["pos"])
            if pos < 0 or pos >= len(rules):
                raise ApiError(404, "firewall rule does not exist")
            return dict(rules[pos])

        async def group_rule_update(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            group = str(payload["group"])
            pos = int(payload["pos"])
            firewall = await _load_firewall(request)
            groups = _scope_data(firewall, scope_fn(payload)).setdefault("groups", {})
            if group not in groups or not isinstance(groups[group], dict):
                raise ApiError(404, "security group does not exist")
            rules = groups[group].setdefault("rules", [])
            if not isinstance(rules, list) or pos < 0 or pos >= len(rules):
                raise ApiError(404, "firewall rule does not exist")
            rules[pos] = {
                **rules[pos],
                **{k: v for k, v in payload.items() if k not in {"node", "vmid", "group"}},
            }
            await _save_firewall(request, firewall)

        async def group_rule_delete(request: Request, inputs: dict[str, Any]) -> None:
            payload = await _ready(request, inputs)
            group = str(payload["group"])
            pos = int(payload["pos"])
            firewall = await _load_firewall(request)
            groups = _scope_data(firewall, scope_fn(payload)).setdefault("groups", {})
            if group not in groups or not isinstance(groups[group], dict):
                raise ApiError(404, "security group does not exist")
            rules = groups[group].setdefault("rules", [])
            if not isinstance(rules, list) or pos < 0 or pos >= len(rules):
                raise ApiError(404, "firewall rule does not exist")
            del rules[pos]
            await _save_firewall(request, firewall)

        registry.register(base, "GET", index)
        registry.register(f"{base}/options", "GET", options_get)
        registry.register(f"{base}/options", "PUT", options_put)
        registry.register(f"{base}/rules", "GET", rules_list)
        registry.register(f"{base}/rules", "POST", rules_create)
        registry.register(f"{base}/rules/{{pos}}", "GET", rule_get)
        registry.register(f"{base}/rules/{{pos}}", "PUT", rule_update)
        registry.register(f"{base}/rules/{{pos}}", "DELETE", rule_delete)
        registry.register(f"{base}/aliases", "GET", aliases_list)
        registry.register(f"{base}/aliases", "POST", aliases_create)
        registry.register(f"{base}/aliases/{{name}}", "GET", aliases_get)
        registry.register(f"{base}/aliases/{{name}}", "PUT", aliases_update)
        registry.register(f"{base}/aliases/{{name}}", "DELETE", aliases_delete)
        registry.register(f"{base}/ipset", "GET", ipset_list)
        registry.register(f"{base}/ipset", "POST", ipset_create)
        registry.register(f"{base}/ipset/{{name}}", "GET", ipset_get)
        registry.register(f"{base}/ipset/{{name}}", "DELETE", ipset_delete)
        registry.register(f"{base}/ipset/{{name}}", "POST", ipset_entry_create)
        registry.register(f"{base}/ipset/{{name}}/{{cidr}}", "GET", ipset_entry_get)
        registry.register(f"{base}/ipset/{{name}}/{{cidr}}", "PUT", ipset_entry_update)
        registry.register(f"{base}/ipset/{{name}}/{{cidr}}", "DELETE", ipset_entry_delete)
        registry.register(f"{base}/refs", "GET", refs_list)
        registry.register(f"{base}/log", "GET", log_list)
        if include_macros:
            registry.register(f"{base}/macros", "GET", macros_list)
        if include_groups:
            registry.register(f"{base}/groups", "GET", groups_list)
            registry.register(f"{base}/groups", "POST", groups_create)
            registry.register(f"{base}/groups/{{group}}", "GET", group_rules)
            registry.register(f"{base}/groups/{{group}}", "POST", group_rule_create)
            registry.register(f"{base}/groups/{{group}}", "DELETE", group_delete)
            registry.register(f"{base}/groups/{{group}}/{{pos}}", "GET", group_rule_get)
            registry.register(f"{base}/groups/{{group}}/{{pos}}", "PUT", group_rule_update)
            registry.register(f"{base}/groups/{{group}}/{{pos}}", "DELETE", group_rule_delete)

    register_scope(
        "/cluster/firewall",
        lambda _payload: "cluster",
        include_macros=True,
        include_groups=True,
    )
    register_scope(
        "/nodes/{node}/firewall",
        lambda payload: f"node:{payload['node']}",
        require_node_name=True,
    )
    register_scope(
        "/nodes/{node}/qemu/{vmid}/firewall",
        lambda payload: f"qemu:{payload['node']}:{payload['vmid']}",
        require_node_name=True,
    )
    register_scope(
        "/nodes/{node}/lxc/{vmid}/firewall",
        lambda payload: f"lxc:{payload['node']}:{payload['vmid']}",
        require_node_name=True,
    )
