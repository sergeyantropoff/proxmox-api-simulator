"""Checksummed asynchronous PostgreSQL migration runner."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
from asyncpg import Connection


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


def load_migrations(root: Path | None = None) -> tuple[Migration, ...]:
    directory = root or Path(__file__).with_name("migrations")
    migrations = []
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name.split("_", 1)[0])
        sql = path.read_text()
        migrations.append(
            Migration(version, path.stem, sql, hashlib.sha256(sql.encode()).hexdigest())
        )
    return tuple(migrations)


async def migrate(connection: Connection, migrations: tuple[Migration, ...] | None = None) -> int:
    await connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
        version integer PRIMARY KEY, name text NOT NULL, checksum text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now())"""
    )
    applied = {
        int(row["version"]): str(row["checksum"])
        for row in await connection.fetch("SELECT version, checksum FROM schema_migrations")
    }
    count = 0
    for migration in migrations or load_migrations():
        if migration.version in applied:
            if applied[migration.version] != migration.checksum:
                raise MigrationError(f"migration {migration.version} checksum mismatch")
            continue
        async with connection.transaction():
            await connection.execute(migration.sql)
            await connection.execute(
                "INSERT INTO schema_migrations(version, name, checksum) VALUES($1, $2, $3)",
                migration.version,
                migration.name,
                migration.checksum,
            )
        count += 1
    return count


async def migrate_url(database_url: str) -> int:
    connection = await asyncpg.connect(database_url)
    try:
        return await migrate(connection)
    finally:
        await connection.close()
