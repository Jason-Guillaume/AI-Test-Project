"""Execute the incremental migration against synthetic historical private credentials."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine, text
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_private_credentials_and_historical_references_are_retained_and_disabled():
    spec=importlib.util.spec_from_file_location('knowledge_migration',Path(__file__).parents[1]/'alembic/versions/0046_project_knowledge.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        for sql in [
            'CREATE TABLE project (id INTEGER PRIMARY KEY)',
            'CREATE TABLE agent_definition (id INTEGER PRIMARY KEY)',
            'CREATE TABLE model_resource (id INTEGER PRIMARY KEY, project_id INTEGER, status TEXT, visibility TEXT)',
            'CREATE TABLE model_revision (id INTEGER PRIMARY KEY, resource_id INTEGER, enabled BOOLEAN)',
            'CREATE TABLE model_credential (id INTEGER PRIMARY KEY, revision_id INTEGER, ciphertext TEXT)',
            'CREATE TABLE historical_task (id INTEGER PRIMARY KEY, revision_id INTEGER)',
            "INSERT INTO model_resource VALUES (11, 3, 'ACTIVE', 'PROJECT')",
            'INSERT INTO model_revision VALUES (21, 11, true)',
            "INSERT INTO model_credential VALUES (31, 21, 'synthetic-encrypted-secret')",
            'INSERT INTO historical_task VALUES (41, 21)',
        ]:connection.execute(text(sql))
        operations=Operations(MigrationContext.configure(connection))
        with patch.object(migration,'op',operations):migration.upgrade()
        assert connection.execute(text('SELECT status,visibility FROM model_resource')).one()==('DISABLED','PROJECT')
        assert not connection.execute(text('SELECT enabled FROM model_revision')).scalar_one()
        assert connection.execute(text('SELECT ciphertext FROM model_credential')).scalar_one()=='synthetic-encrypted-secret'
        assert connection.execute(text('SELECT revision_id FROM historical_task')).scalar_one()==21
        assert connection.execute(text('SELECT decision FROM model_global_migration_audit')).scalar_one()=='DISABLED_PENDING_ADMIN_REVIEW'
