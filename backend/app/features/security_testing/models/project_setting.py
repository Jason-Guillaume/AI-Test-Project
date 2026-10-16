"""security_project_setting：项目级安全执行环境开关（一行一个平台项目）。"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class SecurityProjectSetting(Base):
    """项目级安全执行环境开关。

    生产永远拒绝：服务层与执行器都不读 ``allow_production``，这一列只为记录
    用户意图（PUT 时即使用户传 true 也照存，但不生效）。
    """

    __tablename__ = "security_project_setting"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_security_setting_project"),
        {"comment": "项目级安全执行环境开关：生产永远拒绝，allow_production 仅记录意图"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # 不再单独建 ix：project_id 已被 uq_security_setting_project 唯一索引覆盖，
    # 再加一个非唯一索引纯属重复扫描。
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, comment="所属平台项目ID",
    )
    allow_dev = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="允许在开发环境发安全变异请求",
    )
    allow_test = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="允许在测试环境发安全变异请求",
    )
    allow_staging = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="允许在预发环境执行（项目管理员可打开）；未知环境名按预发处理",
    )
    allow_production = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="仅记录意图：服务层忽略此列，生产永远拒绝",
    )
    updated_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, comment="最后修改人",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")
