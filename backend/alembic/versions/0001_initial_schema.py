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


# 第一阶段基线 9 张表（feature-local 表由 0002+ 显式 op.create_table 建立）。
_BASELINE_TABLES = (
    "user",
    "organization",
    "organization_member",
    "project",
    "project_member",
    "project_outbound_target",
    "model_configuration",
    "environment",
    "notification",
)


def _baseline_tables() -> list:
    """按名从 Base.metadata 筛出基线 9 张表。

    取值用 ``Base.metadata.tables.items()``（字典，**不触发全表拓扑排序**）。
    测试收集期可能把 feature-local 模型（如 business_binding，其 api_id 外键指向
    api_interface）注册进 Base.metadata；若对这些「外键目标表尚未注册」的表一并
    ``create_all`` / ``drop_all``，会在 ``sort_tables_and_constraints`` 里访问
    ``fkc.referred_table`` 时抛 ``NoReferencedTableError``。这里显式按名筛出基线表，
    只对它们建/删，feature-local 表完全不受 0001 影响（由 0002+ 显式 op 迁移建立）。
    """
    import app.models  # noqa: F401  触发核心模型注册进 Base.metadata
    from app.shared.database import Base

    return [t for name, t in Base.metadata.tables.items() if name in _BASELINE_TABLES]


def upgrade() -> None:
    """正向迁移：按 ORM 元数据一次性建出第一阶段的全部基线表。"""
    # create_all(tables=...) 只建指定的基线表（checkfirst=True 幂等），不触碰
    # 测试收集期可能注册进 metadata 的 feature-local 表，避免未解析外键报错。
    # feature-local 表由 0002+ 的显式 op.create_table 建立。
    import app.models  # noqa: F401  触发核心模型注册进 Base.metadata
    from app.shared.database import Base

    Base.metadata.create_all(bind=op.get_bind(), tables=_baseline_tables())


def downgrade() -> None:
    """反向迁移：删除基线建出的全部表（等价于回到初始空库）。"""
    # drop_all(tables=...) 同样按名限定，避免对 feature-local 表排序引发外键错误。
    import app.models  # noqa: F401
    from app.shared.database import Base

    Base.metadata.drop_all(bind=op.get_bind(), tables=_baseline_tables())
