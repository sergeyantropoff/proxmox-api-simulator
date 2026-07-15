"""Remaining LXC console / RRD / volume helpers with durable state."""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

from fastapi import Request

from app.api.registry import HandlerRegistry
from app.config import Settings
from app.handlers.lxc import _database, _lxc_resource, _state, _values
from app.security.auth import issue_ticket


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def _save_state(request: Request, resource_id: Any, state: dict[str, Any]) -> None:
    await _database(request).pool.execute(
        "UPDATE resources SET state=$2::jsonb, version=version+1, updated_at=now() WHERE id=$1",
        resource_id,
        json.dumps(state, sort_keys=True),
    )


async def _save_config(request: Request, resource_id: Any, config: dict[str, Any]) -> None:
    await _database(request).pool.execute(
        "UPDATE containers SET config=$2::jsonb WHERE resource_id=$1",
        resource_id,
        json.dumps(config, sort_keys=True),
    )


def register_lxc_extra_handlers(registry: HandlerRegistry) -> None:
    async def interfaces(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        ifaces = state.setdefault(
            "interfaces",
            [{"name": "eth0", "hwaddr": "02:00:00:00:00:11", "inet": "192.0.2.20/24"}],
        )
        await _save_state(request, resource["id"], state)
        return list(ifaces) if isinstance(ifaces, list) else []

    async def move_volume(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        volume = str(values.get("volume") or values.get("disk") or "rootfs")
        storage = str(values.get("storage") or "local-lvm")
        config = _state(resource["config"])
        current = str(config.get(volume) or "")
        if current:
            # rewrite storage prefix when present
            rest = current.split(":", 1)[1] if ":" in current else current
            config[volume] = f"{storage}:{rest}"
            await _save_config(request, resource["id"], config)
        state = _state(resource["state"])
        moves = state.setdefault("volume_moves", [])
        if not isinstance(moves, list):
            moves = state["volume_moves"] = []
        moves.append({"volume": volume, "storage": storage})
        await _save_state(request, resource["id"], state)
        return f"UPID:{values['node']}:lxc-move-volume:{values['vmid']}"

    async def rrd(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        rrd_state = state.setdefault("rrd", {"filename": f"pve-ct-{values['vmid']}.rrd"})
        await _save_state(request, resource["id"], state)
        return dict(rrd_state)

    async def rrddata(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        series = state.setdefault(
            "rrddata",
            [
                {"time": 1_700_000_000, "cpu": 0.02, "mem": 64 * 1024 * 1024},
                {"time": 1_700_000_060, "cpu": 0.03, "mem": 66 * 1024 * 1024},
            ],
        )
        await _save_state(request, resource["id"], state)
        return list(series)

    async def _console(request: Request, inputs: dict[str, Any], kind: str) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        key = _settings(request).ticket_signing_key.get_secret_value().encode()
        ticket = issue_ticket(str(request.state.principal), key)
        port = 6900 + int(values["vmid"]) % 1000
        state = _state(resource["state"])
        consoles = state.setdefault("consoles", {})
        payload = {
            "type": kind,
            "port": port,
            "ticket": ticket,
            "upid": (
                f"UPID:{values['node']}:{secrets.token_hex(4)}:"
                f"{kind}:{values['vmid']}:{request.state.principal}:"
            ),
            "user": str(request.state.principal),
        }
        consoles[kind] = {k: v for k, v in payload.items() if k != "ticket"}
        await _save_state(request, resource["id"], state)
        return payload

    async def vncproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console(request, inputs, "vnc")

    async def spiceproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console(request, inputs, "spice")

    async def termproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console(request, inputs, "term")

    async def mtunnel(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console(request, inputs, "mtunnel")

    async def _ws(request: Request, inputs: dict[str, Any], kind: str) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _lxc_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        console = state.get("consoles", {}).get(kind) or {"port": 6900}
        key = _settings(request).ticket_signing_key.get_secret_value().encode()
        return {
            "port": console.get("port", 6900),
            "ticket": issue_ticket(str(request.state.principal), key),
        }

    async def vncwebsocket(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _ws(request, inputs, "vnc")

    async def mtunnelwebsocket(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _ws(request, inputs, "mtunnel")

    base = "/nodes/{node}/lxc/{vmid}"
    registry.register(f"{base}/interfaces", "GET", interfaces)
    registry.register(f"{base}/move_volume", "POST", move_volume)
    registry.register(f"{base}/rrd", "GET", rrd)
    registry.register(f"{base}/rrddata", "GET", rrddata)
    registry.register(f"{base}/vncproxy", "POST", vncproxy)
    registry.register(f"{base}/spiceproxy", "POST", spiceproxy)
    registry.register(f"{base}/termproxy", "POST", termproxy)
    registry.register(f"{base}/mtunnel", "POST", mtunnel)
    registry.register(f"{base}/vncwebsocket", "GET", vncwebsocket)
    registry.register(f"{base}/mtunnelwebsocket", "GET", mtunnelwebsocket)
