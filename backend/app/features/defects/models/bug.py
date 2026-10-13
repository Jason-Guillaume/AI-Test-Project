"""缺陷（Bug）ORM 模型。

沿用旧项目的表名、字段与约束语义：
- 表名 ``bug`` 与旧项目一致
- 状态取值：``待确认 / 处理中 / 已修复 / 已关闭 / 已拒绝``，由服务层校验
- 严重度 1-4，1 为最低、4 为最高
- 与旧项目差异：去除 ``testcase_id`` 字段，因新平台 Phase-1 尚未接入测试用例与
  回归关联（DefectRegressionLink / CaseGenerationRun 属后续阶段）
- reporter_id / assignee_id 使用 SET NULL 外键：用户被删除时保留缺陷行，
  前端展示时按 username is None 回退到「未知用户」
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func, text

from app.shared.database import Base


class Bug(Base):
    """测试缺陷及其处理状态。"""

    __tablename__ = "bug"
    __table_args__ = (
        Index("ix_bug_project_status_severity", "project_id", "status", "severity"),
        Index("ix_bug_project_created", "project_id", "created_at"),
        {"comment": "测试缺陷及其处理状态"},
    )
    # (project_id, status, severity) 复合索引服务于列表页按状态与严重度过滤：
    # 先按项目分组，再按状态与严重度收敛，避免全表扫描。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False,
        index=True, comment="所属项目ID",
    )
    # project_id 带 ondelete="CASCADE"：项目被删除时缺陷一并清理，不留下孤儿行。
    title = Column(String(200), nullable=False, index=True, comment="缺陷标题")
    description = Column(String(1000), nullable=True, comment="缺陷描述")
    severity = Column(
        Integer, nullable=False, default=2, server_default=text("2"),
        comment="严重度 1-4，1 低 2 中 3 高 4 严重",
    )
    # severity 不做数据库 CHECK 约束：合法性完全由服务层保证（1<=x<=4），
    # 保持与旧项目一致的灵活性，也避免枚举值变更时需要走 migration。
    status = Column(
        String(20), nullable=False, default="待确认", server_default=text("'待确认'"),
        index=True, comment="状态：待确认/处理中/已修复/已关闭/已拒绝",
    )
    steps_to_reproduce = Column(Text, nullable=True, comment="复现步骤")
    environment = Column(String(200), nullable=True, comment="发现环境")
    reporter_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        index=True, comment="报告人ID",
    )
    assignee_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        index=True, comment="处理人ID",
    )
    # reporter_id / assignee_id 用 SET NULL：用户被删除时保留缺陷行，
    # 前端渲染按 username is None 回退到「未知用户」，不让缺陷数据因人员变动丢失。
    created_at = Column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间",
    )
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
