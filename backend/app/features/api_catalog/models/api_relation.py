"""接口关联（API Relation）ORM 模型。

第一阶段人工维护接口间关联；后续 Agent 自动分析。
关系类型 relation_type ∈ {PRECONDITION, OUTPUT_INPUT, FOLLOW_UP}：
- PRECONDITION：source 接口是 target 的前置条件
- OUTPUT_INPUT：source 的输出（variable_name，经 extract_path 提取）作为 target 的输入
- FOLLOW_UP：target 是 source 的后续步骤

唯一约束 (source_api_id, target_api_id, relation_type, variable_name) 防重复关联。
feature-local 表，由迁移 0003 显式建立。
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.shared.database import Base


class ApiRelation(Base):
    """接口关联（PRECONDITION/OUTPUT_INPUT/FOLLOW_UP）。"""

    __tablename__ = "api_relation"
    __table_args__ = (
        UniqueConstraint(
            "source_api_id",
            "target_api_id",
            "relation_type",
            "variable_name",
            name="uq_api_relation_src_tgt_type_var",
        ),
        Index("ix_api_relation_project", "project_id"),
        Index("ix_api_relation_source", "source_api_id"),
        {"comment": "接口关联（PRECONDITION/OUTPUT_INPUT/FOLLOW_UP）"},
    )
    # 唯一约束防重复关联；source/target/索引服务于按源或目标接口反查关联。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目ID（冗余，便于按项目筛选关联）",
    )
    # project_id 冗余存储：关联天然属于某项目，按项目列关联时无需先联接口表。
    source_api_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="CASCADE"),
        nullable=False,
        comment="源接口ID",
    )
    target_api_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="CASCADE"),
        nullable=False,
        comment="目标接口ID",
    )
    relation_type = Column(
        String(20), nullable=False, comment="关系类型：PRECONDITION/OUTPUT_INPUT/FOLLOW_UP"
    )
    variable_name = Column(
        String(100), nullable=True, comment="变量名（OUTPUT_INPUT 时表示提取出的变量）"
    )
    extract_path = Column(
        String(500), nullable=True, comment="从 source 响应提取变量的路径，如 body.data.token"
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
