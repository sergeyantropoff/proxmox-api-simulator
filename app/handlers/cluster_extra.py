"""Additional cluster-level handlers with durable metadata persistence."""

from __future__ import annotations

import copy
import secrets
import time
from typing import Any

from fastapi import Request

from app.api.errors import ApiError
from app.api.registry import HandlerRegistry
from app.handlers.common import (
    cluster_metadata,
    database,
    require_node,
    save_cluster_metadata,
    subdirs,
    values,
)
from app.tasks.repository import TaskRepository
from app.tasks.upid import Upid

DEFAULT_CEPH_FLAGS: dict[str, int] = {
    "nobackfill": 0,
    "nodeep-scrub": 0,
    "nodown": 0,
    "noin": 0,
    "noout": 0,
    "norebalance": 0,
    "norecover": 0,
    "noscrub": 0,
    "notieragent": 0,
    "pause": 0,
}

DEFAULT_CPU_FLAGS: list[dict[str, Any]] = [
    {"name": "aes", "introduces": "Westmere"},
    {"name": "avx", "introduces": "SandyBridge"},
    {"name": "avx2", "introduces": "Haswell"},
]


def _jobs(metadata: dict[str, Any]) -> dict[str, Any]:
    jobs = metadata.setdefault("jobs", {})
    if not isinstance(jobs, dict):
        jobs = {}
        metadata["jobs"] = jobs
    sync = jobs.setdefault("realm_sync", {})
    if not isinstance(sync, dict):
        sync = {}
        jobs["realm_sync"] = sync
    return jobs


