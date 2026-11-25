"""Store case details together, keeping typed public IDs and same-case step references."""

from alembic import op

from alembic_support.frozen_schema import execute
from alembic_support.test_asset_projection import AssetProjection, external_keys
from app.features.test_management.storage_schema_v1 import component_table

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None

_COMPONENTS = (
    AssetProjection("test_step", "test_case_component", "STEP", {"name": "step_name"}),
    AssetProjection("test_assertion", "test_case_component", "ASSERTION", {"step_id": "step_component_id"}),
    AssetProjection("test_case_precondition", "test_case_component", "PRECONDITION", {"type": "precondition_type"}),
    AssetProjection("test_case_data", "test_case_component", "DATA", {"name": "data_name"}),
)


def upgrade():
    execute("LOCK TABLE test_case, test_step, test_case_precondition, test_case_data, test_assertion "
            "IN ACCESS EXCLUSIVE MODE")
    invalid = op.get_bind().exec_driver_sql("""
        SELECT a.id, a.step_id FROM test_assertion a JOIN test_step s ON s.id=a.step_id
        WHERE a.test_case_id <> s.test_case_id LIMIT 1
    """).first()
    if invalid:
        raise ValueError(f"Assertion {invalid[0]} references step {invalid[1]} from another case")
    bind = op.get_bind()
    storage = component_table(external_keys())
    # Build secondary indexes from the finished data. All foreign keys and the
    # unique public identity are active during transfer.
    secondary_indexes = sorted(storage.indexes, key=lambda index: index.name)
    storage.indexes.clear()
    storage.create(bind)
    for projection in _COMPONENTS:
        projection.fold()
    for index in secondary_indexes:
        index.create(bind)
    for projection in reversed(_COMPONENTS):
        op.drop_table(projection.staged)
    execute("ANALYZE test_case_component")


def downgrade():
    execute("LOCK TABLE test_case, test_case_component IN ACCESS EXCLUSIVE MODE")
    for projection in _COMPONENTS:
        projection.unfold()
    for projection in reversed(_COMPONENTS):
        execute(f"DROP VIEW {projection.staged}")
    op.drop_table("test_case_component")
    execute("DROP TYPE test_component_kind")
