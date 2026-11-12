"""测试范围导航 ORM。

测试范围只负责目录归属，不复制接口、业务、页面或 Agent 的正文。
ASSET_LINK 用 asset_type + asset_id 指向已有资产；INBOX 是每个方向的待整理收件箱。
用例可以出现在多个节点（test_case_scope），被测对象另外记在 test_case_asset 和 TestCase 原有外键上。

已知限制：asset_id 是多态整数，不建跨表外键。资产删除后节点可能悬空，由读取侧显示为失效引用，不级联删用例。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base
from app.core.database.soft_delete import SoftDeleteBase


class TestScopeNode(SoftDeleteBase):
    """项目内某一测试方向的目录节点。parent_id 为空表示该方向的根。"""

    __tablename__ = "test_scope_node"
    __table_args__ = (
        Index("ix_test_scope_project_direction_parent", "project_id", "direction", "parent_id"),
        Index("ix_test_scope_asset", "project_id", "asset_type", "asset_id"),
        {"comment": "测试范围节点：导航层，不复制业务资产"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(String(10), nullable=False, comment="测试方向：API/UI/AI")
    parent_id = Column(Integer, ForeignKey("test_scope_node.id", ondelete="RESTRICT"), nullable=True)
    node_type = Column(String(20), nullable=False, comment="FOLDER/ASSET_LINK/INBOX")
    name = Column(String(200), nullable=False)
    description = Column(String(1000), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0, server_default=text("0"))
    status = Column(String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"))
    asset_type = Column(String(40), nullable=True, comment="指向的已有资产类型，目录节点为空")
    asset_id = Column(Integer, nullable=True, comment="已有资产 ID，不复制资产正文")
    is_system = Column(Boolean, nullable=False, default=False, server_default=text("false"), comment="系统待整理节点，不可删改父级")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TestCaseScope(Base):
    """用例在目录中的归属。一个用例可挂多个节点，目录不是唯一被测对象。"""

    __tablename__ = "test_case_scope"
    __table_args__ = (
        UniqueConstraint("test_case_id", "scope_node_id", name="uq_test_case_scope_case_node"),
        Index("ix_test_case_scope_node", "scope_node_id"),
        {"comment": "用例与测试范围节点的归属"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_node_id = Column(Integer, ForeignKey("test_scope_node.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class TestCaseAsset(Base):
    """用例实际关联的被测资产。与目录归属分开，允许一条用例覆盖多个资产。"""

    __tablename__ = "test_case_asset"
    __table_args__ = (
        UniqueConstraint("test_case_id", "asset_type", "asset_id", name="uq_test_case_asset_target"),
        {"comment": "用例与被测资产的关联，不替代 TestCase 上的执行外键"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_type = Column(String(40), nullable=False)
    asset_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class TestScopeMigrationCheck(Base):
    """迁移前后行数核对。正式资产表的前后数量必须相等。"""

    __tablename__ = "test_scope_migration_check"
    __table_args__ = ({"comment": "测试范围迁移的数量核对"},)

    id = Column(Integer, primary_key=True, autoincrement=True)
    metric = Column(String(80), nullable=False, unique=True)
    before_count = Column(Integer, nullable=False)
    after_count = Column(Integer, nullable=False)


class TestScopeApiBackfill(Base):
    """本次迁移回填了 api_id 的用例。降级时只清空这些行，不动原本已有的关联。"""

    __tablename__ = "test_scope_api_backfill"
    __table_args__ = ({"comment": "迁移唯一匹配回填的 api_id，供降级撤销"},)

    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="CASCADE"), primary_key=True)
