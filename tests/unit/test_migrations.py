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
    migrations = load_migrations()
    migration = migrations[0]

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
    assert "CREATE TABLE realms" in migrations[1].sql
    assert "CREATE TABLE api_tokens" in migrations[1].sql
    domain = migrations[3].sql
    for table in (
        "clusters",
        "virtual_machines",
        "containers",
        "storages",
        "storage_contents",
        "snapshots",
        "backups",
        "pools",
        "identity_groups",
        "contract_paths",
        "observed_contracts",
        "scenario_rules",
        "fault_injections",
    ):
        assert f"CREATE TABLE {table}" in domain
    assert "CREATE TABLE group_acl_entries" in migrations[5].sql
