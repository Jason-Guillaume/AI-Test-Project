"""业务流程执行记录 ORM 模型。

FlowExecution 代表一次业务流执行；ActionExecution 代表其中某个步骤的执行。
context_json 存放运行时变量（非配置数据），与 BusinessFlow 配置表分离。

status 字段均为 String（不设 sa.Enum），合法取值由服务层校验。
"""

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class FlowExecution(Base):
    """业务流程执行记录。"""

    __tablename__ = "flow_execution"
    __table_args__ = {"comment": "业务流程执行记录"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    flow_id = Column(Integer, ForeignKey("business_flow.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environment.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'PENDING'"), index=True,
                    comment="执行状态：PENDING/RUNNING/SUCCESS/FAILED/CANCELLED")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    context_json = Column(JSON, nullable=True, comment="运行时上下文（变量键值对）")
    error_message = Column(Text, nullable=True, comment="整体错误信息")
    error_code = Column(String(50), nullable=True, comment="标准化错误代码")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    revision = Column(Integer, nullable=False, default=1, server_default=text("1"), comment="乐观锁版本号")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    def __init__(self, **kwargs):
        """初始化对象状态。"""
        # 乐观锁版本号在创建时即置 1。Column 的 default 仅在 INSERT 时生效，
        # 未 flush 的实例读到的仍是 None；此处让新建实例就能读到 revision=1，
        # 与乐观锁「新建即版本 1」的语义一致。
        kwargs.setdefault("revision", 1)
        super().__init__(**kwargs)


class ActionExecution(Base):
    """业务步骤执行记录。"""

    __tablename__ = "action_execution"
    __table_args__ = {"comment": "业务步骤执行记录"}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    flow_execution_id = Column(Integer, ForeignKey("flow_execution.id", ondelete="CASCADE"), nullable=False, index=True)
    action_id = Column(Integer, ForeignKey("business_action.id", ondelete="SET NULL"), nullable=True, index=True)
    binding_id = Column(Integer, ForeignKey("business_binding.id", ondelete="SET NULL"), nullable=True)
    sequence = Column(Integer, nullable=False, server_default=text("0"), comment="执行序号（从 0 开始）")
    status = Column(String(20), nullable=False, server_default=text("'PENDING'"), index=True,
                    comment="步骤状态：PENDING/RUNNING/SUCCESS/FAILED/SKIPPED")
    request_snapshot = Column(JSON, nullable=True, comment="请求快照（脱敏后）")
    response_snapshot = Column(JSON, nullable=True, comment="响应快照（脱敏后）")
    input_context = Column(JSON, nullable=True, comment="步骤输入上下文")
    output_context = Column(JSON, nullable=True, comment="步骤输出上下文")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True, comment="执行耗时（毫秒）")
    error_message = Column(Text, nullable=True, comment="错误信息")
    error_code = Column(String(50), nullable=True, comment="标准化错误代码")
    unverified_preconditions = Column(JSON, nullable=True, comment="无法自动验证的前置条件列表（BUSINESS/TEXT 类型）")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
