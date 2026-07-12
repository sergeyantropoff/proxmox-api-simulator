"""Migration discovery and checksum tests."""

from pathlib import Path

from app.db.migrations import load_migrations


def test_load_migrations_is_ordered_and_checksummed(tmp_path: Path) -> None:
    (tmp_path / "002_second.sql").write_text("SELECT 2;")
    (tmp_path / "001_first.sql").write_text("SELECT 1;")

    migrations = load_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 2]
    assert migrations[0].name == "001_first"
    assert len(migrations[0].checksum) == 64


def test_repository_migration_defines_required_planes() -> None:
    migration = load_migrations()[0]

    for table in (
        "contract_snapshots",
        "nodes",
        "resources",
        "principals",
        "acl_entries",
        "tasks",
        "scenarios",
        "audit_events",
    ):
        assert f"CREATE TABLE {table}" in migration.sql
