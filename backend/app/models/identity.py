"""用户、组织与组织成员。

沿用旧项目的表名、字段名、约束与默认值语义，保证与旧库结构一一对应：
- user：平台登录用户，role 为平台级角色（admin / test / dev，默认 test）
- organization：组织边界及负责人
- organization_member：组织成员角色（owner / admin / member）与模型授权
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class User(Base):
    """平台登录用户、角色及账号状态。"""

    __tablename__ = "user"
    __table_args__ = {"comment": "平台登录用户、角色及账号状态"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=True, index=True, comment="用户名")
    # unique 但 nullable=True：与旧库保持兼容（历史行可能没有用户名），
    # PostgreSQL 的 unique 约束允许多个 NULL 共存，因此不会互相冲突。
    hashed_password = Column(String(255), nullable=True, comment="加密密码")
    role = Column(String(20), nullable=False, default="test", server_default=text("'test'"),
                  comment="平台角色： admin/test/dev")
    # 平台级角色（admin/test/dev），是模型配置、环境管理等高危写操作的判定依据；
    # 注意它与组织角色、项目角色是三套互相独立的授权维度。
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否激活")
    # 置为 False 即等效于强制下线：认证入口会拒绝该账号，同时应递增 token_version。
    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"),
                           comment="JWT 撤销版本：修改密码、禁用、调整角色时递增使旧令牌失效")
    # token_version 递增点：改密码、禁用账号、调整角色时必须 +1，
    # JWT 校验侧会比对签发时快照与当前值，不一致即视为失效（无状态撤销的实现）。
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="注册时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
                        comment="更新时间")


class Organization(Base):
    """组织边界及负责人。"""

    __tablename__ = "organization"
    __table_args__ = {"comment": "组织边界及负责人"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    # owner_id 只是「负责人」标记；负责人同样应该有一行 organization_member（role=owner），
    # 由 ensure_personal_organization 等服务层逻辑负责保持一致。
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class OrganizationMember(Base):
    """组织成员、Agent 开放权限及模型分配。"""

    __tablename__ = "organization_member"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_organization_member_user"),
        {"comment": "组织成员、Agent 开放权限及模型分配"},
    )
    # 同一 (organization_id, user_id) 只允许一行：既是防重复授权的唯一约束，
    # 也让「取当前用户在本组织的角色」成为确定的单值查询。

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    # 两个外键都带 ondelete="CASCADE"：删除组织或用户时连带清理成员行，避免残留授权。
    role = Column(String(20), nullable=False, default="member", server_default=text("'member'"),
                  comment="组织角色： owner/admin/member")
    # 组织角色决定组织内可见性边界（谁能看本组织的模型配置、项目与执行记录）。
    agent_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"),
                           comment="是否开放智能体能力")
    # 组织级能力开关：关闭后该组织下的智能体相关接口应返回未接入/未授权提示。
    allowed_model_ids = Column(JSON, nullable=False, default=list, server_default=text("'[]'"),
                               comment="允许的模型 domain_id 列表")
    # 组织级模型授权白名单（存 domain_id，非自增 id）：空列表表示未授权任何模型，
    # 调用方按它做「该组织是否可用此模型」的过滤，属组织/项目可见性边界检查的一环。
    created_at = Column(DateTime, nullable=False, server_default=func.now())
