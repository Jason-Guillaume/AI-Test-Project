"""项目、项目成员与项目出站目标。

沿用旧项目的表名、字段与约束语义：
- project.name 全局唯一（与旧库一致，不做组织内唯一）
- project_member.role ∈ {viewer, member, editor}，虚拟角色 owner/admin 由服务层推导
- project_outbound_target：项目作用域的目标服务授权，仅允许批准的 scheme/host/port
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class Project(Base):
    """测试项目及负责人信息。"""

    __tablename__ = "project"
    __table_args__ = {"comment": "测试项目及负责人信息"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True, comment="项目名称")
    # name 全局唯一（沿用旧库语义，没有做组织内唯一）：跨组织也不能重名，
    # 因此创建/改名前的重名检查必须按全局范围做。
    description = Column(String(500), nullable=True, comment="项目描述")
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=False, comment="负责人ID")
    # owner_id 用于推导「owner」虚拟角色：该用户默认可绕过 project_member 表直接获得项目权限。
    organization_id = Column(Integer, ForeignKey("organization.id"), nullable=True, index=True)
    # 允许为空：兼容未归属任何组织的历史项目；按组织过滤列表时必须排除 NULL。
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
                        comment="更新时间")


class ProjectMember(Base):
    """项目成员及其访问角色。"""

    __tablename__ = "project_member"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_project_member"),
        UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
        {"comment": "项目成员及其数据访问角色"},
    )
    # 命名主键 + (project_id, user_id) 唯一约束：一个用户在一个项目里只保留一行，
    # 因此调整授权是「整体替换角色」而不是追加记录。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(30), nullable=False, default="member", server_default=text("'member'"),
                  comment="项目角色： viewer/member/editor")
    # 本表只存 viewer/member/editor；owner/admin 属虚拟角色，
    # 由服务层根据 project.owner_id（及组织管理员身份）在查询时推导，不落地存储。
    created_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ProjectOutboundTarget(Base):
    """项目出站目标、协议端口及生产目标授权。"""

    __tablename__ = "project_outbound_target"
    __table_args__ = (
        UniqueConstraint("project_id", "scheme", "host", "port", name="uq_project_outbound_target"),
        {"comment": "项目出站目标、协议端口及生产目标授权"},
    )
    # 授权粒度到 (project, scheme, host, port) 四元组：唯一约束保证同一目标不会被重复登记，
    # 服务层据此判断某次外连是否落在该项目的授权范围内。

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    scheme = Column(String(8), nullable=False)
    host = Column(String(253), nullable=False)
    port = Column(Integer, nullable=False)
    # scheme/host/port 的取值应在写入侧校验（只允许批准的 scheme 与目标地址，见模块 docstring），
    # 数据库层不做枚举约束，因此合法性完全依赖服务层防线。
    is_production = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # 生产目标需要更高的审批权限：写入这类记录应触发权限判定，而不是任意成员都能加。
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    # enabled 用于「保留授权记录但临时放行/封禁」，与删除不同：审计链不断。
    approved_by = Column(Integer, ForeignKey("user.id"), nullable=False)
    # 记录审批人，用于追溯生产目标是谁授权的（不可为空，保证每条授权都可归因）。
    created_at = Column(DateTime, nullable=False, server_default=func.now())
