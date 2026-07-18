"""Cluster backup job handlers."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import FastAPI, Request

from app.api.registry import HandlerRegistry
from app.db.pool import AsyncpgDatabase
from app.handlers.backup import register_backup_handlers


class BackupPool:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {
            "backup_jobs": {
                "backup-daily": {
                    "id": "backup-daily",
                    "schedule": "0 2 * * *",
                    "storage": "local",
                    "enabled": 1,
                    "vmid": "100",
                }
            }
        }
        self.guests = [
            {
                "external_id": "100",
                "kind": "qemu",
                "state": '{"name":"demo"}',
                "qemu_config": '{"scsi0":"local-lvm:vm-100-disk-0,size=32G"}',
                "lxc_config": None,
            },
            {
                "external_id": "200",
                "kind": "lxc",
                "state": '{"name":"service"}',
                "qemu_config": None,
                "lxc_config": '{"rootfs":"local-lvm:vm-200-disk-0,size=8G"}',
            },
        ]

    async def fetchrow(self, query: str, *_arguments: object) -> dict[str, Any] | None:
        if "FROM clusters WHERE id" in query:
            return {"metadata": json.dumps(self.metadata)}
        raise AssertionError(query)

    async def fetch(self, query: str, *arguments: object) -> list[dict[str, Any]]:
        if "FROM resources r" in query and "ANY($1" in query:
            selected = set(str(item) for item in cast(list[Any], arguments[0]))
            return [row for row in self.guests if row["external_id"] in selected]
        if "FROM resources r" in query:
            return list(self.guests)
        raise AssertionError(query)

    async def execute(self, query: str, *arguments: object) -> str:
        if "UPDATE clusters SET metadata" in query:
            self.metadata = json.loads(str(arguments[1]))
            return "UPDATE 1"
        raise AssertionError(query)


def _request(pool: BackupPool) -> Request:
    app = FastAPI()
    app.state.database = cast(AsyncpgDatabase, type("DB", (), {"pool": pool})())
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
        }
    )


async def test_backup_jobs_crud_and_shapes() -> None:
    registry = HandlerRegistry()
    register_backup_handlers(registry)
    pool = BackupPool()
    http = _request(pool)

    listed = await registry.get("/cluster/backup", "GET")(http, {"values": {}})
    assert listed[0]["id"] == "backup-daily"
    assert listed[0]["schedule"] == "0 2 * * *"

    await registry.get("/cluster/backup", "POST")(
        http,
        {
            "values": {
                "id": "backup-weekly",
                "schedule": "@weekly",
                "storage": "local",
                "vmid": "200",
            }
        },
    )
    assert "backup-weekly" in pool.metadata["backup_jobs"]

    info = await registry.get("/cluster/backup-info", "GET")(http, {"values": {}})
    assert info == [{"subdir": "not-backed-up"}]

    missing = await registry.get("/cluster/backup-info/not-backed-up", "GET")(http, {"values": {}})
    assert missing == []  # 100 covered by daily; after weekly both covered? weekly adds 200
    # daily covers 100, weekly covers 200 → none missing
    assert missing == []

    included = await registry.get("/cluster/backup/{id}/included_volumes", "GET")(
        http, {"values": {"id": "backup-daily"}}
    )
    assert included["children"][0]["id"] == 100
    assert included["children"][0]["children"][0]["id"] == "scsi0"

    await registry.get("/cluster/backup/{id}", "DELETE")(http, {"values": {"id": "backup-weekly"}})
    assert "backup-weekly" not in pool.metadata["backup_jobs"]
    missing_after = await registry.get("/cluster/backup-info/not-backed-up", "GET")(
        http, {"values": {}}
    )
    assert missing_after[0]["vmid"] == 200
    assert missing_after[0]["type"] == "lxc"
