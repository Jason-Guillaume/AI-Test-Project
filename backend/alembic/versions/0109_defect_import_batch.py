"""缺陷 Excel 导入预览与幂等批次表。

保存预览标识、用户/项目/标准化摘要绑定关系、预览有效期以及确认提交后的幂等回执，
用于防止并发重复提交并支持相同文件内容的历史批次提示。

Revision ID: 0109
Revises: 0108
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    """返回当前库中已存在的表名集合，保证迁移幂等。"""
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    """返回指定表已存在的索引名集合。"""
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    """创建 defect_import_batch 表及唯一/查询索引。"""
    if "defect_import_batch" not in _tables():
        op.create_table(
            "defect_import_batch",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="导入批次编号"),
            sa.Column("preview_token", sa.String(length=36), nullable=False, comment="预览标识（UUID），确认提交的唯一幂等键"),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("project.id", ondelete="CASCADE"),
                nullable=False,
                comment="目标项目ID",
            ),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="SET NULL"),
                nullable=True,
                comment="预览与提交人ID",
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'PREVIEW'"),
                comment="批次状态：PREVIEW 待确认 / COMMITTED 已提交",
            ),
            sa.Column("file_name", sa.String(length=255), nullable=False, comment="原始上传文件名"),
            sa.Column("file_hash", sa.String(length=64), nullable=False, comment="原始上传文件 SHA-256 摘要"),
            sa.Column("content_digest", sa.String(length=64), nullable=False, comment="标准化导入数据的 SHA-256 摘要"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="待创建缺陷条数"),
            sa.Column("payload_json", sa.JSON(), nullable=False, comment="校验通过后的标准化行列表"),
            sa.Column("result_json", sa.JSON(), nullable=True, comment="确认提交后的幂等回执"),
            sa.Column("expires_at", sa.DateTime(), nullable=False, comment="预览有效期截止时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), comment="创建时间"),
            sa.Column("committed_at", sa.DateTime(), nullable=True, comment="确认提交时间"),
            sa.UniqueConstraint("preview_token", name="uq_defect_import_preview_token"),
            comment="缺陷 Excel 导入预览快照与确认幂等回执",
        )
    if "ix_defect_import_project_digest_status" not in _indexes("defect_import_batch"):
        op.create_index(
            "ix_defect_import_project_digest_status",
            "defect_import_batch",
            ["project_id", "content_digest", "status", "committed_at"],
        )
    if "ix_defect_import_project_created" not in _indexes("defect_import_batch"):
        op.create_index(
            "ix_defect_import_project_created",
            "defect_import_batch",
            ["project_id", "created_at"],
        )


def downgrade() -> None:
    """删除 defect_import_batch 表及其索引。"""
    if "defect_import_batch" in _tables():
        op.drop_table("defect_import_batch")
