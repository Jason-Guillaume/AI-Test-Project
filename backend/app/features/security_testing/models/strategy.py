"""security_strategy：安全策略（系统模板 / 项目自定义）。"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityStrategy(Base):
    """一条安全策略。

    - ``project_id`` 可空：空 = 系统模板（scope=SYSTEM、builtin=true），
      删除平台项目时级联删除项目策略，不删除系统模板。
    - 系统模板禁止项目成员修改规则体（服务层 403）。
    - 预留攻击类（INJECTION / RATE_LIMIT / UPLOAD / SSRF）可以保存，但
      enabled 在服务层被强制 false，执行时直接拒绝。
    """

    __tablename__ = "security_strategy"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "strategy_key", name="uq_security_strategy_project_key"
        ),
        Index("ix_security_strategy_project_category", "project_id", "category"),
        Index("ix_security_strategy_scope_enabled", "scope", "enabled"),
        # 部分唯一索引在迁移里用 postgresql_where 表达：系统模板 project_id 为空，
        # 普通 UNIQUE(project_id, strategy_key) 拦不住重复模板（NULL 不相等）。
        Index(
            "uq_security_strategy_system_key", "strategy_key", unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        {"comment": "安全策略：SYSTEM 模板 / PROJECT 自定义"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=True, index=True, comment="所属平台项目ID；空 = 系统模板",
    )
    scope = Column(String(20), nullable=False, comment="策略范围：SYSTEM / PROJECT")
    name = Column(String(200), nullable=False, comment="策略名称")
    strategy_key = Column(
        String(100), nullable=False,
        comment="策略唯一键：^[A-Z][A-Z0-9_]{0,99}$，如 AUTH_BASIC",
    )
    category = Column(
        String(40), nullable=False,
        comment="策略类别：AUTHENTICATION/AUTHORIZATION/IDOR/PARAMETER/HEADER/METHOD/"
                "REPLAY/DUPLICATE_SUBMIT/BUSINESS_STATE/SEQUENCE_BYPASS 可执行；"
                "INJECTION/RATE_LIMIT/UPLOAD/SSRF 只保存不执行",
    )
    description = Column(String(1000), nullable=True, comment="策略说明")
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用（停用后不参与计划生成）",
    )
    risk_level = Column(
        String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"),
        comment="策略默认级别：INFO/LOW/MEDIUM/HIGH/CRITICAL",
    )
    builtin = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="系统模板标记：true 时禁止项目成员修改规则体",
    )
    created_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")