def _metrics(metadata: dict[str, Any]) -> dict[str, Any]:
    metrics = metadata.setdefault("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
        metadata["metrics"] = metrics
    servers = metrics.setdefault("servers", {})
    if not isinstance(servers, dict):
        servers = {}
        metrics["servers"] = servers
    return metrics


def _cpu_models(metadata: dict[str, Any]) -> dict[str, Any]:
    models = metadata.get("qemu_cpu_models")
    if not isinstance(models, dict):
        models = {}
        metadata["qemu_cpu_models"] = models
    return models


def _ha_rules_store(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rules = metadata.get("ha_rules")
    if isinstance(rules, dict):
        return [
            {"rule": str(name), **dict(value)}
            for name, value in rules.items()
            if isinstance(value, dict)
        ]
    if isinstance(rules, list):
        return [dict(item) for item in rules if isinstance(item, dict)]
    defaults = [
        {"rule": "node-fencing", "type": "node", "action": "restart"},
        {"rule": "service-ha", "type": "resource", "action": "failover"},
    ]
    metadata["ha_rules"] = defaults
    return list(defaults)


def _save_ha_rules(metadata: dict[str, Any], rules: list[dict[str, Any]]) -> None:
    metadata["ha_rules"] = rules


def _replication_jobs(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = metadata.get("replication", [])
    if not isinstance(jobs, list):
        return []
    return [dict(item) for item in jobs if isinstance(item, dict)]


def _ceph(metadata: dict[str, Any]) -> dict[str, Any]:
    ceph = metadata.get("ceph")
    if not isinstance(ceph, dict):
        ceph = {}
    flags = ceph.get("flags")
    if not isinstance(flags, dict):
        flags = copy.deepcopy(DEFAULT_CEPH_FLAGS)
    else:
        merged = copy.deepcopy(DEFAULT_CEPH_FLAGS)
        merged.update({str(key): int(value) for key, value in flags.items()})
        flags = merged
    ceph["flags"] = flags
    metadata["ceph"] = ceph
    return ceph


async def _cluster_task(request: Request, *, task_type: str, worker: str) -> str:
    from app.db.primitives import ConflictError

    pool = database(request).pool
    node = await pool.fetchval("SELECT name FROM nodes ORDER BY name LIMIT 1") or "localhost"
    upid = str(Upid.allocate(str(node), worker, "0", str(request.state.principal)))
    try:
        task = await TaskRepository(pool).create(
            upid=upid,
            task_type=task_type,
            payload={"cluster": True},
            resource_key=f"cluster:{task_type}:{secrets.token_hex(4)}",
        )
    except ConflictError as error:
        raise ApiError(409, str(error)) from error
    return task.upid


async def _bulk_guest_status(request: Request, status: str) -> None:
    await database(request).pool.execute(
        """UPDATE resources
        SET state = jsonb_set(COALESCE(state, '{}'::jsonb), '{status}', to_jsonb($1::text), true),
            updated_at=now()
        WHERE kind IN ('qemu', 'lxc')""",
        status,
    )


def register_cluster_extra_handlers(registry: HandlerRegistry) -> None:
    async def jobs_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("realm-sync", "schedule-analyze")

    async def realm_sync_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        jobs = _jobs(metadata)
        items = [
            {"id": job_id, **dict(payload)}
            for job_id, payload in sorted(jobs.get("realm_sync", {}).items())
            if isinstance(payload, dict)
        ]
        return items

    async def realm_sync_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _jobs(metadata)
        payload = jobs.get("realm_sync", {}).get(job_id)
        if not isinstance(payload, dict):
            raise ApiError(404, "realm-sync job does not exist")
        return {"id": job_id, **payload}

    async def realm_sync_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        job_id = str(payload["id"])
        metadata = await cluster_metadata(request)
        jobs = _jobs(metadata)
        sync = jobs.setdefault("realm_sync", {})
        if job_id in sync:
            raise ApiError(409, "realm-sync job already exists")
        entry = {
            key: value for key, value in payload.items() if key not in {"id", "delete", "digest"}
        }
        entry.setdefault("schedule", "0 0 * * *")
        entry.setdefault("enabled", 1)
        entry.setdefault("realm", str(payload.get("realm") or "pam"))
        sync[job_id] = entry
        metadata["jobs"] = jobs
        await save_cluster_metadata(request, metadata)
        return {"id": job_id, **entry}

    async def realm_sync_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        job_id = str(payload["id"])
        metadata = await cluster_metadata(request)
        jobs = _jobs(metadata)
        sync = jobs.setdefault("realm_sync", {})
        if job_id not in sync:
            raise ApiError(404, "realm-sync job does not exist")
        updated = {
            **sync[job_id],
            **{
                key: value
                for key, value in payload.items()
                if key not in {"id", "delete", "digest"}
            },
        }
        sync[job_id] = updated
        metadata["jobs"] = jobs
        await save_cluster_metadata(request, metadata)
        return {"id": job_id, **updated}

    async def realm_sync_delete(request: Request, inputs: dict[str, Any]) -> None:
        job_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        jobs = _jobs(metadata)
        sync = jobs.setdefault("realm_sync", {})
        if job_id not in sync:
            raise ApiError(404, "realm-sync job does not exist")
        del sync[job_id]
        metadata["jobs"] = jobs
        await save_cluster_metadata(request, metadata)

    async def schedule_analyze(request: Request, inputs: dict[str, Any]) -> list[dict[str, Any]]:
        schedule = str(values(inputs).get("schedule") or "*/15")
        metadata = await cluster_metadata(request)
        jobs = _jobs(metadata)
        jobs["last_schedule_analyze"] = {"schedule": schedule, "at": int(time.time())}
        metadata["jobs"] = jobs
        await save_cluster_metadata(request, metadata)
        now = int(time.time())
        return [{"timestamp": now + offset * 900, "utc": True} for offset in range(4)]

    async def metrics_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("export", "server")

    async def metrics_export(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        metrics = _metrics(metadata)
        return {
            "data": metrics.get("export_data")
            or '# HELP pve_up Node is up\npve_up{node="pve01"} 1\n',
            "timestamp": int(time.time()),
        }

    async def metrics_server_list(
        request: Request, _inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        metrics = _metrics(metadata)
        return [
            {"id": server_id, **dict(payload)}
            for server_id, payload in sorted(metrics.get("servers", {}).items())
            if isinstance(payload, dict)
        ]

    async def metrics_server_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        server_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        metrics = _metrics(metadata)
        payload = metrics.get("servers", {}).get(server_id)
        if not isinstance(payload, dict):
            raise ApiError(404, "metrics server does not exist")
        return {"id": server_id, **payload}

    async def metrics_server_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        server_id = str(payload["id"])
        metadata = await cluster_metadata(request)
        metrics = _metrics(metadata)
        servers = metrics.setdefault("servers", {})
        if server_id in servers:
            raise ApiError(409, "metrics server already exists")
        entry = {
            key: value for key, value in payload.items() if key not in {"id", "delete", "digest"}
        }
        entry.setdefault("type", "influxdb")
        entry.setdefault("server", "127.0.0.1")
        entry.setdefault("port", 8086)
        entry.setdefault("enable", 1)
        servers[server_id] = entry
        metadata["metrics"] = metrics
        await save_cluster_metadata(request, metadata)
        return {"id": server_id, **entry}

    async def metrics_server_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        server_id = str(payload["id"])
        metadata = await cluster_metadata(request)
        metrics = _metrics(metadata)
        servers = metrics.setdefault("servers", {})
        if server_id not in servers:
            raise ApiError(404, "metrics server does not exist")
        updated = {
            **servers[server_id],
            **{
                key: value
                for key, value in payload.items()
                if key not in {"id", "delete", "digest"}
            },
        }
        servers[server_id] = updated
        metadata["metrics"] = metrics
        await save_cluster_metadata(request, metadata)
        return {"id": server_id, **updated}

    async def metrics_server_delete(request: Request, inputs: dict[str, Any]) -> None:
        server_id = str(values(inputs)["id"])
        metadata = await cluster_metadata(request)
        metrics = _metrics(metadata)
        servers = metrics.setdefault("servers", {})
        if server_id not in servers:
            raise ApiError(404, "metrics server does not exist")
        del servers[server_id]
        metadata["metrics"] = metrics
        await save_cluster_metadata(request, metadata)

    async def qemu_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("cpu-flags", "custom-cpu-models")

    async def qemu_cpu_flags(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return list(DEFAULT_CPU_FLAGS)

    async def cpu_models_list(request: Request, _inputs: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = await cluster_metadata(request)
        models = _cpu_models(metadata)
        return [
            {"name": name, **dict(payload)}
            for name, payload in sorted(models.items())
            if isinstance(payload, dict)
        ]

    async def cpu_models_create(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        name = str(payload.get("name") or payload.get("cputype") or "")
        if not name:
            raise ApiError(400, "parameter verification failed - 'name' missing")
        metadata = await cluster_metadata(request)
        models = _cpu_models(metadata)
        if name in models:
            raise ApiError(409, "custom cpu model already exists")
        entry = {
            key: value
            for key, value in payload.items()
            if key not in {"name", "cputype", "delete", "digest"}
        }
        entry.setdefault("vendor", "Custom")
        models[name] = entry
        metadata["qemu_cpu_models"] = models
        await save_cluster_metadata(request, metadata)
        return {"name": name, **entry}

    async def cpu_models_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        name = str(values(inputs)["cputype"])
        metadata = await cluster_metadata(request)
        models = _cpu_models(metadata)
        payload = models.get(name)
        if not isinstance(payload, dict):
            raise ApiError(404, "custom cpu model does not exist")
        return {"name": name, **payload}

    async def cpu_models_update(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = values(inputs)
        name = str(payload["cputype"])
        metadata = await cluster_metadata(request)
        models = _cpu_models(metadata)
        if name not in models:
            raise ApiError(404, "custom cpu model does not exist")
        updated = {
            **models[name],
            **{
                key: value
                for key, value in payload.items()
                if key not in {"cputype", "delete", "digest"}
            },
        }
        models[name] = updated
        metadata["qemu_cpu_models"] = models
        await save_cluster_metadata(request, metadata)
        return {"name": name, **updated}

    async def cpu_models_delete(request: Request, inputs: dict[str, Any]) -> None:
        name = str(values(inputs)["cputype"])
        metadata = await cluster_metadata(request)
        models = _cpu_models(metadata)
        if name not in models:
            raise ApiError(404, "custom cpu model does not exist")
        del models[name]
        metadata["qemu_cpu_models"] = models
        await save_cluster_metadata(request, metadata)

    async def bulk_action_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("guest")

    async def bulk_guest_index(_request: Request, _inputs: dict[str, Any]) -> list[dict[str, str]]:
        return subdirs("migrate", "shutdown", "start", "suspend")

    async def bulk_guest_action(request: Request, inputs: dict[str, Any], action: str) -> str:
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        metadata["last_bulk_action"] = {
            "action": action,
            "payload": {
                key: value for key, value in payload.items() if key not in {"delete", "digest"}
            },
            "at": int(time.time()),
        }
        await save_cluster_metadata(request, metadata)
        if action == "start":
            await _bulk_guest_status(request, "running")
        elif action == "shutdown":
            await _bulk_guest_status(request, "stopped")
        elif action == "suspend":
            await _bulk_guest_status(request, "paused")
        elif action == "migrate":
            target = str(payload.get("target") or "")
            if target:
                target_row = await database(request).pool.fetchrow(
                    "SELECT id FROM nodes WHERE name=$1", target
                )
                if target_row is None:
                    raise ApiError(404, "target node does not exist")
                vms = payload.get("vms") or payload.get("guests") or ""
                if isinstance(vms, str) and vms:
                    ids = [part.strip() for part in vms.split(",") if part.strip()]
                    for vmid in ids:
                        await database(request).pool.execute(
                            """UPDATE resources SET node_id=$2, updated_at=now()
                            WHERE kind IN ('qemu', 'lxc') AND external_id=$1""",
                            vmid,
                            target_row["id"],
                        )
        return await _cluster_task(request, task_type=f"bulk-{action}", worker=f"bulk{action}")

    async def cluster_ceph_index(
        _request: Request, _inputs: dict[str, Any]
    ) -> list[dict[str, str]]:
        return subdirs("flags", "metadata", "status")

    async def ceph_flags_get(request: Request, _inputs: dict[str, Any]) -> dict[str, int]:
        metadata = await cluster_metadata(request)
        ceph = _ceph(metadata)
        await save_cluster_metadata(request, metadata)
        return {str(key): int(value) for key, value in ceph["flags"].items()}

    async def ceph_flags_put(request: Request, inputs: dict[str, Any]) -> dict[str, int]:
        payload = values(inputs)
        metadata = await cluster_metadata(request)
        ceph = _ceph(metadata)
        flags = dict(ceph["flags"])
        for key, value in payload.items():
            if key in {"delete", "digest"}:
                continue
            flags[str(key)] = int(value)
        ceph["flags"] = flags
        metadata["ceph"] = ceph
        await save_cluster_metadata(request, metadata)
        return {str(key): int(value) for key, value in flags.items()}

    async def ceph_flag_get(request: Request, inputs: dict[str, Any]) -> dict[str, int]:
        flag = str(values(inputs)["flag"])
        metadata = await cluster_metadata(request)
        ceph = _ceph(metadata)
        flags = ceph["flags"]
        if flag not in flags:
            raise ApiError(404, "ceph flag does not exist")
        return {flag: int(flags[flag])}

    async def ceph_flag_put(request: Request, inputs: dict[str, Any]) -> dict[str, int]:
        payload = values(inputs)
        flag = str(payload["flag"])
        metadata = await cluster_metadata(request)
        ceph = _ceph(metadata)
        flags = dict(ceph["flags"])
        if "value" in payload:
            flags[flag] = int(payload["value"])
        elif flag in payload:
            flags[flag] = int(payload[flag])
        else:
            flags[flag] = 1
        ceph["flags"] = flags
        metadata["ceph"] = ceph
        await save_cluster_metadata(request, metadata)
        return {flag: int(flags[flag])}

    async def ceph_metadata(request: Request, _inputs: dict[str, Any]) -> dict[str, Any]:
        metadata = await cluster_metadata(request)
        ceph = _ceph(metadata)
        await save_cluster_metadata(request, metadata)
        return {
            "version": ceph.get("version") or {"str": "18.2.2", "parts": [18, 2, 2]},
            "fsid": ceph.get("config", {}).get("fsid")
            if isinstance(ceph.get("config"), dict)
            else "pve-simulator-fsid",
            "initialized": int(bool(ceph.get("initialized", True))),
            "flags": ceph.get("flags", {}),
        }

    async def ha_rule_create(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        rule = str(payload.get("rule") or payload.get("name") or "")
        if not rule:
            raise ApiError(400, "parameter verification failed - 'rule' missing")
        metadata = await cluster_metadata(request)
        rules = _ha_rules_store(metadata)
        if any(str(item.get("rule")) == rule for item in rules):
            raise ApiError(409, "HA rule already exists")
        entry = {key: value for key, value in payload.items() if key not in {"delete", "digest"}}
        entry["rule"] = rule
        entry.setdefault("type", "resource")
        entry.setdefault("action", "migrate")
        rules.append(entry)
        _save_ha_rules(metadata, rules)
        await save_cluster_metadata(request, metadata)

    async def ha_rule_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        rule = str(values(inputs)["rule"])
        metadata = await cluster_metadata(request)
        for item in _ha_rules_store(metadata):
            if str(item.get("rule")) == rule:
                return dict(item)
        raise ApiError(404, "HA rule does not exist")

    async def ha_rule_update(request: Request, inputs: dict[str, Any]) -> None:
        payload = values(inputs)
        rule = str(payload["rule"])
        metadata = await cluster_metadata(request)
        rules = _ha_rules_store(metadata)
        updated: list[dict[str, Any]] = []
        found = False
        for item in rules:
            if str(item.get("rule")) != rule:
                updated.append(item)
                continue
            found = True
            merged = {
                **item,
                **{
                    key: value
                    for key, value in payload.items()
                    if key not in {"rule", "delete", "digest"}
                },
            }
            merged["rule"] = rule
            updated.append(merged)
        if not found:
            raise ApiError(404, "HA rule does not exist")
        _save_ha_rules(metadata, updated)
        await save_cluster_metadata(request, metadata)

    async def ha_rule_delete(request: Request, inputs: dict[str, Any]) -> None:
        rule = str(values(inputs)["rule"])
        metadata = await cluster_metadata(request)
        rules = _ha_rules_store(metadata)
        remaining = [item for item in rules if str(item.get("rule")) != rule]
        if len(remaining) == len(rules):
            raise ApiError(404, "HA rule does not exist")
        _save_ha_rules(metadata, remaining)
        await save_cluster_metadata(request, metadata)

    async def node_replication_list(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        node = str(values(inputs)["node"])
        await require_node(request, node)
        metadata = await cluster_metadata(request)
        jobs = _replication_jobs(metadata)
        return [
            job
            for job in jobs
            if str(job.get("source") or job.get("node") or node) == node
            or job.get("source") is None
        ]

    async def node_replication_get(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        node = str(values(inputs)["node"])
        job_id = str(values(inputs)["id"])
        await require_node(request, node)
        for job in _replication_jobs(await cluster_metadata(request)):
            if str(job.get("id")) == job_id:
                return dict(job)
        raise ApiError(404, "replication job does not exist")

    async def node_replication_log(
        request: Request, inputs: dict[str, Any]
    ) -> list[dict[str, Any]]:
        job = await node_replication_get(request, inputs)
        log = job.get("log")
        if isinstance(log, list):
            return [dict(item) for item in log if isinstance(item, dict)]
        return [{"t": int(time.time()), "n": 0, "msg": f"replication idle for {job.get('id')}"}]

    async def node_replication_status(request: Request, inputs: dict[str, Any]) -> dict[str, Any]:
        job = await node_replication_get(request, inputs)
        return {
            "id": job.get("id"),
            "last_sync": job.get("last_sync", 0),
            "duration": job.get("duration", 0),
            "fail_count": job.get("fail_count", 0),
            "error": job.get("error", ""),
            "state": job.get("state", "OK"),
        }

    async def node_replication_schedule_now(request: Request, inputs: dict[str, Any]) -> None:
        node = str(values(inputs)["node"])
        job_id = str(values(inputs)["id"])
        await require_node(request, node)
        metadata = await cluster_metadata(request)
        jobs = _replication_jobs(metadata)
        found = False
        for job in jobs:
            if str(job.get("id")) != job_id:
                continue
            found = True
            job["last_sync"] = int(time.time())
            job["state"] = "OK"
            job["schedule_now"] = 1
        if not found:
            raise ApiError(404, "replication job does not exist")
        metadata["replication"] = jobs
        await save_cluster_metadata(request, metadata)

    registry.register("/cluster/jobs", "GET", jobs_index)
    registry.register("/cluster/jobs/realm-sync", "GET", realm_sync_list)
    registry.register("/cluster/jobs/realm-sync/{id}", "GET", realm_sync_get)
    registry.register("/cluster/jobs/realm-sync/{id}", "POST", realm_sync_create)
    registry.register("/cluster/jobs/realm-sync/{id}", "PUT", realm_sync_update)
    registry.register("/cluster/jobs/realm-sync/{id}", "DELETE", realm_sync_delete)
    registry.register("/cluster/jobs/schedule-analyze", "GET", schedule_analyze)

    registry.register("/cluster/metrics", "GET", metrics_index)
    registry.register("/cluster/metrics/export", "GET", metrics_export)
    registry.register("/cluster/metrics/server", "GET", metrics_server_list)
    registry.register("/cluster/metrics/server/{id}", "GET", metrics_server_get)
    registry.register("/cluster/metrics/server/{id}", "POST", metrics_server_create)
    registry.register("/cluster/metrics/server/{id}", "PUT", metrics_server_update)
    registry.register("/cluster/metrics/server/{id}", "DELETE", metrics_server_delete)

    registry.register("/cluster/qemu", "GET", qemu_index)
    registry.register("/cluster/qemu/cpu-flags", "GET", qemu_cpu_flags)
    registry.register("/cluster/qemu/custom-cpu-models", "GET", cpu_models_list)
    registry.register("/cluster/qemu/custom-cpu-models", "POST", cpu_models_create)
    registry.register("/cluster/qemu/custom-cpu-models/{cputype}", "GET", cpu_models_get)
    registry.register("/cluster/qemu/custom-cpu-models/{cputype}", "PUT", cpu_models_update)
    registry.register("/cluster/qemu/custom-cpu-models/{cputype}", "DELETE", cpu_models_delete)

    registry.register("/cluster/bulk-action", "GET", bulk_action_index)
    registry.register("/cluster/bulk-action/guest", "GET", bulk_guest_index)
    registry.register(
        "/cluster/bulk-action/guest/migrate",
        "POST",
        lambda request, inputs: bulk_guest_action(request, inputs, "migrate"),
    )
    registry.register(
        "/cluster/bulk-action/guest/shutdown",
        "POST",
        lambda request, inputs: bulk_guest_action(request, inputs, "shutdown"),
    )
    registry.register(
        "/cluster/bulk-action/guest/start",
        "POST",
        lambda request, inputs: bulk_guest_action(request, inputs, "start"),
    )
    registry.register(
        "/cluster/bulk-action/guest/suspend",
        "POST",
        lambda request, inputs: bulk_guest_action(request, inputs, "suspend"),
    )

    registry.register("/cluster/ceph", "GET", cluster_ceph_index)
    registry.register("/cluster/ceph/flags", "GET", ceph_flags_get)
    registry.register("/cluster/ceph/flags", "PUT", ceph_flags_put)
    registry.register("/cluster/ceph/flags/{flag}", "GET", ceph_flag_get)
    registry.register("/cluster/ceph/flags/{flag}", "PUT", ceph_flag_put)
    registry.register("/cluster/ceph/metadata", "GET", ceph_metadata)

    registry.register("/cluster/ha/rules", "POST", ha_rule_create)
    registry.register("/cluster/ha/rules/{rule}", "GET", ha_rule_get)
    registry.register("/cluster/ha/rules/{rule}", "PUT", ha_rule_update)
    registry.register("/cluster/ha/rules/{rule}", "DELETE", ha_rule_delete)

    registry.register("/nodes/{node}/replication", "GET", node_replication_list)
    registry.register("/nodes/{node}/replication/{id}", "GET", node_replication_get)
    registry.register("/nodes/{node}/replication/{id}/log", "GET", node_replication_log)
    registry.register("/nodes/{node}/replication/{id}/status", "GET", node_replication_status)
    registry.register(
        "/nodes/{node}/replication/{id}/schedule_now", "POST", node_replication_schedule_now
    )
