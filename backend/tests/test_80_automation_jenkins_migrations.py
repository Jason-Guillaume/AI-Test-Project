"""PostgreSQL migration coverage for the repaired Jenkins revision chain."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from tests.conftest import BACKEND_DIR


def test_automation_migration_graph_has_one_head_and_unique_revisions():
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    revision_ids = [revision.revision for revision in revisions]
    assert len(revision_ids) == len(set(revision_ids))
    assert script.get_heads() == ["0085"]
    chain = {revision.revision: revision.down_revision for revision in revisions}
    assert chain["0085"] == "0084"
    assert chain["0084"] == "0083"
    assert chain["0083"] == "0082"
    assert chain["0082"] == "0081"


def test_upgrade_head_is_repeatable_and_creates_jenkins_constraints(isolated_migration_database):
    config, engine = isolated_migration_database
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0085"
        inspector = inspect(connection)
        config_columns = {column["name"] for column in inspector.get_columns("automation_integration_config")}
        execution_columns = {column["name"] for column in inspector.get_columns("automation_execution")}
        indexes = {index["name"] for index in inspector.get_indexes("automation_execution")}
        assert {"provider_type", "enabled", "allow_private_network"} <= config_columns
        assert {
            "integration_config_id", "provider_type", "external_queue_id", "external_build_number",
            "external_run_url", "stop_reason", "stop_requested_at", "queue_missing_since",
        } <= execution_columns
        assert {
            "uq_automation_execution_jenkins_queue", "uq_automation_execution_jenkins_build",
            "ix_automation_execution_stop_requested",
        } <= indexes


def test_legacy_jenkins_0082_stamp_upgrades_without_duplicate_ddl(isolated_migration_database):
    """Mimic the previously shipped Jenkins 0082 schema before the API-key 0082 chain."""
    config, engine = isolated_migration_database
    command.downgrade(config, "0081")
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE automation_integration_config "
            "ADD COLUMN provider_type VARCHAR(20) NOT NULL DEFAULT 'YUNXIAO', "
            "ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE, "
            "ADD COLUMN allow_private_network BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        connection.execute(text(
            "CREATE TABLE automation_jenkins_credential ("
            "integration_config_id INTEGER PRIMARY KEY REFERENCES automation_integration_config(id) ON DELETE CASCADE, "
            "base_url VARCHAR(500) NOT NULL, username VARCHAR(200) NOT NULL, "
            "api_token_encrypted TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT now(), "
            "updated_at TIMESTAMP NOT NULL DEFAULT now())"
        ))
        connection.execute(text("ALTER TABLE automation_pipeline ALTER COLUMN pipeline_id TYPE VARCHAR(255)"))
        connection.execute(text(
            "ALTER TABLE automation_execution ADD COLUMN integration_config_id INTEGER, "
            "ADD COLUMN provider_type VARCHAR(20) NOT NULL DEFAULT 'YUNXIAO', "
            "ADD COLUMN external_queue_id VARCHAR(64), ADD COLUMN external_build_number INTEGER, "
            "ADD COLUMN external_run_url VARCHAR(1000) NOT NULL DEFAULT ''"
        ))
        connection.execute(text(
            "ALTER TABLE automation_execution ADD CONSTRAINT fk_automation_execution_integration_config "
            "FOREIGN KEY (integration_config_id) REFERENCES automation_integration_config(id) ON DELETE SET NULL"
        ))
        connection.execute(text(
            "CREATE INDEX ix_automation_execution_integration_config_id "
            "ON automation_execution(integration_config_id)"
        ))
        connection.execute(text("ALTER TABLE automation_execution ALTER COLUMN external_pipeline_id TYPE VARCHAR(255)"))
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_automation_execution_jenkins_queue "
            "ON automation_execution(integration_config_id, external_queue_id) "
            "WHERE provider_type = 'JENKINS' AND external_queue_id IS NOT NULL"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_automation_execution_jenkins_build "
            "ON automation_execution(integration_config_id, external_pipeline_id, external_build_number) "
            "WHERE provider_type = 'JENKINS' AND external_build_number IS NOT NULL"
        ))
        connection.execute(text("UPDATE alembic_version SET version_num = '0082'"))

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0085"
        columns = {column["name"] for column in inspect(connection).get_columns("api_response")}
        execution_columns = {column["name"] for column in inspect(connection).get_columns("automation_execution")}
        assert "response_key" in columns
        assert {"stop_reason", "stop_requested_at", "queue_missing_since"} <= execution_columns
        assert "uq_automation_execution_jenkins_build" in {
            index["name"] for index in inspect(connection).get_indexes("automation_execution")
        }
