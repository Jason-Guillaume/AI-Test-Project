"""Integration contracts for namespaced test assets and their PostgreSQL projections."""

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session

from tests.conftest import TEST_DSN, unique


@pytest.fixture
def connection(test_database):
    engine = sa.create_engine(TEST_DSN)
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            yield conn
        finally:
            transaction.rollback()
    engine.dispose()


def _project(conn):
    owner = conn.exec_driver_sql('INSERT INTO "user" DEFAULT VALUES RETURNING id').scalar_one()
    return conn.execute(
        sa.text("INSERT INTO project (owner_id, name) VALUES (:owner, :name) RETURNING id"),
        {"owner": owner, "name": unique("storage")},
    ).scalar_one()


def _case(conn, project):
    return conn.execute(
        sa.text("INSERT INTO test_case (project_id, name) VALUES (:project, :name) RETURNING id"),
        {"project": project, "name": unique("case")},
    ).scalar_one()


def _reject(conn, sql, **params):
    with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
        conn.execute(sa.text(sql), params)


def test_plan_suite_and_case_edges_reject_other_projects(connection):
    first, second = _project(connection), _project(connection)
    case = _case(connection, first)
    plan = connection.execute(sa.text(
        "INSERT INTO test_plan (project_id, name) VALUES (:p, 'daily') RETURNING id"
    ), {"p": first}).scalar_one()
    suite = connection.execute(sa.text(
        "INSERT INTO test_suite (project_id, name) VALUES (:p, 'daily') RETURNING id"
    ), {"p": second}).scalar_one()
    _reject(connection, "INSERT INTO test_plan_suite (plan_id, suite_id) VALUES (:p, :s)", p=plan, s=suite)
    _reject(connection, "INSERT INTO test_suite_case (suite_id, test_case_id) VALUES (:s, :c)", s=suite, c=case)


def test_step_reference_rejects_another_case_even_on_update(connection):
    project = _project(connection)
    first, second = _case(connection, project), _case(connection, project)
    step = connection.execute(sa.text(
        "INSERT INTO test_step (test_case_id, name) VALUES (:c, 'load') RETURNING id"
    ), {"c": first}).scalar_one()
    assertion = connection.execute(sa.text(
        "INSERT INTO test_assertion (test_case_id, step_id) VALUES (:c, :s) RETURNING id"
    ), {"c": first, "s": step}).scalar_one()
    _reject(connection, "UPDATE test_assertion SET test_case_id=:c WHERE id=:a", c=second, a=assertion)
    _reject(connection, "UPDATE test_step SET test_case_id=:c WHERE id=:s", c=second, s=step)
    _reject(connection, "INSERT INTO test_assertion (test_case_id, step_id) VALUES (:c, :s)", c=first, s=-98765)


def test_signed_step_keys_preserve_the_entire_historical_integer_range(connection):
    case = _case(connection, _project(connection))
    for public in (-2147483648, 2147483647):
        params = {"id": public, "c": case}
        for statement in (
            "INSERT INTO test_step (id,test_case_id,name) VALUES (:id,:c,'boundary')",
            "INSERT INTO test_case_precondition (id,test_case_id) VALUES (:id,:c)",
            "INSERT INTO test_case_data (id,test_case_id,name) VALUES (:id,:c,CAST(:id AS text))",
            "INSERT INTO test_case_component (public_id,test_case_id,assertion_type,operator,required,step_component_id) "
            "VALUES (:id,:c,'STATUS_CODE','EQ',true,:id)",
        ):
            connection.execute(sa.text(statement), params)
        assert connection.execute(sa.text(
            "SELECT id, step_id FROM test_assertion WHERE id=:id"
        ), params).one() == (public, public)
        _reject(connection, "UPDATE test_step SET id=12345 WHERE id=:id", **params)
    assert connection.scalar(sa.text(
        "SELECT count(DISTINCT id) FROM test_case_component WHERE test_case_id=:c"
    ), {"c": case}) == 8
    connection.execute(sa.text("DELETE FROM test_step WHERE test_case_id=:c"), {"c": case})
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM test_assertion WHERE test_case_id=:c AND step_id IS NULL"
    ), {"c": case}) == 2


