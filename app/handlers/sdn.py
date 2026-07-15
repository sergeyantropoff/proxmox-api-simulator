"""Cluster and node SDN handlers backed by clusters.metadata.sdn."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    cluster_metadata,
    require_node,
    save_cluster_metadata,
    subdirs,
    values,
)

_SECRET_KEYS = frozenset({"key", "token", "fingerprint"})


def _sdn(metadata: dict[str, Any]) -> dict[str, Any]:
    current = metadata.setdefault(
        "sdn",
        {
            "zones": {},
            "vnets": {},
            "controllers": {},
            "dns": {},
            "ipams": {},
            "fabrics": {},
            "fabric_nodes": {},
            "prefix_lists": {},
            "route_maps": {},
            "lock": None,
            "pending": False,
            "running_version": 1,
        },
    )
    if not isinstance(current, dict):
        current = {
            "zones": {},
            "vnets": {},
            "controllers": {},
            "dns": {},
            "ipams": {},
            "fabrics": {},
            "fabric_nodes": {},
            "prefix_lists": {},
            "route_maps": {},
            "lock": None,
            "pending": False,
            "running_version": 1,
        }
        metadata["sdn"] = current
    for key in (
        "zones",
        "vnets",
        "controllers",
        "dns",
        "ipams",
        "fabrics",
        "fabric_nodes",
        "prefix_lists",
        "route_maps",
    ):
        current.setdefault(key, {})
    return current


def _public(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in _SECRET_KEYS}


def _store_list(store: dict[str, Any], *, id_key: str) -> list[dict[str, Any]]:
    return [_public({id_key: name, **item}) for name, item in sorted(store.items())]


async def _load(request: Request) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = await cluster_metadata(request)
    return metadata, _sdn(metadata)


def register_sdn_handlers(registry: HandlerRegistry) -> None:
    async def index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs(
            "controllers",
            "dns",
            "dry-run",
            "fabrics",
            "ipams",
            "lock",
            "prefix-lists",
            "rollback",
            "route-maps",
            "vnets",
            "zones",
        )

    async def apply(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata, sdn = await _load(request)
        lock = sdn.get("lock")
        token = payload.get("lock-token")
        if lock and token and lock.get("token") != token:
            raise ApiError(400, "invalid SDN lock token")
        sdn["pending"] = False
        sdn["running_version"] = int(sdn.get("running_version") or 1) + 1
        if payload.get("release-lock"):
            sdn["lock"] = None
        await save_cluster_metadata(request, metadata)

    async def lock_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        metadata, sdn = await _load(request)
        if sdn.get("lock") and not values(inputs).get("allow-pending"):
            raise ApiError(400, "SDN is already locked")
        token = secrets.token_hex(8)
        sdn["lock"] = {"token": token}
        await save_cluster_metadata(request, metadata)
        return {"digest": token, "token": token}

    async def lock_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata, sdn = await _load(request)
        lock = sdn.get("lock")
        if lock is None:
            return None
        if not payload.get("force") and lock.get("token") != payload.get("lock-token"):
            raise ApiError(400, "invalid SDN lock token")
        sdn["lock"] = None
        await save_cluster_metadata(request, metadata)

    async def rollback(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        metadata, sdn = await _load(request)
        sdn["pending"] = False
        if payload.get("release-lock"):
            sdn["lock"] = None
        await save_cluster_metadata(request, metadata)

    async def dry_run(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        _metadata, sdn = await _load(request)
        return [
            {"type": "zone", "name": name, "action": "noop"}
            for name in sorted(sdn.get("zones") or {})
        ]

    def register_named(
        path: str,
        store_key: str,
        id_param: str,
        *,
        create_required: str | None = None,
    ) -> None:
        async def list_items(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
            _metadata, sdn = await _load(request)
            items = _store_list(sdn.get(store_key) or {}, id_key=id_param)
            type_filter = values(inputs).get("type")
            if type_filter:
                items = [item for item in items if item.get("type") == type_filter]
            return items

        async def create(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            item_id = str(payload[create_required or id_param])
            metadata, sdn = await _load(request)
            store = sdn.setdefault(store_key, {})
            if item_id in store:
                raise ApiError(400, f"{store_key} '{item_id}' already exists")
            store[item_id] = {
                key: value
                for key, value in payload.items()
                if key not in {"lock-token", "digest", "delete"}
            }
            store[item_id][id_param] = item_id
            sdn["pending"] = True
            await save_cluster_metadata(request, metadata)

        async def get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
            item_id = str(values(inputs)[id_param])
            _metadata, sdn = await _load(request)
            item = (sdn.get(store_key) or {}).get(item_id)
            if not isinstance(item, dict):
                raise ApiError(404, f"{store_key} entry does not exist")
            return _public({id_param: item_id, **item})

        async def update(request: Request, inputs: dict[str, Any]) -> None:
            payload = values(inputs)
            item_id = str(payload[id_param])
            metadata, sdn = await _load(request)
            store = sdn.setdefault(store_key, {})
            if item_id not in store:
                raise ApiError(404, f"{store_key} entry does not exist")
            current = dict(store[item_id])
            for key in [
                item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
            ]:
                current.pop(key, None)
            for key, value in payload.items():
                if key in {id_param, "delete", "digest", "lock-token"}:
                    continue
                current[key] = value
            current[id_param] = item_id
            store[item_id] = current
            sdn["pending"] = True
            await save_cluster_metadata(request, metadata)

        async def delete(request: Request, inputs: dict[str, Any]) -> None:
            item_id = str(values(inputs)[id_param])
            metadata, sdn = await _load(request)
            store = sdn.setdefault(store_key, {})
            if item_id not in store:
                raise ApiError(404, f"{store_key} entry does not exist")
            del store[item_id]
            sdn["pending"] = True
            await save_cluster_metadata(request, metadata)

        registry.register(path, "GET", list_items)
        registry.register(path, "POST", create)
        registry.register(f"{path}/{{{id_param}}}", "GET", get)
        registry.register(f"{path}/{{{id_param}}}", "PUT", update)
        registry.register(f"{path}/{{{id_param}}}", "DELETE", delete)

    # zones / controllers / dns / ipams
    register_named("/cluster/sdn/zones", "zones", "zone")
    register_named("/cluster/sdn/controllers", "controllers", "controller")
    register_named("/cluster/sdn/dns", "dns", "dns")
    register_named("/cluster/sdn/ipams", "ipams", "ipam")

    async def ipam_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        ipam = str(values(inputs)["ipam"])
        _metadata, sdn = await _load(request)
        if ipam not in (sdn.get("ipams") or {}):
            raise ApiError(404, "ipam does not exist")
        return {"status": "ok", "ipam": ipam}

    # vnets + nested
    async def vnets_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        _metadata, sdn = await _load(request)
        return _store_list(sdn.get("vnets") or {}, id_key="vnet")

    async def vnets_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("vnets", {})
        if vnet in store:
            raise ApiError(400, f"vnet '{vnet}' already exists")
        store[vnet] = {
            **{k: v for k, v in payload.items() if k not in {"lock-token", "digest"}},
            "vnet": vnet,
            "subnets": {},
            "ips": [],
            "firewall": {"options": {"enable": 0}, "rules": []},
        }
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def vnet_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        vnet = str(values(inputs)["vnet"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("vnets") or {}).get(vnet)
        if not isinstance(item, dict):
            raise ApiError(404, "vnet does not exist")
        return _public({"vnet": vnet, **{k: v for k, v in item.items() if k != "firewall"}})

    async def vnet_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("vnets", {})
        if vnet not in store:
            raise ApiError(404, "vnet does not exist")
        current = dict(store[vnet])
        for key in [
            item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
        ]:
            current.pop(key, None)
        for key, value in payload.items():
            if key in {"vnet", "delete", "digest", "lock-token"}:
                continue
            current[key] = value
        current["vnet"] = vnet
        store[vnet] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def vnet_delete(request: Request, inputs: dict[str, Any]) -> None:
        vnet = str(values(inputs)["vnet"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("vnets", {})
        if vnet not in store:
            raise ApiError(404, "vnet does not exist")
        del store[vnet]
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def _vnet(sdn: dict[str, Any], vnet: str) -> dict[str, Any]:
        item = (sdn.get("vnets") or {}).get(vnet)
        if not isinstance(item, dict):
            raise ApiError(404, "vnet does not exist")
        item.setdefault("subnets", {})
        item.setdefault("ips", [])
        item.setdefault("firewall", {"options": {"enable": 0}, "rules": []})
        return item

    async def subnets_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        vnet = str(values(inputs)["vnet"])
        _metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        return _store_list(item.get("subnets") or {}, id_key="subnet")

    async def subnets_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        subnet = str(payload["subnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        subnets = item.setdefault("subnets", {})
        if subnet in subnets:
            raise ApiError(400, f"subnet '{subnet}' already exists")
        subnets[subnet] = {
            **{k: v for k, v in payload.items() if k not in {"lock-token", "digest"}},
            "subnet": subnet,
        }
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def subnet_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        subnet = str(payload["subnet"])
        _metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        data = (item.get("subnets") or {}).get(subnet)
        if not isinstance(data, dict):
            raise ApiError(404, "subnet does not exist")
        return _public({"subnet": subnet, **data})

    async def subnet_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        subnet = str(payload["subnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        subnets = item.setdefault("subnets", {})
        if subnet not in subnets:
            raise ApiError(404, "subnet does not exist")
        current = dict(subnets[subnet])
        for key in [
            item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
        ]:
            current.pop(key, None)
        for key, value in payload.items():
            if key in {"vnet", "subnet", "delete", "digest", "lock-token"}:
                continue
            current[key] = value
        current["subnet"] = subnet
        subnets[subnet] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def subnet_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        subnet = str(payload["subnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        subnets = item.setdefault("subnets", {})
        if subnet not in subnets:
            raise ApiError(404, "subnet does not exist")
        del subnets[subnet]
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def ips_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        ips = item.setdefault("ips", [])
        if not isinstance(ips, list):
            ips = item["ips"] = []
        ips.append(
            {
                "ip": payload.get("ip"),
                "mac": payload.get("mac"),
                "zone": payload.get("zone"),
                "vmid": payload.get("vmid"),
            }
        )
        await save_cluster_metadata(request, metadata)

    async def ips_update(request: Request, inputs: dict[str, Any]) -> None:
        await ips_create(request, inputs)

    async def ips_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        ips = item.setdefault("ips", [])
        if not isinstance(ips, list):
            return None
        item["ips"] = [
            entry
            for entry in ips
            if not (entry.get("ip") == payload.get("ip") and entry.get("mac") == payload.get("mac"))
        ]
        await save_cluster_metadata(request, metadata)

    async def fw_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await _vnet((await _load(request))[1], str(values(inputs)["vnet"]))
        return subdirs("options", "rules")

    async def fw_options_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        vnet = str(values(inputs)["vnet"])
        _metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        return dict(item.get("firewall", {}).get("options") or {"enable": 0})

    async def fw_options_put(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        options = dict(item.setdefault("firewall", {}).setdefault("options", {"enable": 0}))
        for key, value in payload.items():
            if key in {"vnet", "delete", "digest"}:
                continue
            options[key] = value
        item["firewall"]["options"] = options
        await save_cluster_metadata(request, metadata)

    async def fw_rules_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        vnet = str(values(inputs)["vnet"])
        _metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        rules = item.get("firewall", {}).get("rules") or []
        return list(rules) if isinstance(rules, list) else []

    async def fw_rules_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        rules = item.setdefault("firewall", {}).setdefault("rules", [])
        if not isinstance(rules, list):
            rules = item["firewall"]["rules"] = []
        rule = {k: v for k, v in payload.items() if k not in {"vnet", "pos", "digest"}}
        rule["pos"] = len(rules)
        rules.append(rule)
        await save_cluster_metadata(request, metadata)

    async def fw_rule_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        rules = await fw_rules_list(request, inputs)
        pos = int(values(inputs)["pos"])
        if pos < 0 or pos >= len(rules):
            raise ApiError(404, "firewall rule does not exist")
        return dict(rules[pos])

    async def fw_rule_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        pos = int(payload["pos"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        rules = item.setdefault("firewall", {}).setdefault("rules", [])
        if not isinstance(rules, list) or pos < 0 or pos >= len(rules):
            raise ApiError(404, "firewall rule does not exist")
        rules[pos] = {
            **rules[pos],
            **{k: v for k, v in payload.items() if k not in {"vnet", "pos"}},
        }
        await save_cluster_metadata(request, metadata)

    async def fw_rule_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        vnet = str(payload["vnet"])
        pos = int(payload["pos"])
        metadata, sdn = await _load(request)
        item = await _vnet(sdn, vnet)
        rules = item.setdefault("firewall", {}).setdefault("rules", [])
        if not isinstance(rules, list) or pos < 0 or pos >= len(rules):
            raise ApiError(404, "firewall rule does not exist")
        del rules[pos]
        await save_cluster_metadata(request, metadata)

    # fabrics
    async def fabrics_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("all", "fabric", "node")

    async def fabrics_all(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        _metadata, sdn = await _load(request)
        return _store_list(sdn.get("fabrics") or {}, id_key="id")

    async def fabric_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await fabrics_all(request, inputs)

    async def fabric_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        fabric_id = str(payload["id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("fabrics", {})
        if fabric_id in store:
            raise ApiError(400, f"fabric '{fabric_id}' already exists")
        store[fabric_id] = {
            **{k: v for k, v in payload.items() if k not in {"lock-token", "digest"}},
            "id": fabric_id,
        }
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def fabric_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        fabric_id = str(values(inputs)["id"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("fabrics") or {}).get(fabric_id)
        if not isinstance(item, dict):
            raise ApiError(404, "fabric does not exist")
        return _public({"id": fabric_id, **item})

    async def fabric_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        fabric_id = str(payload["id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("fabrics", {})
        if fabric_id not in store:
            raise ApiError(404, "fabric does not exist")
        current = dict(store[fabric_id])
        for key in [
            item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
        ]:
            current.pop(key, None)
        for key, value in payload.items():
            if key in {"id", "delete", "digest", "lock-token"}:
                continue
            current[key] = value
        current["id"] = fabric_id
        store[fabric_id] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def fabric_delete(request: Request, inputs: dict[str, Any]) -> None:
        fabric_id = str(values(inputs)["id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("fabrics", {})
        if fabric_id not in store:
            raise ApiError(404, "fabric does not exist")
        del store[fabric_id]
        nodes = sdn.setdefault("fabric_nodes", {})
        nodes.pop(fabric_id, None)
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def fabric_nodes_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        _metadata, sdn = await _load(request)
        fabric_id = values(inputs).get("fabric_id")
        nodes = sdn.get("fabric_nodes") or {}
        result: list[dict[str, Any]] = []
        for fid, store in sorted(nodes.items()):
            if fabric_id and fid != fabric_id:
                continue
            if not isinstance(store, dict):
                continue
            for node_id, item in sorted(store.items()):
                result.append(_public({"fabric_id": fid, "node_id": node_id, **item}))
        return result

    async def fabric_node_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        fabric_id = str(payload["fabric_id"])
        node_id = str(payload["node_id"])
        metadata, sdn = await _load(request)
        if fabric_id not in (sdn.get("fabrics") or {}):
            raise ApiError(404, "fabric does not exist")
        store = sdn.setdefault("fabric_nodes", {}).setdefault(fabric_id, {})
        if node_id in store:
            raise ApiError(400, f"fabric node '{node_id}' already exists")
        store[node_id] = {
            **{k: v for k, v in payload.items() if k not in {"lock-token", "digest"}},
            "node_id": node_id,
        }
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def fabric_node_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        fabric_id = str(payload["fabric_id"])
        node_id = str(payload["node_id"])
        _metadata, sdn = await _load(request)
        item = ((sdn.get("fabric_nodes") or {}).get(fabric_id) or {}).get(node_id)
        if not isinstance(item, dict):
            raise ApiError(404, "fabric node does not exist")
        return _public({"fabric_id": fabric_id, "node_id": node_id, **item})

    async def fabric_node_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        fabric_id = str(payload["fabric_id"])
        node_id = str(payload["node_id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("fabric_nodes", {}).setdefault(fabric_id, {})
        if node_id not in store:
            raise ApiError(404, "fabric node does not exist")
        current = dict(store[node_id])
        for key in [
            item.strip() for item in str(payload.get("delete") or "").split(",") if item.strip()
        ]:
            current.pop(key, None)
        for key, value in payload.items():
            if key in {"fabric_id", "node_id", "delete", "digest", "lock-token"}:
                continue
            current[key] = value
        current["node_id"] = node_id
        store[node_id] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def fabric_node_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        fabric_id = str(payload["fabric_id"])
        node_id = str(payload["node_id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("fabric_nodes", {}).setdefault(fabric_id, {})
        if node_id not in store:
            raise ApiError(404, "fabric node does not exist")
        del store[node_id]
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    # prefix lists
    async def prefix_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        _metadata, sdn = await _load(request)
        return _store_list(sdn.get("prefix_lists") or {}, id_key="id")

    async def prefix_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        list_id = str(payload["id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("prefix_lists", {})
        if list_id in store:
            raise ApiError(400, f"prefix-list '{list_id}' already exists")
        store[list_id] = {
            "id": list_id,
            "entries": payload.get("entries") if isinstance(payload.get("entries"), dict) else {},
            "digest": payload.get("digest"),
        }
        if isinstance(payload.get("entries"), list):
            store[list_id]["entries"] = {
                str(index): entry for index, entry in enumerate(payload["entries"])
            }
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def prefix_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        list_id = str(values(inputs)["id"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("prefix_lists") or {}).get(list_id)
        if not isinstance(item, dict):
            raise ApiError(404, "prefix-list does not exist")
        return {"id": list_id, **item}

    async def prefix_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        list_id = str(payload["id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("prefix_lists", {})
        if list_id not in store:
            raise ApiError(404, "prefix-list does not exist")
        current = dict(store[list_id])
        if "entries" in payload:
            current["entries"] = payload["entries"]
        store[list_id] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def prefix_delete(request: Request, inputs: dict[str, Any]) -> None:
        list_id = str(values(inputs)["id"])
        metadata, sdn = await _load(request)
        store = sdn.setdefault("prefix_lists", {})
        if list_id not in store:
            raise ApiError(404, "prefix-list does not exist")
        del store[list_id]
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def prefix_entries(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        list_id = str(values(inputs)["id"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("prefix_lists") or {}).get(list_id)
        if not isinstance(item, dict):
            raise ApiError(404, "prefix-list does not exist")
        entries = item.get("entries") or {}
        if isinstance(entries, dict):
            return [{"seq": key, **value} for key, value in sorted(entries.items())]
        return list(entries) if isinstance(entries, list) else []

    async def prefix_entry_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        list_id = str(payload["id"])
        seq = str(payload.get("seq") or secrets.randbelow(10000))
        metadata, sdn = await _load(request)
        item = (sdn.get("prefix_lists") or {}).get(list_id)
        if not isinstance(item, dict):
            raise ApiError(404, "prefix-list does not exist")
        entries = item.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = item["entries"] = {}
        entries[seq] = {
            "seq": seq,
            "action": payload.get("action"),
            "prefix": payload.get("prefix"),
            "ge": payload.get("ge"),
            "le": payload.get("le"),
        }
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def prefix_entry_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        list_id = str(payload["id"])
        seq = str(payload["url_seq"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("prefix_lists") or {}).get(list_id)
        if not isinstance(item, dict):
            raise ApiError(404, "prefix-list does not exist")
        entry = (item.get("entries") or {}).get(seq)
        if not isinstance(entry, dict):
            raise ApiError(404, "prefix-list entry does not exist")
        return {"seq": seq, **entry}

    async def prefix_entry_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        list_id = str(payload["id"])
        seq = str(payload["url_seq"])
        metadata, sdn = await _load(request)
        item = (sdn.get("prefix_lists") or {}).get(list_id)
        if not isinstance(item, dict):
            raise ApiError(404, "prefix-list does not exist")
        entries = item.setdefault("entries", {})
        if seq not in entries:
            raise ApiError(404, "prefix-list entry does not exist")
        current = dict(entries[seq])
        for key in ("action", "prefix", "ge", "le", "seq"):
            if key in payload:
                current[key] = payload[key]
        entries[seq] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def prefix_entry_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        list_id = str(payload["id"])
        seq = str(payload["url_seq"])
        metadata, sdn = await _load(request)
        item = (sdn.get("prefix_lists") or {}).get(list_id)
        if not isinstance(item, dict):
            raise ApiError(404, "prefix-list does not exist")
        entries = item.setdefault("entries", {})
        if seq not in entries:
            raise ApiError(404, "prefix-list entry does not exist")
        del entries[seq]
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    # route maps
    async def route_maps_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("entries")

    async def route_entries_list(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        _metadata, sdn = await _load(request)
        maps = sdn.get("route_maps") or {}
        route_map_id = values(inputs).get("route-map-id")
        result: list[dict[str, Any]] = []
        for map_id, entries in sorted(maps.items()):
            if route_map_id and map_id != route_map_id:
                continue
            if not isinstance(entries, dict):
                continue
            for order, entry in sorted(entries.items(), key=lambda pair: int(pair[0])):
                result.append({"route-map-id": map_id, "order": int(order), **entry})
        return result

    async def route_entry_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        map_id = str(payload["route-map-id"])
        order = str(payload.get("order") or 10)
        metadata, sdn = await _load(request)
        entries = sdn.setdefault("route_maps", {}).setdefault(map_id, {})
        if order in entries:
            raise ApiError(400, f"route-map entry '{order}' already exists")
        entries[order] = {
            k: v for k, v in payload.items() if k not in {"lock-token", "digest", "route-map-id"}
        }
        entries[order]["order"] = int(order)
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def route_map_entries(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await route_entries_list(
            request,
            {
                "values": {"route-map-id": values(inputs)["route-map-id"]},
                "provided": frozenset(),
            },
        )

    async def route_entry_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        map_id = str(payload["route-map-id"])
        order = str(payload["order"])
        _metadata, sdn = await _load(request)
        entry = ((sdn.get("route_maps") or {}).get(map_id) or {}).get(order)
        if not isinstance(entry, dict):
            raise ApiError(404, "route-map entry does not exist")
        return {"route-map-id": map_id, "order": int(order), **entry}

    async def route_entry_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        map_id = str(payload["route-map-id"])
        order = str(payload["order"])
        metadata, sdn = await _load(request)
        entries = sdn.setdefault("route_maps", {}).setdefault(map_id, {})
        if order not in entries:
            raise ApiError(404, "route-map entry does not exist")
        current = dict(entries[order])
        for key, value in payload.items():
            if key in {"route-map-id", "order", "delete", "digest", "lock-token"}:
                continue
            current[key] = value
        current["order"] = int(order)
        entries[order] = current
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    async def route_entry_delete(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        map_id = str(payload["route-map-id"])
        order = str(payload["order"])
        metadata, sdn = await _load(request)
        entries = sdn.setdefault("route_maps", {}).setdefault(map_id, {})
        if order not in entries:
            raise ApiError(404, "route-map entry does not exist")
        del entries[order]
        sdn["pending"] = True
        await save_cluster_metadata(request, metadata)

    # node sdn surfaces
    async def node_sdn_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await require_node(request, str(values(inputs)["node"]))
        return subdirs("fabrics", "vnets", "zones")

    async def node_zones(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        _metadata, sdn = await _load(request)
        return _store_list(sdn.get("zones") or {}, id_key="zone")

    async def node_zone(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        await require_node(request, str(values(inputs)["node"]))
        zone = str(values(inputs)["zone"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("zones") or {}).get(zone)
        if not isinstance(item, dict):
            raise ApiError(404, "zone does not exist")
        return _public({"zone": zone, **item})

    async def node_zone_bridges(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        zone = await node_zone(request, inputs)
        bridge = zone.get("bridge") or f"vmbr-{zone.get('zone')}"
        return [{"iface": bridge, "active": 1}]

    async def node_zone_content(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        zone = str(values(inputs)["zone"])
        _metadata, sdn = await _load(request)
        return [
            {"vnet": name, **item}
            for name, item in sorted((sdn.get("vnets") or {}).items())
            if item.get("zone") == zone
        ]

    async def node_zone_ip_vrf(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        zone = await node_zone(request, inputs)
        return {"zone": zone.get("zone"), "vrf": f"vrf-{zone.get('zone')}", "table": 100}

    async def node_vnet(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        await require_node(request, str(values(inputs)["node"]))
        return await vnet_get(request, inputs)

    async def node_vnet_mac_vrf(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        vnet = await node_vnet(request, inputs)
        return {"vnet": vnet.get("vnet"), "mac-vrf": f"macvrf-{vnet.get('vnet')}"}

    async def node_fabric(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        await require_node(request, str(values(inputs)["node"]))
        fabric = str(values(inputs)["fabric"])
        return await fabric_get(request, {"values": {"id": fabric}, "provided": frozenset()})

    async def node_fabric_interfaces(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        fabric = str(values(inputs)["fabric"])
        _metadata, sdn = await _load(request)
        nodes = (sdn.get("fabric_nodes") or {}).get(fabric) or {}
        result = []
        for node_id, item in nodes.items():
            ifaces = item.get("interfaces") or []
            if isinstance(ifaces, str):
                ifaces = [part.strip() for part in ifaces.split(",") if part.strip()]
            for iface in ifaces:
                result.append({"node": node_id, "iface": iface})
        return result

    async def node_fabric_neighbors(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        fabric = str(values(inputs)["fabric"])
        _metadata, sdn = await _load(request)
        nodes = (sdn.get("fabric_nodes") or {}).get(fabric) or {}
        return [{"node": node_id, "state": "up"} for node_id in sorted(nodes)]

    async def node_fabric_routes(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        await require_node(request, str(values(inputs)["node"]))
        fabric = str(values(inputs)["fabric"])
        _metadata, sdn = await _load(request)
        item = (sdn.get("fabrics") or {}).get(fabric) or {}
        prefix = item.get("ip_prefix") or "10.0.0.0/24"
        return [{"dst": prefix, "protocol": item.get("protocol") or "ospf"}]

    # registrations
    registry.register("/cluster/sdn", "GET", index)
    registry.register("/cluster/sdn", "PUT", apply)
    registry.register("/cluster/sdn/lock", "POST", lock_create)
    registry.register("/cluster/sdn/lock", "DELETE", lock_delete)
    registry.register("/cluster/sdn/rollback", "POST", rollback)
    registry.register("/cluster/sdn/dry-run", "GET", dry_run)
    registry.register("/cluster/sdn/ipams/{ipam}/status", "GET", ipam_status)

    registry.register("/cluster/sdn/vnets", "GET", vnets_list)
    registry.register("/cluster/sdn/vnets", "POST", vnets_create)
    registry.register("/cluster/sdn/vnets/{vnet}", "GET", vnet_get)
    registry.register("/cluster/sdn/vnets/{vnet}", "PUT", vnet_update)
    registry.register("/cluster/sdn/vnets/{vnet}", "DELETE", vnet_delete)
    registry.register("/cluster/sdn/vnets/{vnet}/subnets", "GET", subnets_list)
    registry.register("/cluster/sdn/vnets/{vnet}/subnets", "POST", subnets_create)
    registry.register("/cluster/sdn/vnets/{vnet}/subnets/{subnet}", "GET", subnet_get)
    registry.register("/cluster/sdn/vnets/{vnet}/subnets/{subnet}", "PUT", subnet_update)
    registry.register("/cluster/sdn/vnets/{vnet}/subnets/{subnet}", "DELETE", subnet_delete)
    registry.register("/cluster/sdn/vnets/{vnet}/ips", "POST", ips_create)
    registry.register("/cluster/sdn/vnets/{vnet}/ips", "PUT", ips_update)
    registry.register("/cluster/sdn/vnets/{vnet}/ips", "DELETE", ips_delete)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall", "GET", fw_index)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/options", "GET", fw_options_get)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/options", "PUT", fw_options_put)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/rules", "GET", fw_rules_list)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/rules", "POST", fw_rules_create)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/rules/{pos}", "GET", fw_rule_get)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/rules/{pos}", "PUT", fw_rule_update)
    registry.register("/cluster/sdn/vnets/{vnet}/firewall/rules/{pos}", "DELETE", fw_rule_delete)

    registry.register("/cluster/sdn/fabrics", "GET", fabrics_index)
    registry.register("/cluster/sdn/fabrics/all", "GET", fabrics_all)
    registry.register("/cluster/sdn/fabrics/fabric", "GET", fabric_list)
    registry.register("/cluster/sdn/fabrics/fabric", "POST", fabric_create)
    registry.register("/cluster/sdn/fabrics/fabric/{id}", "GET", fabric_get)
    registry.register("/cluster/sdn/fabrics/fabric/{id}", "PUT", fabric_update)
    registry.register("/cluster/sdn/fabrics/fabric/{id}", "DELETE", fabric_delete)
    registry.register("/cluster/sdn/fabrics/node", "GET", fabric_nodes_list)
    registry.register("/cluster/sdn/fabrics/node/{fabric_id}", "GET", fabric_nodes_list)
    registry.register("/cluster/sdn/fabrics/node/{fabric_id}", "POST", fabric_node_create)
    registry.register("/cluster/sdn/fabrics/node/{fabric_id}/{node_id}", "GET", fabric_node_get)
    registry.register("/cluster/sdn/fabrics/node/{fabric_id}/{node_id}", "PUT", fabric_node_update)
    registry.register(
        "/cluster/sdn/fabrics/node/{fabric_id}/{node_id}", "DELETE", fabric_node_delete
    )

    registry.register("/cluster/sdn/prefix-lists", "GET", prefix_list)
    registry.register("/cluster/sdn/prefix-lists", "POST", prefix_create)
    registry.register("/cluster/sdn/prefix-lists/{id}", "GET", prefix_get)
    registry.register("/cluster/sdn/prefix-lists/{id}", "PUT", prefix_update)
    registry.register("/cluster/sdn/prefix-lists/{id}", "DELETE", prefix_delete)
    registry.register("/cluster/sdn/prefix-lists/{id}/entries", "GET", prefix_entries)
    registry.register("/cluster/sdn/prefix-lists/{id}/entries", "POST", prefix_entry_create)
    registry.register("/cluster/sdn/prefix-lists/{id}/entries/{url_seq}", "GET", prefix_entry_get)
    registry.register(
        "/cluster/sdn/prefix-lists/{id}/entries/{url_seq}", "PUT", prefix_entry_update
    )
    registry.register(
        "/cluster/sdn/prefix-lists/{id}/entries/{url_seq}", "DELETE", prefix_entry_delete
    )

    registry.register("/cluster/sdn/route-maps", "GET", route_maps_index)
    registry.register("/cluster/sdn/route-maps/entries", "GET", route_entries_list)
    registry.register("/cluster/sdn/route-maps/entries", "POST", route_entry_create)
    registry.register("/cluster/sdn/route-maps/entries/{route-map-id}", "GET", route_map_entries)
    registry.register(
        "/cluster/sdn/route-maps/entries/{route-map-id}/entry/{order}",
        "GET",
        route_entry_get,
    )
    registry.register(
        "/cluster/sdn/route-maps/entries/{route-map-id}/entry/{order}",
        "PUT",
        route_entry_update,
    )
    registry.register(
        "/cluster/sdn/route-maps/entries/{route-map-id}/entry/{order}",
        "DELETE",
        route_entry_delete,
    )

    registry.register("/nodes/{node}/sdn", "GET", node_sdn_index)
    registry.register("/nodes/{node}/sdn/zones", "GET", node_zones)
    registry.register("/nodes/{node}/sdn/zones/{zone}", "GET", node_zone)
    registry.register("/nodes/{node}/sdn/zones/{zone}/bridges", "GET", node_zone_bridges)
    registry.register("/nodes/{node}/sdn/zones/{zone}/content", "GET", node_zone_content)
    registry.register("/nodes/{node}/sdn/zones/{zone}/ip-vrf", "GET", node_zone_ip_vrf)
    registry.register("/nodes/{node}/sdn/vnets/{vnet}", "GET", node_vnet)
    registry.register("/nodes/{node}/sdn/vnets/{vnet}/mac-vrf", "GET", node_vnet_mac_vrf)
    registry.register("/nodes/{node}/sdn/fabrics/{fabric}", "GET", node_fabric)
    registry.register(
        "/nodes/{node}/sdn/fabrics/{fabric}/interfaces", "GET", node_fabric_interfaces
    )
    registry.register("/nodes/{node}/sdn/fabrics/{fabric}/neighbors", "GET", node_fabric_neighbors)
    registry.register("/nodes/{node}/sdn/fabrics/{fabric}/routes", "GET", node_fabric_routes)
