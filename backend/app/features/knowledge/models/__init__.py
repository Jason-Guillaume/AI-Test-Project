"""项目知识库 ORM 模型集合。

这些 feature-local 表仅由对应 Alembic 迁移建立，不导入 app.models 基线包。
"""

from app.features.knowledge.models.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeParseJob,
)

__all__ = [
    "KnowledgeBase",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeDocumentVersion",
    "KnowledgeParseJob",
]