def test_component_ids_and_live_only_uniqueness_survive_step_replacement(connection):
    case = _case(connection, _project(connection))
    args = {"c": case, "id": 700001}
    for sql in (
        "INSERT INTO test_step (id, test_case_id, name) VALUES (:id, :c, 'open')",
        "INSERT INTO test_assertion (id, test_case_id, step_id) VALUES (:id, :c, :id)",
        "INSERT INTO test_case_precondition (id, test_case_id) VALUES (:id, :c)",
        "INSERT INTO test_case_data (id, test_case_id, name) VALUES (:id, :c, 'account')",
    ):
        connection.execute(sa.text(sql), args)
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM test_case_component WHERE test_case_id=:c AND public_id=:id"
    ), args) == 4
    assert connection.execute(sa.text(
        "SELECT s.kind, s.public_id FROM test_case_component a JOIN test_case_component s "
        "ON s.id=a.step_component_id WHERE a.kind='ASSERTION' AND a.public_id=:id"
    ), args).one() == ("STEP", 700001)
    connection.execute(sa.text("UPDATE test_case_data SET deleted_at=now() WHERE id=:id"), args)
    connection.execute(sa.text("INSERT INTO test_case_data (test_case_id,name) VALUES (:c,'account')"), args)
    _reject(connection, "UPDATE test_case_data SET deleted_at=NULL WHERE id=:id", id=args["id"])
    connection.execute(sa.text("DELETE FROM test_step WHERE test_case_id=:c"), args)
    assert connection.execute(sa.text("SELECT step_id FROM test_assertion WHERE id=:id"), args).one() == (None,)
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM test_case_component WHERE test_case_id=:c"
    ), args) == 4


def test_plan_deletion_clears_run_and_preserves_same_public_suite(connection):
    project = _project(connection)
    case = _case(connection, project)
    args = {"p": project, "c": case, "id": 700002}
    for sql in (
        "INSERT INTO test_plan (id, project_id, name) VALUES (:id, :p, 'same name')",
        "INSERT INTO test_suite (id, project_id, name) VALUES (:id, :p, 'same name')",
        "INSERT INTO test_plan_suite (id, plan_id, suite_id) VALUES (:id, :id, :id)",
        "INSERT INTO test_suite_case (id, suite_id, test_case_id) VALUES (:id, :id, :c)",
    ):
        connection.execute(sa.text(sql), args)
    run = connection.scalar(sa.text(
        "INSERT INTO test_run (project_id, plan_id) VALUES (:p, :id) RETURNING id"
    ), args)
    assert connection.scalar(sa.text(
        "SELECT count(*) FROM test_collection_member WHERE public_id=:id"
    ), args) == 2
    _reject(connection, "INSERT INTO test_plan_suite (plan_id, suite_id) VALUES (:id,:id)", id=args["id"])
    connection.execute(sa.text("UPDATE test_plan_suite SET deleted_at=now() WHERE id=:id"), args)
    connection.execute(sa.text("INSERT INTO test_plan_suite (plan_id,suite_id) VALUES (:id,:id)"), args)
    connection.execute(sa.text("DELETE FROM test_plan WHERE id=:id"), args)
    assert connection.execute(sa.text("SELECT plan_id FROM test_run WHERE id=:run"), {"run": run}).one() == (None,)
    assert connection.scalar(sa.text("SELECT count(*) FROM test_plan_suite WHERE plan_id=:id"), args) == 0
    assert connection.scalar(sa.text("SELECT test_case_id FROM test_suite_case WHERE id=:id"), args) == case
    _reject(connection, "INSERT INTO test_run (project_id, plan_id) VALUES (:p,:id)", **args)


def test_web_save_and_recycle_use_typed_component_ids(connection):
    from app.core.models.identity import User
    from app.features.web_testing.schemas import CaseInput
    from app.features.web_testing.services.case_service import save_case
    from app.lifecycle.service import delete_resource, restore_recycle_item

    project = _project(connection)
    with Session(connection, join_transaction_mode="create_savepoint") as db:
        owner = db.scalar(sa.text("SELECT owner_id FROM project WHERE id=:p"), {"p": project})
        actor = db.get(User, owner)
        body = CaseInput(name="browser", steps=[{"name": "open", "operation": "NAVIGATE", "value": "/first"}])
        case = save_case(db, project, body, actor)
        step = db.scalar(sa.text("SELECT id FROM test_step WHERE test_case_id=:c"), {"c": case["id"]})
        # Reserve the same public ID above the ordinary test fixtures' sequences.
        params = {"c": case["id"], "s": 700003}
        db.execute(sa.text("UPDATE test_step SET id=:s WHERE id=:old"), {**params, "old": step})
        db.execute(sa.text(
            "INSERT INTO test_assertion (id,test_case_id,step_id) VALUES (:s,:c,:s)"
        ), params)
        db.commit()
        assertion_item, _ = delete_resource(db, "test_assertion", params["s"], actor=actor)
        step_item, _ = delete_resource(db, "test_step", params["s"], actor=actor)
        assert assertion_item.id != step_item.id
        restore_recycle_item(db, step_item.id, actor)
        restore_recycle_item(db, assertion_item.id, actor)
        assert db.execute(sa.text("SELECT step_id FROM test_assertion WHERE id=:s"), params).one() == (700003,)
        body = CaseInput(name="browser", revision=case["revision"],
                         steps=[{"name": "next", "operation": "NAVIGATE", "value": "/next"}])
        updated = save_case(db, project, body, actor, case_id=case["id"])
        assert [row["name"] for row in updated["steps"]] == ["next"]
        assert db.execute(sa.text(
            "SELECT step_id, deleted_at FROM test_assertion WHERE id=:s"
        ), params).one() == (None, None)


