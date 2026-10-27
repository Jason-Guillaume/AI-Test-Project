"""为缺陷与真实测试结果或安全疑似问题建立可追溯关系。"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    """新增来源关联表；来源或缺陷删除时只移除关联，不影响其他业务记录。"""
    op.create_table(
        "defect_source_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bug_id", sa.Integer(), sa.ForeignKey("bug.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_execution_id", sa.Integer(), sa.ForeignKey("case_execution.id", ondelete="CASCADE")),
        sa.Column("security_finding_id", sa.Integer(), sa.ForeignKey("security_finding.id", ondelete="CASCADE")),
        sa.Column("request_key", sa.String(100)),
        sa.Column("request_digest", sa.String(64)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("(case_execution_id IS NOT NULL AND security_finding_id IS NULL) OR (case_execution_id IS NULL AND security_finding_id IS NOT NULL)", name="ck_defect_source_exactly_one"),
        sa.UniqueConstraint("bug_id", "case_execution_id", name="uq_defect_case_execution"),
        sa.UniqueConstraint("bug_id", "security_finding_id", name="uq_defect_security_finding"),
        sa.UniqueConstraint("project_id", "request_key", name="uq_defect_source_request"),
    )
    op.create_index("ix_defect_source_project", "defect_source_link", ["project_id"])
    op.create_index("ix_defect_source_case", "defect_source_link", ["case_execution_id"])
    op.create_index("ix_defect_source_finding", "defect_source_link", ["security_finding_id"])


def downgrade():
    """回退关联表，不删除缺陷或来源记录。"""
    op.drop_table("defect_source_link")
