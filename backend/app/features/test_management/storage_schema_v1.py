"""Frozen PostgreSQL table definitions introduced by revisions 0103 and 0105.

The legacy write interfaces select a single generated kind. Their original
column defaults fill the required discriminator fields on INSERT, so PostgreSQL
can update, lock and delete projected rows natively.
"""

import sqlalchemy as sa


def _identity_columns():
    return (
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("public_id", sa.Integer, nullable=False, comment="类型内的原公开 ID"),
    )


def _lifecycle_columns():
    return (
        sa.Column("deleted_at", sa.DateTime),
        sa.Column("deleted_by", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("deletion_reason", sa.String(500)),
        sa.Column("deletion_batch_id", sa.String(36)),
    )


def _timestamp(name):
    return sa.Column(name, sa.DateTime, server_default=sa.func.now(), nullable=False)


def collection_tables(metadata):
    collection = sa.Table(
        "test_collection", metadata,
        *_identity_columns(),
        sa.Column("kind", sa.String(12), sa.Computed(
            "CASE WHEN suite_type IS NULL THEN 'PLAN' ELSE 'SUITE' END", persisted=True
        ), nullable=False),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("environment_id", sa.Integer, sa.ForeignKey("environment.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20)),
        sa.Column("execution_mode", sa.String(20)),
        sa.Column("suite_type", sa.String(20)),
        sa.Column("enabled", sa.Boolean),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
        _timestamp("created_at"), _timestamp("updated_at"), *_lifecycle_columns(),
        sa.Column("plan_public_id", sa.Integer, sa.Computed(
            "CASE WHEN suite_type IS NULL THEN public_id END", persisted=True
        )),
        sa.Column("suite_public_id", sa.Integer, sa.Computed(
            "CASE WHEN suite_type IS NOT NULL THEN public_id END", persisted=True
        )),
        sa.CheckConstraint(
            "(suite_type IS NULL AND status IS NOT NULL AND execution_mode IS NOT NULL AND enabled IS NULL)"
            " OR (suite_type IS NOT NULL AND enabled IS NOT NULL AND status IS NULL "
            "AND execution_mode IS NULL AND environment_id IS NULL)", name="ck_test_collection_fields",
        ),
        sa.UniqueConstraint("kind", "public_id", name="uq_test_collection_public"),
        sa.UniqueConstraint("plan_public_id", name="uq_test_collection_plan"),
        sa.UniqueConstraint("plan_public_id", "project_id", name="uq_test_collection_plan_project"),
        sa.UniqueConstraint("suite_public_id", "project_id", name="uq_test_collection_suite_project"),
        sa.Index("uq_test_collection_live_name", "project_id", "kind", "name", unique=True,
                 postgresql_where=sa.text("deleted_at IS NULL")),
        sa.Index("ix_test_collection_project_status", "project_id", "status",
                 postgresql_where=sa.text("kind = 'PLAN'")),
        sa.Index("ix_test_collection_project_enabled", "project_id", "enabled",
                 postgresql_where=sa.text("kind = 'SUITE'")),
        sa.Index("ix_test_collection_environment", "environment_id",
                 postgresql_where=sa.text("environment_id IS NOT NULL")),
        comment="项目测试计划与套件，以类型和公开 ID 寻址",
    )
    member = sa.Table(
        "test_collection_member", metadata,
        *_identity_columns(),
        sa.Column("kind", sa.String(12), sa.Computed(
            "CASE WHEN plan_id IS NULL THEN 'SUITE_CASE' ELSE 'PLAN_SUITE' END", persisted=True
        ), nullable=False),
        sa.Column("project_id", sa.Integer, nullable=False),
        sa.Column("plan_id", sa.Integer),
        sa.Column("suite_id", sa.Integer, nullable=False),
        sa.Column("test_case_id", sa.Integer),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean),
        _timestamp("created_at"), *_lifecycle_columns(),
        sa.CheckConstraint(
            "(plan_id IS NOT NULL AND test_case_id IS NULL AND enabled IS NULL) OR "
            "(plan_id IS NULL AND test_case_id IS NOT NULL AND enabled IS NOT NULL)",
            name="ck_test_collection_member_fields",
        ),
        sa.ForeignKeyConstraint(["plan_id", "project_id"],
                                ["test_collection.plan_public_id", "test_collection.project_id"],
                                name="fk_test_member_plan", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["suite_id", "project_id"],
                                ["test_collection.suite_public_id", "test_collection.project_id"],
                                name="fk_test_member_suite", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id", "project_id"], ["test_case.id", "test_case.project_id"],
                                name="fk_test_member_case", ondelete="CASCADE"),
        sa.UniqueConstraint("kind", "public_id", name="uq_test_member_public"),
        sa.Index("uq_test_member_live_plan_suite", "plan_id", "suite_id", unique=True,
                 postgresql_where=sa.text("plan_id IS NOT NULL AND deleted_at IS NULL")),
        sa.Index("uq_test_member_live_suite_case", "suite_id", "test_case_id", unique=True,
                 postgresql_where=sa.text("test_case_id IS NOT NULL AND deleted_at IS NULL")),
        sa.Index("ix_test_member_plan_order", "plan_id", "sort", "public_id",
                 postgresql_where=sa.text("kind = 'PLAN_SUITE'")),
        sa.Index("ix_test_member_suite_order", "suite_id", "kind", "sort", "public_id"),
        sa.Index("ix_test_member_case", "test_case_id", postgresql_where=sa.text("test_case_id IS NOT NULL")),
        comment="同项目的计划套件和套件用例成员",
    )
    return collection, member


def component_table(metadata):
    return sa.Table(
        "test_case_component", metadata,
        # Every historical public key is a signed int32. Shifting the other
        # kinds by multiples of 2^32 produces globally unique internal keys.
        # Only STEP can be referenced by an int32 step_component_id.
        sa.Column("id", sa.BigInteger, sa.Computed(
            "public_id::bigint + CASE WHEN step_type IS NOT NULL THEN 0::bigint "
            "WHEN assertion_type IS NOT NULL THEN 4294967296::bigint "
            "WHEN precondition_type IS NOT NULL THEN 8589934592::bigint ELSE 12884901888::bigint END",
            persisted=True,
        ), nullable=False),
        sa.Column("public_id", sa.Integer, nullable=False, comment="类型内的原公开 ID"),
        sa.Column(
            "kind", sa.Enum("STEP", "ASSERTION", "PRECONDITION", "DATA", name="test_component_kind"),
            sa.Computed(
                "CASE WHEN step_type IS NOT NULL THEN 'STEP'::test_component_kind "
                "WHEN assertion_type IS NOT NULL THEN 'ASSERTION' WHEN precondition_type IS NOT NULL "
                "THEN 'PRECONDITION' WHEN value_type IS NOT NULL THEN 'DATA' END", persisted=True,
            ), nullable=False,
        ),
        sa.Column("test_case_id", sa.Integer, sa.ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort", sa.Integer, nullable=False, server_default="0"),
        sa.Column("step_name", sa.String(200)),
        sa.Column("step_type", sa.String(20)),
        sa.Column("target_type", sa.String(20)),
        sa.Column("target_id", sa.Integer),
        sa.Column("assertion_type", sa.String(30)),
        sa.Column("step_component_id", sa.Integer, comment="断言关联的内部步骤 ID"),
        sa.Column("source", sa.String(100)),
        sa.Column("path", sa.String(500)),
        sa.Column("operator", sa.String(20)),
        sa.Column("expected_value", sa.Text),
        sa.Column("precondition_type", sa.String(30)),
        sa.Column("target", sa.String(200)),
        sa.Column("description", sa.String(500)),
        sa.Column("config_json", sa.JSON),
        sa.Column("data_name", sa.String(100)),
        sa.Column("value_type", sa.String(20)),
        sa.Column("value", sa.Text),
        sa.Column("source_type", sa.String(20)),
        sa.Column("required", sa.Boolean),
        _timestamp("created_at"), _timestamp("updated_at"), *_lifecycle_columns(),
        sa.CheckConstraint("num_nonnulls(step_type, assertion_type, precondition_type, value_type) = 1",
                           name="ck_test_component_one_kind"),
        sa.CheckConstraint(
            "(step_type IS NOT NULL) = (step_name IS NOT NULL) AND "
            "(value_type IS NOT NULL) = (data_name IS NOT NULL) AND "
            "(value_type IS NOT NULL) = (source_type IS NOT NULL) AND "
            "(assertion_type IS NOT NULL OR precondition_type IS NOT NULL) = (operator IS NOT NULL) AND "
            "(assertion_type IS NOT NULL OR value_type IS NOT NULL) = (required IS NOT NULL)",
            name="ck_test_component_required",
        ),
        sa.CheckConstraint(
            "(step_type IS NOT NULL OR (target_type IS NULL AND target_id IS NULL)) AND "
            "(assertion_type IS NOT NULL OR (source IS NULL AND path IS NULL AND step_component_id IS NULL)) AND "
            "(precondition_type IS NOT NULL OR target IS NULL) AND (value_type IS NOT NULL OR value IS NULL) AND "
            "(operator IS NOT NULL OR expected_value IS NULL) AND "
            "(assertion_type IS NULL OR config_json IS NULL) AND "
            "(precondition_type IS NOT NULL OR value_type IS NOT NULL OR description IS NULL)",
            name="ck_test_component_fields",
        ),
        sa.UniqueConstraint("kind", "public_id", name="uq_test_component_public"),
        # Including the case in the FK target also prevents moving a referenced
        # step to another case. Its generated internal ID stays globally unique.
        sa.PrimaryKeyConstraint("id", "test_case_id", name="pk_test_case_component"),
        sa.ForeignKeyConstraint(
            ["step_component_id", "test_case_id"], ["test_case_component.id", "test_case_component.test_case_id"],
            name="fk_test_component_step", ondelete="SET NULL (step_component_id)",
        ),
        sa.Index("uq_test_component_live_data_name", "test_case_id", "data_name", unique=True,
                 postgresql_where=sa.text("kind = 'DATA' AND deleted_at IS NULL")),
        sa.Index("ix_test_component_case_order", "test_case_id", "kind", "sort", "public_id"),
        sa.Index("ix_test_component_step_reference", "step_component_id",
                 postgresql_where=sa.text("step_component_id IS NOT NULL")),
        comment="测试用例的步骤、断言、前置条件和数据项",
    )
