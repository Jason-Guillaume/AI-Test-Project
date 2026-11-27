"""缺陷项目模板：字段显隐、默认值与分阶段必填规则，按版本发布。"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class DefectTemplate(Base):
    """模板版本行；同一项目至多一个 published 版本，由服务层保证。"""

    __tablename__ = "defect_template"
    __table_args__ = (
        Index("uq_defect_template_project_version", "project_id", "version", unique=True),
        {"comment": "缺陷项目模板：字段显隐、默认值与分阶段必填规则"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    version = Column(Integer, nullable=False)
    config = Column(JSON, nullable=False, comment="字段显隐/默认值/优先级/分阶段必填；不含人员指派")
    status = Column(
        String(20), nullable=False, default="draft", server_default=text("'draft'"),
        comment="draft / published / retired",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    published_at = Column(DateTime, nullable=True)