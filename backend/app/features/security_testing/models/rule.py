"""security_mutation_rule：结构化变异规则。"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityMutationRule(Base):
    """一条变异规则：改哪里、怎么改、期望什么、什么级别。

    全部是结构化配置，不允许脚本。``mutation_config`` 出现
    ``script`` / ``python`` / ``sql`` / ``shell`` / ``payload_file`` / ``command``
    任一键时服务层直接拒绝（SECURITY_MUTATION_INVALID）。

    ``severity`` 只是规则上的默认级别；执行时由 ``runtime/severity.py`` 按结果重算，
    不允许模型单独决定级别。
    """

    __tablename__ = "security_mutation_rule"
    __table_args__ = (
        Index("ix_security_rule_strategy_sort", "strategy_id", "enabled", "sort"),
        {"comment": "结构化变异规则：字段/位置/算子/期望/级别，禁止脚本"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=True, index=True, comment="所属平台项目ID；空 = 系统规则",
    )
    strategy_id = Column(
        Integer, ForeignKey("security_strategy.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属策略ID",
    )
    name = Column(String(200), nullable=False, comment="规则名称")
    mutation_type = Column(
        String(40), nullable=False,
        comment="变异类型（算子白名单），如 REMOVE_TOKEN / IDOR / ZERO",
    )
    target_location = Column(
        String(20), nullable=False,
        comment="目标位置：HEADER/QUERY/PATH/BODY/METHOD/REQUEST",
    )
    target_field = Column(
        String(200), nullable=True,
        comment="目标字段，如 Authorization、project_id、$.task_id；"
                "参数类模板留空表示执行前按 Schema 展开",
    )
    operator = Column(
        String(40), nullable=False,
        comment="算子名，与 mutation_type 同集；禁止自由字符串脚本",
    )
    mutation_config = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json"),
        comment="结构化变异参数；禁止出现 script/python/sql/shell/payload_file/command 键",
    )
    expected_security_behavior = Column(
        String(40), nullable=False,
        comment="安全期望：EXPECTED_DENY/EXPECTED_ALLOW/EXPECTED_VALIDATION_ERROR/"
                "EXPECTED_IDEMPOTENT",
    )
    expected_status_codes = Column(
        JSON, nullable=True, comment="期望状态码列表，如 [401, 403]",
    )
    severity = Column(
        String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"),
        comment="规则默认级别：INFO/LOW/MEDIUM/HIGH/CRITICAL（执行时按结果重算）",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用",
    )
    confirmation_required = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否需要成员确认高风险；未确认时不发请求，结果为 SKIPPED",
    )
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="同策略内排序",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
