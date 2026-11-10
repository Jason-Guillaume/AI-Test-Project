"""用例生成批次与草稿。

草稿不是正式用例。只有人工接受后才写入 TestCase，并记下主/子 Agent 版本、模型和 Skill 版本。
本表不替代 AgentSession：现有会话服务的是执行工作流，存不下这批待审核草稿。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class CaseGenerationBatch(Base):
    """一次 Super Agent 生成。单模块失败时批次仍保留其他模块的草稿。"""

    __tablename__ = "case_generation_batch"
    __table_args__ = ({"comment": "用例生成批次：待人工审核，不自动执行"},)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    direction = Column(String(10), nullable=False, comment="API/UI/AI")
    scope_node_id = Column(Integer, ForeignKey("test_scope_node.id", ondelete="SET NULL"), nullable=True)
    supervisor_agent_id = Column(Integer, ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True)
    supervisor_version = Column(Integer, nullable=False)
    supervisor_name = Column(String(120), nullable=False)
    model_config_id = Column(Integer, nullable=True)
    model_name = Column(String(200), nullable=True)
    requirements = Column(Text, nullable=False)
    modules_json = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, comment="COMPLETED/PARTIAL_FAILED/FAILED")
    review_summary = Column(Text, nullable=True)
    review_gaps_json = Column(JSON, nullable=False, default=list)
    module_errors_json = Column(JSON, nullable=False, default=list)
    # 各模块生成耗时与 token 指标；只存数值，不含提示词、响应或密钥。
    module_metrics_json = Column(JSON, nullable=False, default=list)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class CaseDraft(Base):
    """一条待审核草稿。接受后写入 test_case_id；拒绝后不产生用例。"""

    __tablename__ = "case_draft"
    __table_args__ = ({"comment": "用例生成草稿，接受前不是正式用例"},)

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("case_generation_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    module = Column(String(20), nullable=False)
    child_agent_id = Column(Integer, ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True)
    child_version = Column(Integer, nullable=False, server_default=text("1"))
    child_name = Column(String(120), nullable=False, server_default=text("''"))
    model_config_id = Column(Integer, nullable=True)
    model_name = Column(String(200), nullable=True)
    skill_versions_json = Column(JSON, nullable=False, default=list)
    title = Column(String(200), nullable=False)
    priority = Column(String(10), nullable=False)
    payload_json = Column(JSON, nullable=False)
    # 原始 AI 生成内容，人工编辑只改 payload_json，本字段不变。
    original_payload_json = Column(JSON, nullable=False)
    # 系统规则校验结果：[{rule, level, message, ...}]；只提示，不阻断审核。
    quality_json = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"), index=True)
    review_comment = Column(String(500), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="SET NULL"), nullable=True)
    import_error = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class CaseGenerationAudit(Base):
    """审核、编辑、入库与再生成操作的审计行。"""

    __tablename__ = "case_generation_audit"
    __table_args__ = ({"comment": "用例生成审核与入库操作审计"},)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("case_generation_batch.id", ondelete="CASCADE"), nullable=False, index=True)
    # 空表示批次级操作（批量审核、再生成）。
    draft_id = Column(Integer, ForeignKey("case_draft.id", ondelete="CASCADE"), nullable=True, index=True)
    action = Column(String(30), nullable=False, comment="CREATE/EDIT/APPROVE/REJECT/REOPEN/BATCH_REVIEW/REGENERATE")
    actor_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    detail_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
