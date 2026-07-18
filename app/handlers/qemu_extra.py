"""Additional QEMU guest/agent/console endpoints with durable guest state."""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from typing import Any, cast

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.config import Settings
from app.handlers.qemu import _agent_resource, _database, _qemu_resource, _state, _values
from app.security.auth import issue_ticket


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def _save_guest_state(request: Request, resource_id: Any, state: dict[str, Any]) -> None:
    await _database(request).pool.execute(
        "UPDATE resources SET state=$2::jsonb, version=version+1, updated_at=now() WHERE id=$1",
        resource_id,
        json.dumps(state, sort_keys=True),
    )


async def _save_guest_config(request: Request, resource_id: Any, config: dict[str, Any]) -> None:
    await _database(request).pool.execute(
        "UPDATE virtual_machines SET config=$2::jsonb WHERE resource_id=$1",
        resource_id,
        json.dumps(config, sort_keys=True),
    )


def register_qemu_extra_handlers(registry: HandlerRegistry) -> None:
    async def agent_index(request: Request, inputs: dict[str, Any]) -> list[dict[str, str]]:
        await _agent_resource(request, _values(inputs))
        return [
            {"name": name}
            for name in (
                "exec",
                "exec-status",
                "file-read",
                "file-write",
                "fsfreeze-freeze",
                "fsfreeze-status",
                "fsfreeze-thaw",
                "fstrim",
                "get-fsinfo",
                "get-memory-block-info",
                "get-memory-blocks",
                "get-timezone",
                "get-users",
                "get-vcpus",
                "info",
                "ping",
                "set-user-password",
                "shutdown",
                "suspend-disk",
                "suspend-hybrid",
                "suspend-ram",
            )
        ]

    async def agent_post(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        command = str(payload.get("command") or "ping")
        resource = await _agent_resource(request, payload)
        state = _state(resource["state"])
        agent = state.setdefault("agent", {})
        agent["last_command"] = command
        await _save_guest_state(request, resource["id"], state)
        return {"result": {"command": command, "ok": 1}}

    async def _agent_blob(command: str, request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        resource = await _agent_resource(request, _values(inputs))
        state = _state(resource["state"])
        agent = state.get("agent")
        blobs = agent.get("results") if isinstance(agent, dict) else None
        if not isinstance(blobs, dict) or command not in blobs:
            raise ApiError(404, f"agent command '{command}' has no stored result")
        return {"result": blobs[command]}

    async def agent_users(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("get-users", request, inputs)

    async def agent_fsinfo(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("get-fsinfo", request, inputs)

    async def agent_memory_block_info(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("get-memory-block-info", request, inputs)

    async def agent_memory_blocks(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("get-memory-blocks", request, inputs)

    async def agent_timezone(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("get-timezone", request, inputs)

    async def agent_vcpus(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("get-vcpus", request, inputs)

    async def agent_exec(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        resource = await _agent_resource(request, payload)
        state = _state(resource["state"])
        agent = state.setdefault("agent", {})
        execs = agent.setdefault("exec", {})
        pid = int(agent.get("next_pid", 1000)) + 1
        agent["next_pid"] = pid
        execs[str(pid)] = {
            "exited": 1,
            "exitcode": 0,
            "out-data": "",
            "err-data": "",
            "command": payload.get("command"),
        }
        await _save_guest_state(request, resource["id"], state)
        return {"pid": pid}

    async def agent_exec_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        resource = await _agent_resource(request, payload)
        pid = str(payload.get("pid") or "")
        state = _state(resource["state"])
        result = state.get("agent", {}).get("exec", {}).get(pid)
        if not isinstance(result, dict):
            raise ApiError(404, "exec process does not exist")
        return {"result": result}

    async def agent_file_read(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        resource = await _agent_resource(request, payload)
        path = str(payload.get("file") or payload.get("path") or "/etc/hostname")
        state = _state(resource["state"])
        agent = state.get("agent")
        files = agent.get("files") if isinstance(agent, dict) else None
        if not isinstance(files, dict) or path not in files:
            raise ApiError(404, "file does not exist")
        content = str(files[path])
        return {"result": {"content": content, "truncated": True}}

    async def agent_file_write(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        resource = await _agent_resource(request, payload)
        default_path = "guest-agent-out"
        path = str(payload.get("file") or payload.get("path") or default_path)
        content = str(payload.get("content") or "")
        state = _state(resource["state"])
        files = state.setdefault("agent", {}).setdefault("files", {})
        files[path] = content
        await _save_guest_state(request, resource["id"], state)
        return {"result": None}

    async def agent_fsfreeze(
        request: Request, inputs: dict[str, Any], status: str
    ) -> dict[str, Any]:
        resource = await _agent_resource(request, _values(inputs))
        state = _state(resource["state"])
        agent = state.setdefault("agent", {})
        agent["fsfreeze"] = status
        agent.setdefault("results", {})["fsfreeze-status"] = status
        await _save_guest_state(request, resource["id"], state)
        return {"result": status}

    async def agent_fsfreeze_freeze(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_fsfreeze(request, inputs, "frozen")

    async def agent_fsfreeze_thaw(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_fsfreeze(request, inputs, "thawed")

    async def agent_fsfreeze_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _agent_blob("fsfreeze-status", request, inputs)

    async def agent_fstrim(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        resource = await _agent_resource(request, _values(inputs))
        state = _state(resource["state"])
        agent = dict(state.get("agent") or {})
        agent["last_fstrim"] = True
        state["agent"] = agent
        await _save_guest_state(request, resource["id"], state)
        results = agent.get("results") if isinstance(agent.get("results"), dict) else {}
        fstrim = results.get("fstrim") if isinstance(results, dict) else None
        if isinstance(fstrim, dict):
            return {"result": fstrim}
        return {"result": {}}

    async def agent_set_password(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = _values(inputs)
        resource = await _agent_resource(request, payload)
        username = str(payload.get("username") or "root")
        state = _state(resource["state"])
        passwords = state.setdefault("agent", {}).setdefault("passwords", {})
        passwords[username] = True  # store only presence, not secret
        await _save_guest_state(request, resource["id"], state)
        return {"result": None}

    async def agent_shutdown(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        resource = await _agent_resource(request, _values(inputs))
        state = _state(resource["state"])
        state["status"] = "stopped"
        await _save_guest_state(request, resource["id"], state)
        return {"result": None}

    async def agent_suspend(request: Request, inputs: dict[str, Any], mode: str) -> dict[str, Any]:
        resource = await _agent_resource(request, _values(inputs))
        state = _state(resource["state"])
        state["status"] = "paused"
        state.setdefault("agent", {})["suspend"] = mode
        await _save_guest_state(request, resource["id"], state)
        return {"result": None}

    async def agent_suspend_disk(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_suspend(request, inputs, "disk")

    async def agent_suspend_ram(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_suspend(request, inputs, "ram")

    async def agent_suspend_hybrid(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await agent_suspend(request, inputs, "hybrid")

    async def cloudinit_get(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        config = _state(resource["config"])
        state = _state(resource["state"])
        pending = cast(Mapping[str, Any], state.get("pending", {}))
        keys = sorted(
            {
                key
                for key in set(config) | set(pending)
                if str(key).startswith(("ci", "ipconfig", "sshkeys", "nameserver", "searchdomain"))
            }
        )
        return [
            {
                "key": key,
                "value": str(config.get(key, "")),
                "pending": str(pending[key]) if key in pending else None,
            }
            for key in keys
        ]

    async def cloudinit_update(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        state["cloudinit_generation"] = int(state.get("cloudinit_generation") or 0) + 1
        await _save_guest_state(request, resource["id"], state)

    async def cloudinit_dump(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        dump = state.get("cloudinit_dump")
        return str(dump) if dump is not None else ""

    async def rrd(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        rrd_state = state.get("rrd")
        return dict(rrd_state) if isinstance(rrd_state, dict) else {}

    async def rrddata(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        series = state.get("rrddata")
        return [dict(item) for item in series] if isinstance(series, list) else []

    async def monitor(request: Request, inputs: dict[str, Any]) -> str:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        command = str(values.get("command") or "info status")
        state = _state(resource["state"])
        history = state.setdefault("monitor", [])
        if not isinstance(history, list):
            history = state["monitor"] = []
        output = f"OK {command}"
        history.append({"command": command, "output": output})
        await _save_guest_state(request, resource["id"], state)
        return output

    async def sendkey(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        key = str(values.get("key") or "")
        if not key:
            raise ApiError(400, "parameter verification failed - 'key' missing")
        state = _state(resource["state"])
        keys = state.setdefault("sendkey", [])
        if not isinstance(keys, list):
            keys = state["sendkey"] = []
        keys.append(key)
        await _save_guest_state(request, resource["id"], state)

    async def unlink(request: Request, inputs: dict[str, Any]) -> None:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        idlist = [
            item.strip()
            for item in str(values.get("idlist") or values.get("ids") or "").split(",")
            if item.strip()
        ]
        if not idlist:
            raise ApiError(400, "parameter verification failed - 'idlist' missing")
        config = _state(resource["config"])
        for disk in idlist:
            config.pop(disk, None)
        await _save_guest_config(request, resource["id"], config)
        state = _state(resource["state"])
        state["config"] = config
        await _save_guest_state(request, resource["id"], state)

    async def _console_proxy(request: Request, inputs: dict[str, Any], kind: str) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        key = _settings(request).ticket_signing_key.get_secret_value().encode()
        ticket = issue_ticket(str(request.state.principal), key)
        port = 5900 + int(values["vmid"]) % 1000
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
            "cert": "",
        }
        if values.get("generate-password") or values.get("websocket"):
            payload["password"] = secrets.token_urlsafe(8)
        consoles[kind] = {k: v for k, v in payload.items() if k != "ticket"}
        await _save_guest_state(request, resource["id"], state)
        return payload

    async def vncproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console_proxy(request, inputs, "vnc")

    async def spiceproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console_proxy(request, inputs, "spice")

    async def termproxy(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console_proxy(request, inputs, "term")

    async def mtunnel(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await _console_proxy(request, inputs, "mtunnel")

    async def websocket_ticket(
        request: Request, inputs: dict[str, Any], kind: str
    ) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        console = state.get("consoles", {}).get(kind) or {"port": 5900}
        key = _settings(request).ticket_signing_key.get_secret_value().encode()
        return {
            "port": console.get("port", 5900),
            "ticket": issue_ticket(str(request.state.principal), key),
        }

    async def vncwebsocket(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await websocket_ticket(request, inputs, "vnc")

    async def mtunnelwebsocket(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        return await websocket_ticket(request, inputs, "mtunnel")

    async def dbus_vmstate(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        values = _values(inputs)
        resource = await _qemu_resource(request, str(values["node"]), str(values["vmid"]))
        state = _state(resource["state"])
        state["dbus_vmstate"] = True
        await _save_guest_state(request, resource["id"], state)
        return {"result": "OK"}

    base = "/nodes/{node}/qemu/{vmid}"
    registry.register(f"{base}/agent", "GET", agent_index)
    registry.register(f"{base}/agent", "POST", agent_post)
    registry.register(f"{base}/agent/exec", "POST", agent_exec)
    registry.register(f"{base}/agent/exec-status", "GET", agent_exec_status)
    registry.register(f"{base}/agent/file-read", "GET", agent_file_read)
    registry.register(f"{base}/agent/file-write", "POST", agent_file_write)
    registry.register(f"{base}/agent/fsfreeze-freeze", "POST", agent_fsfreeze_freeze)
    registry.register(f"{base}/agent/fsfreeze-status", "POST", agent_fsfreeze_status)
    registry.register(f"{base}/agent/fsfreeze-thaw", "POST", agent_fsfreeze_thaw)
    registry.register(f"{base}/agent/fstrim", "POST", agent_fstrim)
    registry.register(f"{base}/agent/get-fsinfo", "GET", agent_fsinfo)
    registry.register(f"{base}/agent/get-memory-block-info", "GET", agent_memory_block_info)
    registry.register(f"{base}/agent/get-memory-blocks", "GET", agent_memory_blocks)
    registry.register(f"{base}/agent/get-timezone", "GET", agent_timezone)
    registry.register(f"{base}/agent/get-users", "GET", agent_users)
    registry.register(f"{base}/agent/get-vcpus", "GET", agent_vcpus)
    registry.register(f"{base}/agent/set-user-password", "POST", agent_set_password)
    registry.register(f"{base}/agent/shutdown", "POST", agent_shutdown)
    registry.register(f"{base}/agent/suspend-disk", "POST", agent_suspend_disk)
    registry.register(f"{base}/agent/suspend-hybrid", "POST", agent_suspend_hybrid)
    registry.register(f"{base}/agent/suspend-ram", "POST", agent_suspend_ram)
    registry.register(f"{base}/cloudinit", "GET", cloudinit_get)
    registry.register(f"{base}/cloudinit", "PUT", cloudinit_update)
    registry.register(f"{base}/cloudinit/dump", "GET", cloudinit_dump)
    registry.register(f"{base}/rrd", "GET", rrd)
    registry.register(f"{base}/rrddata", "GET", rrddata)
    registry.register(f"{base}/monitor", "POST", monitor)
    registry.register(f"{base}/sendkey", "PUT", sendkey)
    registry.register(f"{base}/unlink", "PUT", unlink)
    registry.register(f"{base}/vncproxy", "POST", vncproxy)
    registry.register(f"{base}/spiceproxy", "POST", spiceproxy)
    registry.register(f"{base}/termproxy", "POST", termproxy)
    registry.register(f"{base}/mtunnel", "POST", mtunnel)
    registry.register(f"{base}/vncwebsocket", "GET", vncwebsocket)
    registry.register(f"{base}/mtunnelwebsocket", "GET", mtunnelwebsocket)
    registry.register(f"{base}/dbus-vmstate", "POST", dbus_vmstate)
