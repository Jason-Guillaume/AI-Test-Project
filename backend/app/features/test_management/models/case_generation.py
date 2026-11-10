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
    status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"), index=True)
    test_case_id = Column(Integer, ForeignKey("test_case.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
