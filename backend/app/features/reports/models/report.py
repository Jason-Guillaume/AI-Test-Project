"""正式测试报告 ORM 模型（TestReport）。

一张 TestReport 对应一次 TestRun（Phase 2 第一阶段约定）。报告**只保存汇总 / AI 总结 /
风险 / 元数据**，不复制 CaseExecution / Request / Response / Assertion 明细——明细仍以
现有执行记录为事实来源，报告详情页实时读取 TestRun + CaseExecution + Assertions。

字段口径（对齐 Phase 2 规约 §三）：
- status ∈ {GENERATING, COMPLETED, FAILED}：GENERATING 为中间态，COMPLETED 表示统计完成，
  FAILED 表示生成过程异常（不影响 TestRun 自身状态，见 §二十八「三者状态独立」）。
- risk_level ∈ {LOW, MEDIUM, HIGH, CRITICAL}：由代码 + 规则决定（§八），AI 仅提供解释。
- report_no：稳定编号 RPT-YYYYMMDD-NNNNNN，由 ReportService 生成。
- summary：代码统计的结构化汇总（失败分类、耗时分布等），不可变。
- ai_summary：LLM 结构化总结（§九），允许重生成，配合 ai_summary_version 追溯。

统计字段（total/passed/failed/error/skipped_cases、pass_rate、duration_ms）一律由
ReportBuilder 代码计算，LLM 不参与（§五「不要让 LLM 自己计算」）。

feature-local 表，由迁移 0008 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestReport(Base):
    """正式测试报告：一次 TestRun 的汇总结论 + AI 总结 + 风险等级。"""

    __tablename__ = "test_report"
    __table_args__ = (
        Index("ix_test_report_project_created", "project_id", "created_at"),
        Index("ix_test_report_run", "test_run_id"),
        {"comment": "正式测试报告：汇总 + AI 总结 + 风险（不复制执行明细）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    test_run_id = Column(
        # 删除 TestRun 不连带删报告：报告引用置空，报告记录保留（§十一「删除只删报告记录」）。
        Integer,
        ForeignKey("test_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联测试执行ID（一报告一执行）",
    )
    report_no = Column(String(32), nullable=False, unique=True, comment="报告编号 RPT-YYYYMMDD-NNNNNN")
    title = Column(String(200), nullable=False, comment="报告标题")
    environment_id = Column(
        # 冗余环境ID便于列表无需 join 即可筛选（§十二筛选条件含 Environment）。
        Integer,
        ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="执行环境ID（冗余，便于列表筛选）",
    )
    status = Column(
        String(20), nullable=False, default="GENERATING", server_default=text("'GENERATING'"),
        index=True, comment="报告状态：GENERATING/COMPLETED/FAILED",
    )
    total_cases = Column(Integer, nullable=False, server_default=text("0"), comment="用例总数")
    passed_cases = Column(Integer, nullable=False, server_default=text("0"), comment="通过数")
    failed_cases = Column(Integer, nullable=False, server_default=text("0"), comment="失败数")
    error_cases = Column(Integer, nullable=False, server_default=text("0"), comment="错误数")
    skipped_cases = Column(Integer, nullable=False, server_default=text("0"), comment="跳过数")
    pass_rate = Column(
        # 通过率：passed / (total - skipped) * 100，分母为 0 时记 0（§六）。
        Numeric(5, 2), nullable=False, server_default=text("0"), comment="通过率（0-100，保留两位）",
    )
    duration_ms = Column(Integer, nullable=True, comment="总耗时（毫秒，由 CaseExecution 累加）")
    summary = Column(JSON, nullable=True, comment="代码统计的结构化汇总（失败分类等，不可变）")
    ai_summary = Column(JSON, nullable=True, comment="LLM 结构化总结（可重生成）")
    ai_summary_version = Column(String(20), nullable=True, comment="AI 总结版本号，如 summary-v1")
    risk_level = Column(
        String(20), nullable=False, default="LOW", server_default=text("'LOW'"),
        index=True, comment="风险等级：LOW/MEDIUM/HIGH/CRITICAL",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="生成人ID")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
