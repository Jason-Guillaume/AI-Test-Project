"""PostgreSQL storage contract for the reversible 198-to-180 refactor."""
import sqlalchemy as sa


def test_contract_entries_have_typed_public_ids(db):
    assert "api_contract_entry" in sa.inspect(db.connection()).get_table_names()
    assert {"api_parameter", "api_response", "api_request_body"} <= set(
        sa.inspect(db.connection()).get_view_names()
    )


def test_extensions_preserve_ids_presence_and_new_writes_on_rollback(isolated_migration_database):
    from alembic import command
    from sqlalchemy.orm import Session

    from app.lifecycle.service import _agent_session_purge_references, _project_purge_references

    config, engine = isolated_migration_database
    command.downgrade(config, "0099")
    with engine.begin() as c:
        assert len(sa.inspect(c).get_table_names()) == 198
        c.exec_driver_sql("""
            INSERT INTO "user" (id, username) VALUES (8001, 'storage-owner'), (8002, 'reviewer');
            INSERT INTO project (id, name, owner_id) VALUES (8001, 'storage-fixture', 8001);
            INSERT INTO api_interface (id, project_id, name, method, path) VALUES
                (8001, 8001, 'explicit', 'GET', '/one'), (8002, 8001, 'absent', 'GET', '/two');
            INSERT INTO api_request_body (id, interface_id, body_type, content_type)
                VALUES (17, 8001, 'none', 'text/plain');
            INSERT INTO api_parameter (id, interface_id, name, location) VALUES (17, 8001, 'q', 'QUERY');
            INSERT INTO api_response (id, interface_id, status_code, response_key) VALUES (17,8001,NULL,'2XX');
            SELECT setval('api_parameter_id_seq', 400);
            SELECT setval('api_response_id_seq', 900);
            INSERT INTO test_case (id, project_id, name, target_type) VALUES
                (8001, 8001, 'configured', 'WEB'), (8002, 8001, 'imported without config', 'WEB');
            INSERT INTO web_case (test_case_id, confirmed_by) VALUES (8001, 8002);
            INSERT INTO agent_session (id, project_id, updated_at) VALUES (8001, 8001, '2020-07-01');
            INSERT INTO agent_session_summary
                (session_id, summary_text, source_digest, source_through_message_id, expires_at)
                VALUES (8001, 'review', 'digest', 42, '2020-07-02');
            INSERT INTO security_project_setting (id, project_id, revision, updated_by) VALUES (71, 8001, 7, 8002);
            INSERT INTO test_scope_api_backfill (test_case_id) VALUES (8002);
            INSERT INTO model_global_migration_audit (resource_id, project_id, previous_status, decision)
                VALUES (33, 8001, 'ACTIVE', 'HISTORIC');
        """)
    command.upgrade(config, "0106")
    with engine.begin() as c:
        assert len(sa.inspect(c).get_table_names()) == 180
        assert c.exec_driver_sql("SELECT kind, public_id FROM api_contract_entry ORDER BY kind").all() == [
            ("PARAMETER", 17), ("RESPONSE", 17),
        ]
        assert c.exec_driver_sql("SELECT request_body_id, request_body_type, request_body_content_type, "
                                 "content_type FROM api_interface WHERE id=8001").one() == (
            17, "none", "text/plain", "application/json",
        )
        assert c.exec_driver_sql("SELECT request_body_id FROM api_interface WHERE id=8002").scalar_one() is None
        assert c.exec_driver_sql("SELECT test_case_id FROM web_case").scalars().all() == [8001]
        assert c.exec_driver_sql("SELECT id, revision FROM security_project_setting").one() == (71, 7)
        assert c.exec_driver_sql("SELECT public_id, previous_status FROM migration_evidence "
                                 "WHERE kind='MODEL_AUDIT' AND public_id=33").one() == (33, "ACTIVE")
        with Session(c) as session:
            from app.features.api_catalog.models import ApiInterface
            from app.features.api_catalog.services.response_loader import detail_response

            detail = detail_response(session, session.get(ApiInterface, 8001))
            assert [param.id for param in detail.parameters] == [17]
            assert [(response.id, response.response_key) for response in detail.responses] == [(17, "2XX")]
            c.exec_driver_sql("UPDATE api_response SET description='edited' WHERE id=17")
            assert detail_response(session, session.get(ApiInterface, 8001)).responses[0].description == "edited"
            assert "agent_session_summary.session_id: 1" in _agent_session_purge_references(session, 8001)
            assert "security_project_setting: 1" in _project_purge_references(session, 8001)
        assert c.exec_driver_sql("INSERT INTO api_parameter(interface_id, name, location) "
                                 "VALUES (8002,'q2','QUERY') RETURNING id").scalar_one() == 401
        assert c.exec_driver_sql("INSERT INTO api_response(interface_id, response_key) "
                                 "VALUES (8002,'default') RETURNING id").scalar_one() == 901
        c.exec_driver_sql("""
            DELETE FROM api_parameter WHERE interface_id = 8001;
            UPDATE agent_session_summary SET summary_text = 'after cutover' WHERE session_id=8001;
            UPDATE security_project_setting SET revision=8 WHERE project_id=8001;
            DELETE FROM "user" WHERE id=8002;
            DELETE FROM api_request_body WHERE id=17;
            INSERT INTO api_request_body (interface_id, body_type) VALUES (8002, 'raw');
            DELETE FROM test_case WHERE id=8002;
        """)
        assert c.exec_driver_sql("SELECT count(*) FROM migration_evidence WHERE kind='API_BACKFILL' "
                                 "AND test_case_id=8002").scalar_one() == 0
    command.downgrade(config, "0099")
    with engine.begin() as c:
        assert len(sa.inspect(c).get_table_names()) == 198
        assert c.exec_driver_sql("SELECT interface_id, body_type FROM api_request_body").all() == [(8002, "raw")]
        assert c.exec_driver_sql("SELECT id, name FROM api_parameter").all() == [(401, "q2")]
        assert c.exec_driver_sql("SELECT id,response_key FROM api_response ORDER BY id").all() == [
            (17, "2XX"), (901, "default"),
        ]
        assert c.exec_driver_sql("SELECT summary_text, source_through_message_id, expires_at::date::text "
                                 "FROM agent_session_summary").one() == ("after cutover", 42, "2020-07-02")
        assert c.exec_driver_sql("SELECT updated_at::date::text FROM agent_session WHERE id=8001").scalar_one() == "2020-07-01"
        assert c.exec_driver_sql("SELECT id, revision, updated_by FROM security_project_setting").one() == (71, 8, None)
        assert c.exec_driver_sql("SELECT test_case_id, timeout_ms, total_timeout_ms, confirmed_by FROM web_case").one() == (
            8001, 30000, 120000, None,
        )
        assert c.exec_driver_sql("SELECT resource_id, decision FROM model_global_migration_audit "
                                 "WHERE resource_id=33").one() == (33, "HISTORIC")
    command.upgrade(config, "0106")
    with engine.connect() as c:
        assert len(sa.inspect(c).get_table_names()) == 180
        assert c.exec_driver_sql("SELECT count(*) FROM api_contract_entry").scalar_one() == 3