def test_populated_test_asset_upgrade_and_downgrade(isolated_migration_database):
    config, engine = isolated_migration_database
    command.downgrade(config, "0102")
    public = 500101
    with engine.begin() as conn:
        project, other_project = _project(conn), _project(conn)
        case, other_case = _case(conn, project), _case(conn, other_project)
        params = {"id": public, "p": project, "other": other_project, "c": case, "foreign_case": other_case}
        for sql in (
            "INSERT INTO test_plan (id, project_id, name) VALUES (:id,:p,'nightly')",
            "INSERT INTO test_suite (id, project_id, name) VALUES (:id,:other,'nightly')",
            "INSERT INTO test_plan_suite (id, plan_id,suite_id) VALUES (:id,:id,:id)",
            "INSERT INTO test_step (id, test_case_id, name, sort) VALUES (:id,:c,'query',7)",
            "INSERT INTO test_assertion (id, test_case_id, step_id) VALUES (:id,:foreign_case,:id)",
            "INSERT INTO test_case_precondition (id, test_case_id, target) VALUES (:id,:c,'account')",
            "INSERT INTO test_case_data (id, test_case_id, name, value, deleted_at) VALUES (:id,:c,'key','old',now())",
            "INSERT INTO test_case_data (test_case_id, name, value) VALUES (:c,'key','current')",
        ):
            conn.execute(sa.text(sql), params)
        conn.exec_driver_sql("SELECT setval('test_step_id_seq', 510000)")
    with pytest.raises(ValueError, match="Cross-project membership"):
        command.upgrade(config, "0103")
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE test_suite SET project_id=:p WHERE id=:id"), params)
        conn.execute(sa.text("INSERT INTO test_suite_case (id,suite_id,test_case_id) VALUES (:id,:id,:c)"), params)
    command.upgrade(config, "0104")
    with pytest.raises(ValueError, match="references step"):
        command.upgrade(config, "0105")
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE test_assertion SET test_case_id=:c WHERE id=:id"), params)
    command.upgrade(config, "0105")
    with engine.begin() as conn:
        ref = conn.execute(sa.text(
            "SELECT a.public_id,s.public_id,s.sort FROM test_case_component a JOIN test_case_component s "
            "ON s.id=a.step_component_id WHERE a.kind='ASSERTION' AND a.test_case_id=:c"
        ), params).one()
        assert ref == (public, public, 7)
        assert conn.scalar(sa.text(
            "INSERT INTO test_step (test_case_id,name) VALUES (:c,'temporary') RETURNING id"
        ), params) == 510001
        conn.execute(sa.text("DELETE FROM test_step WHERE id=510001"))
        conn.execute(sa.text("UPDATE test_case_data SET value='updated' WHERE id=:id"), params)
        conn.execute(sa.text("DELETE FROM test_suite_case WHERE id=:id"), params)
    command.downgrade(config, "0102")
    with engine.begin() as conn:
        assert conn.execute(sa.text(
            "SELECT value, deleted_at IS NOT NULL FROM test_case_data WHERE id=:id"
        ), params).one() == ("updated", True)
        assert conn.execute(sa.text("SELECT step_id FROM test_assertion WHERE id=:id"), params).one() == (public,)
        assert conn.scalar(sa.text("SELECT count(*) FROM test_suite_case WHERE id=:id"), params) == 0
        assert conn.scalar(sa.text("INSERT INTO test_step (test_case_id, name) VALUES (:c,'next') RETURNING id"),
                           params) == 510002
    command.upgrade(config, "0105")
