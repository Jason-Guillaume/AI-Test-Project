"""业务域（Business Domain）ORM 模型。

业务域属于项目，是业务流程的顶层分组容器（如「用户管理」「AI选址」「订单管理」）。
一个项目下可有多个业务域，按 sort 排序展示。

字段沿用平台约定：Integer 自增主键、内联 created_at/updated_at、project_id 外键
ondelete=CASCADE（项目删除时业务域一并清理）。status 为字符串列（ACTIVE/INACTIVE），
合法性由服务层校验，数据库不设 CHECK（与 bug.status / api_interface.status 一致）。

feature-local 表，由迁移 0004 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class BusinessDomain(Base):
    """业务域：项目下的业务流程分组容器。"""

    __tablename__ = "business_domain"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_business_domain_project_name"),
        Index("ix_business_domain_project_sort", "project_id", "sort"),
        {"comment": "业务域：项目下的业务流程分组容器"},
    )
    # 唯一约束 (project_id, name)：同一项目下业务域名称不重复。
    # (project_id, sort) 复合索引服务于左侧目录树按项目分组并按 sort 排序展示。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    # project_id 带 ondelete=CASCADE：项目被删除时业务域及下属流程/动作/绑定一并清理。
    name = Column(String(100), nullable=False, comment="业务域名称")
    description = Column(String(500), nullable=True, comment="业务域描述")
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="排序值，越小越靠前",
    )
    status = Column(
        String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"),
        index=True, comment="状态：ACTIVE/INACTIVE",
    )
    # status 不做数据库 CHECK：合法性由服务层校验，保持与 bug.status / api_interface.status 一致。
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
