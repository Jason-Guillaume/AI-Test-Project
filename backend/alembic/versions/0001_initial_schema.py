"""第一阶段基线表结构。

一次性创建第一阶段所需的 9 张表：
    user / organization / organization_member / project / project_member
    project_outbound_target / model_configuration / environment / notification

迁移内容直接由 app.models 中声明的 SQLAlchemy 2.x ORM 元数据生成，
保证 Alembic 产物与 ORM 定义（含索引、约束、命名）始终一致；
后续结构变更在此基础上追加 0002+ 的显式 op 迁移。

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""

from __future__ import annotations

from alembic import op


# 版本链起点：revision="0001"、down_revision=None 表示这是最初的基线迁移。
revision = "0001"
down_revision = None
# 本迁移不启用分支（branch/merge），版本链保持单线演进。
branch_labels = None
depends_on = None


def upgrade() -> None:
    """正向迁移：按 ORM 元数据一次性建出第一阶段的全部表。"""
    # 集中导入所有 ORM 模型，确保 Base.metadata 完整。
    import app.models  # noqa: F401
    from app.shared.database import Base

    bind = op.get_bind()
    # create_all 只建「尚不存在的表」，不修改已存在的表结构——
    # 因此本基线迁移必须在空库上执行，后续变更改走 0002+ 的显式 op 迁移。
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """反向迁移：删除基线建出的全部表（等价于回到初始空库）。"""
    import app.models  # noqa: F401
    from app.shared.database import Base

    # drop_all 会连带删除表内所有数据，仅在需要彻底重置时使用。
    Base.metadata.drop_all(bind=op.get_bind())
