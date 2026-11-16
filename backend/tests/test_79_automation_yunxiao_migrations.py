"""Migration coverage for returning the automation center to Yunxiao Flow."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from tests.conftest import BACKEND_DIR


def test_migration_graph_has_one_head_and_unique_revisions():
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    revision_ids = [revision.revision for revision in revisions]
    assert len(revision_ids) == len(set(revision_ids))
    assert script.get_heads() == ["0087"]
    chain = {revision.revision: revision.down_revision for revision in revisions}
    assert chain["0087"] == "0086"
    assert chain["0086"] == "0085"
    assert chain["0085"] == "0084"


def test_fresh_upgrade_removes_retired_schema_and_keeps_generic_link(isolated_migration_database):
    config, engine = isolated_migration_database
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        config_columns = {column["name"] for column in inspector.get_columns("automation_integration_config")}
        execution_columns = {column["name"] for column in inspector.get_columns("automation_execution")}
        pipeline_columns = {column["name"] for column in inspector.get_columns("automation_pipeline")}
        assert "automation_jenkins_credential" not in inspector.get_table_names()
        assert not {"provider_type", "enabled", "allow_private_network"} & config_columns
        assert not {
            "provider_type", "external_queue_id", "external_build_number", "external_run_url",
            "stop_reason", "stop_requested_at", "queue_missing_since",
        } & execution_columns
        assert {"integration_config_id", "pipeline_run_id", "external_pipeline_id"} <= execution_columns
        assert "pipeline_id" in pipeline_columns
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0087"


def test_downgrade_restores_legacy_shape_and_upgrade_cleans_it_again(isolated_migration_database):
    config, engine = isolated_migration_database
    command.downgrade(config, "0086")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "automation_jenkins_credential" in inspector.get_table_names()
        assert "provider_type" in {
            column["name"] for column in inspector.get_columns("automation_integration_config")
        }

    command.upgrade(config, "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "automation_jenkins_credential" not in inspector.get_table_names()
        assert "provider_type" not in {
            column["name"] for column in inspector.get_columns("automation_integration_config")
        }


def test_forward_cleanup_preserves_yunxiao_config_history_and_allure(isolated_migration_database):
    config, engine = isolated_migration_database
    command.downgrade(config, "0086")

    with engine.begin() as connection:
        connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (9101, 'migration-user')"))
        connection.execute(text(
            "INSERT INTO organization (id, name, owner_id) VALUES (9101, 'migration-org', 9101)"
        ))
        connection.execute(text(
            "INSERT INTO project (id, name, owner_id, organization_id) "
            "VALUES (9101, 'migration-project', 9101, 9101)"
        ))
        connection.execute(text(
            "INSERT INTO automation_integration_config "
            "(id, project_id, name, api_base_url, organization_id, deployment, access_token_encrypted, "
            "callback_key, callback_secret_encrypted) "
            "VALUES (9101, 9101, 'yunxiao', 'https://openapi.example', 'corp', 'central', 'token-cipher', "
            "'callback-key', 'secret-cipher')"
        ))
        connection.execute(text(
            "INSERT INTO automation_project (id, project_id, integration_config_id, name) "
            "VALUES (9101, 9101, 9101, 'suite')"
        ))
        connection.execute(text(
            "INSERT INTO automation_pipeline (id, automation_project_id, name, pipeline_id) "
            "VALUES (9101, 9101, 'main', '321')"
        ))
        connection.execute(text(
            "INSERT INTO automation_execution "
            "(id, project_id, automation_project_id, pipeline_binding_id, integration_config_id, "
            "external_pipeline_id, pipeline_run_id, status, branch, log_excerpt) "
            "VALUES (9101, 9101, 9101, 9101, 9101, '321', 'run-123', 'SUCCESS', 'main', 'pytest: 10 passed')"
        ))
        connection.execute(text(
            "INSERT INTO automation_report "
            "(id, execution_id, project_id, automation_project_id, storage_dir, total_cases, passed_cases) "
            "VALUES (9101, 9101, 9101, 9101, 'reports/run-123', 10, 10)"
        ))
        connection.execute(text(
            "INSERT INTO automation_artifact (id, execution_id, report_id, kind, relative_path) "
            "VALUES (9101, 9101, 9101, 'ALLURE_HTML_ZIP', 'reports/run-123.zip')"
        ))

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT name FROM automation_integration_config WHERE id=9101"
        )).scalar_one() == "yunxiao"
        run = connection.execute(text(
            "SELECT integration_config_id, pipeline_run_id, status, log_excerpt "
            "FROM automation_execution WHERE id=9101"
        )).one()
        assert tuple(run) == (9101, "run-123", "SUCCESS", "pytest: 10 passed")
        assert connection.execute(text(
            "SELECT storage_dir FROM automation_report WHERE id=9101"
        )).scalar_one() == "reports/run-123"
        assert connection.execute(text(
            "SELECT relative_path FROM automation_artifact WHERE id=9101"
        )).scalar_one() == "reports/run-123.zip"


def test_forward_cleanup_refuses_jenkins_data_before_schema_changes(isolated_migration_database):
    config, engine = isolated_migration_database
    command.downgrade(config, "0086")

    with engine.begin() as connection:
        connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (9102, 'guard-user')"))
        connection.execute(text(
            "INSERT INTO organization (id, name, owner_id) VALUES (9102, 'guard-org', 9102)"
        ))
        connection.execute(text(
            "INSERT INTO project (id, name, owner_id, organization_id) "
            "VALUES (9102, 'guard-project', 9102, 9102)"
        ))
        connection.execute(text(
            "INSERT INTO automation_integration_config "
            "(id, project_id, name, api_base_url, organization_id, deployment, access_token_encrypted, "
            "callback_key, callback_secret_encrypted, provider_type) "
            "VALUES (9102, 9102, 'jenkins', 'https://ci.example', '', 'central', 'cipher', "
            "'guard-key', 'cipher', 'JENKINS')"
        ))

    with pytest.raises(RuntimeError, match="refuses to remove Jenkins integration configurations"):
        command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0086"
        columns = {column["name"] for column in inspect(connection).get_columns("automation_integration_config")}
        assert "provider_type" in columns
        assert connection.execute(text(
            "SELECT provider_type FROM automation_integration_config WHERE id=9102"
        )).scalar_one() == "JENKINS"
