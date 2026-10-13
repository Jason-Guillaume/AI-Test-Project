"""业务流程（Business Flow）ORM 模型。

业务流程表示一个完整业务过程（如「创建并执行AI选址任务」），归属于项目与业务域，
包含多个按顺序编排的业务动作（Business Action）。

status ∈ {DRAFT, ACTIVE, DEPRECATED}，由服务层校验。version 为流程版本号，复制/启用
等操作可递增。feature-local 表，由迁移 0004 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class BusinessFlow(Base):
    """业务流程：一组有序业务动作的完整业务过程。"""

    __tablename__ = "business_flow"
    __table_args__ = (
        UniqueConstraint("domain_id", "name", name="uq_business_flow_domain_name"),
        Index("ix_business_flow_project_status", "project_id", "status"),
        {"comment": "业务流程：一组有序业务动作的完整业务过程"},
    )
    # 唯一约束 (domain_id, name)：同一业务域下流程名不重复。
    # (project_id, status) 索引服务于按项目列出启用/停用流程。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    # project_id 冗余存储：流程虽归属业务域，但项目级查询/权限校验需要直接拿到 project_id，
    # 避免每次都联表 business_domain → 取项目。CASCADE 保证项目删除时流程一并清理。
    domain_id = Column(
        Integer,
        ForeignKey("business_domain.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务域ID",
    )
    # domain_id 带 ondelete=CASCADE：业务域被删除时其下流程一并清理。
    name = Column(String(200), nullable=False, comment="业务流程名称")
    description = Column(String(1000), nullable=True, comment="业务流程描述")
    status = Column(
        String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        index=True, comment="状态：DRAFT/ACTIVE/DEPRECATED",
    )
    version = Column(
        Integer, nullable=False, default=1, server_default=text("1"), comment="流程版本号",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
