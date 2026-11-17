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
    assert script.get_heads() == ["0089"]
    chain = {revision.revision: revision.down_revision for revision in revisions}
    assert chain["0089"] == "0088"
    assert chain["0088"] == "0087"
    assert chain["0087"] == "0086"
    assert chain["0086"] == "0085"


def test_head_schema_removes_jenkins_columns_and_adds_dagu_configuration(isolated_migration_database):
    """Match the ORM schema after a clean base-to-head Alembic upgrade."""
    _config, engine = isolated_migration_database
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0089"
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
            "external_queue_id VARCHAR(64), external_build_number INTEGER, queue_missing_since TIMESTAMP, "
            "status VARCHAR(20), error_message VARCHAR(500), finished_at TIMESTAMP, stop_requested_at TIMESTAMP)"
        ))
        connection.execute(text("CREATE INDEX uq_automation_execution_jenkins_queue ON automation_execution (id)"))
        connection.execute(text("CREATE INDEX uq_automation_execution_jenkins_build ON automation_execution (id)"))
        connection.execute(text("CREATE TABLE automation_jenkins_credential (integration_config_id INTEGER PRIMARY KEY)"))
        connection.execute(text(
            "INSERT INTO automation_integration_config VALUES (1, 'JENKINS', TRUE, TRUE), (2, 'YUNXIAO', TRUE, FALSE)"
        ))
        connection.execute(text(
            "INSERT INTO automation_execution VALUES "
            "(11, 'JENKINS', '{\"branch\":\"main\"}'::jsonb, '735', 19, NULL, 'SUCCESS', '', NULL, NULL), "
            "(12, 'YUNXIAO', '{\"branch\":\"develop\"}'::jsonb, NULL, NULL, NULL, 'SUCCESS', '', NULL, NULL), "
            "(13, 'JENKINS', '{}'::jsonb, '801', NULL, NULL, 'RUNNING', '', NULL, NULL)"
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
        archived = connection.execute(text(
            "SELECT status, error_message, run_params FROM automation_execution WHERE id = 13"
        )).one()
        assert archived.status == "CANCELLED"
        assert "已归档" in archived.error_message
        assert archived.run_params["legacy_provider_identifiers"]["previous_status"] == "RUNNING"
        assert archived.run_params["legacy_provider_identifiers"]["archived_incomplete"] is True
        inspector = inspect(connection)
        assert "automation_jenkins_credential" not in inspector.get_table_names()
        assert not {"external_queue_id", "external_build_number", "queue_missing_since"} & {
            column["name"] for column in inspector.get_columns("automation_execution")
        }


def test_dagu_migration_downgrade_restores_empty_schema_and_keeps_history(isolated_migration_database):
    """空库可以恢复 Jenkins 表结构；一旦有归档或 Dagu 数据，降级必须停住。"""
    config, engine = isolated_migration_database
    command.downgrade(config, "0086")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0086"
        inspector = inspect(connection)
        execution_columns = {column["name"] for column in inspector.get_columns("automation_execution")}
        config_columns = {column["name"] for column in inspector.get_columns("automation_integration_config")}
        assert {"external_queue_id", "external_build_number", "queue_missing_since"} <= execution_columns
        assert "allow_private_network" in config_columns
        assert "dagu_base_url" not in config_columns
        assert "automation_jenkins_credential" in inspector.get_table_names()
    command.upgrade(config, "0087")
    with engine.begin() as connection:
        user_id = connection.execute(text(
            "INSERT INTO \"user\" (username, role, is_active, token_version) "
            "VALUES ('legacy-migration-user', 'test', true, 0) RETURNING id"
        )).scalar_one()
        project_id = connection.execute(text(
            "INSERT INTO project (name, owner_id) VALUES ('legacy-migration-project', :owner) RETURNING id"
        ), {"owner": user_id}).scalar_one()
        config_id = connection.execute(text(
            "INSERT INTO automation_integration_config ("
            "project_id, name, provider_type, enabled, api_base_url, access_token_encrypted, "
            "callback_key, callback_secret_encrypted"
            ") VALUES (:project_id, 'archived', 'LEGACY', false, 'https://jenkins.example', 'cipher', "
            "'legacy-callback-key', 'cipher') RETURNING id"
        ), {"project_id": project_id}).scalar_one()
        automation_project_id = connection.execute(text(
            "INSERT INTO automation_project (project_id, integration_config_id, name) "
            "VALUES (:project_id, :config_id, 'archived-job') RETURNING id"
        ), {"project_id": project_id, "config_id": config_id}).scalar_one()
        connection.execute(text(
            "INSERT INTO automation_execution ("
            "project_id, automation_project_id, integration_config_id, provider_type, "
            "external_pipeline_id, status"
            ") VALUES (:project_id, :automation_project_id, :config_id, 'LEGACY', 'legacy-job', 'CANCELLED')"
        ), {
            "project_id": project_id,
            "automation_project_id": automation_project_id,
            "config_id": config_id,
        })
    try:
        command.downgrade(config, "0086")
    except RuntimeError as error:
        assert "无法安全降级" in str(error)
    else:
        raise AssertionError("0087 downgrade erased archived history")
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT provider_type FROM automation_execution WHERE external_pipeline_id = 'legacy-job'"
        )).scalar_one() == "LEGACY"


def test_upgrade_from_legacy_share_0088_adds_missing_dagu_schema(isolated_migration_database):
    """旧分享工作树的 0088 已建分享表，但尚未包含 Dagu 的 0088。"""
    config, engine = isolated_migration_database
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE automation_execution_idempotency"))
        connection.execute(text("DROP INDEX ix_automation_execution_dispatch"))
        connection.execute(text("ALTER TABLE automation_execution DROP COLUMN dispatch_state"))
        connection.execute(text("UPDATE alembic_version SET version_num = '0088'"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0089"
        assert "defect_share_link" in inspector.get_table_names()
        assert "automation_execution_idempotency" in inspector.get_table_names()
        assert "dispatch_state" in {column["name"] for column in inspector.get_columns("automation_execution")}
