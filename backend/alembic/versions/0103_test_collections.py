"""Unify plans, suites and their two typed, project-scoped membership relations."""

import sqlalchemy as sa
from alembic import op

from alembic_support.frozen_schema import execute
from alembic_support.test_asset_projection import AssetProjection, external_keys
from app.features.test_management.storage_schema_v1 import collection_tables

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None

_COLLECTIONS = (
    AssetProjection("test_plan", "test_collection", "PLAN"),
    AssetProjection("test_suite", "test_collection", "SUITE"),
    AssetProjection("test_plan_suite", "test_collection_member", "PLAN_SUITE"),
    AssetProjection("test_suite_case", "test_collection_member", "SUITE_CASE"),
)


def upgrade():
    execute("LOCK TABLE test_case, test_plan, test_suite, test_plan_suite, test_suite_case, test_run "
            "IN ACCESS EXCLUSIVE MODE")
    invalid = op.get_bind().exec_driver_sql("""
        SELECT 'test_plan_suite', m.id FROM test_plan_suite m
        JOIN test_plan p ON p.id=m.plan_id JOIN test_suite s ON s.id=m.suite_id
        WHERE p.project_id <> s.project_id
        UNION ALL
        SELECT 'test_suite_case', m.id FROM test_suite_case m
        JOIN test_suite s ON s.id=m.suite_id JOIN test_case c ON c.id=m.test_case_id
        WHERE s.project_id <> c.project_id
        LIMIT 1
    """).first()
    if invalid:
        raise ValueError(f"Cross-project membership in {invalid[0]}, public ID {invalid[1]}")
    op.create_unique_constraint("uq_test_case_id_project", "test_case", ["id", "project_id"])
    for table in collection_tables(external_keys()):
        table.create(op.get_bind())
    execute("""
        CREATE FUNCTION test_member_project() RETURNS trigger LANGUAGE plpgsql AS $member$
        BEGIN
            IF TG_OP = 'INSERT' AND NEW.project_id IS NOT NULL THEN RETURN NEW; END IF;
            SELECT project_id INTO NEW.project_id FROM test_collection WHERE suite_public_id = NEW.suite_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unknown suite %', NEW.suite_id USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END;
        $member$
    """)
    execute("CREATE TRIGGER test_member_project BEFORE INSERT OR UPDATE OF suite_id ON test_collection_member "
            "FOR EACH ROW EXECUTE FUNCTION test_member_project()")
    for projection in _COLLECTIONS:
        projection.fold()
    [legacy_fk] = [fk for fk in sa.inspect(op.get_bind()).get_foreign_keys("test_run")
                   if fk["constrained_columns"] == ["plan_id"] and fk["referred_table"] == _COLLECTIONS[0].staged]
    op.drop_constraint(legacy_fk["name"], "test_run", type_="foreignkey")
    op.create_foreign_key("fk_test_run_plan_collection", "test_run", "test_collection",
                          ["plan_id"], ["plan_public_id"], ondelete="SET NULL")
    for projection in reversed(_COLLECTIONS):
        op.drop_table(projection.staged)
    execute("ANALYZE test_collection, test_collection_member")


def downgrade():
    execute("LOCK TABLE test_case, test_collection, test_collection_member, test_run IN ACCESS EXCLUSIVE MODE")
    for projection in _COLLECTIONS:
        projection.unfold()
    op.drop_constraint("fk_test_run_plan_collection", "test_run", type_="foreignkey")
    op.create_foreign_key("test_run_plan_id_fkey", "test_run", "test_plan", ["plan_id"], ["id"], ondelete="SET NULL")
    for projection in reversed(_COLLECTIONS):
        execute(f"DROP VIEW {projection.staged}")
    op.drop_table("test_collection_member")
    op.drop_table("test_collection")
    execute("DROP FUNCTION test_member_project()")
    op.drop_constraint("uq_test_case_id_project", "test_case", type_="unique")
