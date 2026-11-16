"""Dagu migration graph, schema cleanup and legacy history preservation."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _script_directory() -> ScriptDirectory:
    """Load the repository migration graph for structural assertions."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


def test_automation_migration_graph_has_one_dagu_head():
    """Keep one forward-only revision after the published provider migration."""
    script = _script_directory()
    revisions = list(script.walk_revisions())
    identifiers = [revision.revision for revision in revisions]
    assert len(identifiers) == len(set(identifiers))
    assert script.get_heads() == ["0087"]
    chain = {revision.revision: revision.down_revision for revision in revisions}
    assert chain["0087"] == "0086"
    assert chain["0086"] == "0085"


def test_head_schema_removes_jenkins_columns_and_adds_dagu_configuration(isolated_migration_database):
    """Match the ORM schema after a clean base-to-head Alembic upgrade."""
    _config, engine = isolated_migration_database
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0087"
        inspector = inspect(connection)
        config_columns = {column["name"] for column in inspector.get_columns("automation_integration_config")}
        execution_columns = {column["name"] for column in inspector.get_columns("automation_execution")}
        assert {"dagu_base_url", "dagu_api_key_encrypted", "dagu_api_key_configured"} <= config_columns
        assert not {"allow_private_network", "queue_missing_since"} & config_columns
        assert not {"external_queue_id", "external_build_number", "queue_missing_since"} & execution_columns
        assert "automation_jenkins_credential" not in inspector.get_table_names()
        execution_indexes = {index["name"] for index in inspector.get_indexes("automation_execution")}
        assert not {"uq_automation_execution_jenkins_queue", "uq_automation_execution_jenkins_build"} & execution_indexes


def test_upgrade_archives_old_provider_ids_and_disables_legacy_config(isolated_migration_database):
    """Upgrade a minimal 0086-shaped database and retain Jenkins history as LEGACY JSON."""
    config, engine = isolated_migration_database
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0086')"))
        connection.execute(text(
            "CREATE TABLE automation_integration_config ("
            "id INTEGER PRIMARY KEY, provider_type VARCHAR(20) NOT NULL, enabled BOOLEAN NOT NULL, "
            "allow_private_network BOOLEAN NOT NULL DEFAULT FALSE)"
        ))
        connection.execute(text(
            "CREATE TABLE automation_execution ("
            "id INTEGER PRIMARY KEY, provider_type VARCHAR(20) NOT NULL, run_params JSONB, "
            "external_queue_id VARCHAR(64), external_build_number INTEGER, queue_missing_since TIMESTAMP)"
        ))
        connection.execute(text("CREATE INDEX uq_automation_execution_jenkins_queue ON automation_execution (id)"))
        connection.execute(text("CREATE INDEX uq_automation_execution_jenkins_build ON automation_execution (id)"))
        connection.execute(text("CREATE TABLE automation_jenkins_credential (integration_config_id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "INSERT INTO automation_integration_config VALUES (1, 'JENKINS', TRUE, TRUE), (2, 'YUNXIAO', TRUE, FALSE)"
        ))
        connection.execute(text(
            "INSERT INTO automation_execution VALUES "
            "(11, 'JENKINS', '{\"branch\":\"main\"}'::jsonb, '735', 19, NULL), "
            "(12, 'YUNXIAO', '{\"branch\":\"develop\"}'::jsonb, NULL, NULL, NULL)"
        ))

    command.upgrade(config, "0087")
    with engine.connect() as connection:
        configs = connection.execute(text(
            "SELECT id, provider_type, enabled FROM automation_integration_config ORDER BY id"
        )).all()
        assert configs == [(1, "LEGACY", False), (2, "YUNXIAO", True)]
        legacy = connection.execute(text(
            "SELECT provider_type, run_params FROM automation_execution WHERE id = 11"
        )).one()
        assert legacy.provider_type == "LEGACY"
        assert legacy.run_params["legacy_provider_identifiers"] == {
            "provider_type": "JENKINS", "queue_id": "735", "build_number": 19,
        }
        assert legacy.run_params["branch"] == "main"
        yunxiao = connection.execute(text(
            "SELECT provider_type, run_params FROM automation_execution WHERE id = 12"
        )).one()
        assert yunxiao.provider_type == "YUNXIAO"
        assert yunxiao.run_params == {"branch": "develop"}
        inspector = inspect(connection)
        assert "automation_jenkins_credential" not in inspector.get_table_names()
        assert not {"external_queue_id", "external_build_number", "queue_missing_since"} & {
            column["name"] for column in inspector.get_columns("automation_execution")
        }


def test_dagu_migration_downgrade_requires_database_restore(isolated_migration_database):
    """Never erase preserved provider history during an implicit Alembic rollback."""
    config, _engine = isolated_migration_database
    try:
        command.downgrade(config, "0086")
    except RuntimeError as error:
        assert "不支持降级" in str(error) or "无法安全降级" in str(error)
    else:
        raise AssertionError("0087 downgrade unexpectedly succeeded")
