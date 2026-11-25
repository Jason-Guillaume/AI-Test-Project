"""第一阶段的九张基线表。固定的 PostgreSQL DDL 保留历史字段、约束、注释和索引。"""
from alembic_support.frozen_schema import execute, restore_table

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    restore_table("0001", "baseline")


def downgrade() -> None:
    execute('DROP TABLE notification, environment, model_configuration, project_outbound_target, '
            'project_member, project, organization_member, organization, "user"')