def test_postgres_metadata_matches_storage_and_typed_model_keys(db):
    from app.core.database.schema_metadata import postgres_metadata
    from app.core.database.base import Base
    from app.core.database import migration_evidence  # noqa: F401
    from app.main import app  # noqa: F401  register all runtime models

    physical = postgres_metadata(Base.metadata)
    inspector = sa.inspect(db.connection())
    assert set(physical.tables) == set(inspector.get_table_names()) - {"alembic_version", "td_sandbox_task"}
    assert not set(physical.tables).intersection(inspector.get_view_names())

    typed_keys = {"model_public_id", "connection_public_id", "parameter_public_id"}
    expected = {
        (table.name, key.parent.name, key.column.name, key.ondelete or "NO ACTION")
        for table in physical.tables.values() for key in table.foreign_keys
        if key.column.table.name == "model_legacy_binding" and key.column.name in typed_keys
    }
    observed = {
        (table, fk["constrained_columns"][0], fk["referred_columns"][0], fk["options"].get("ondelete", "NO ACTION"))
        for table, fks in inspector.get_multi_foreign_keys().items() for fk in fks
        if fk["referred_table"] == "model_legacy_binding" and fk["referred_columns"][0] in typed_keys
    }
    assert expected == {(table[1], source, target, action) for table, source, target, action in observed}
