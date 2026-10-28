"""项目知识库 HTTP 契约。

响应只包含用户有权访问的项目元数据与正文片段，不返回服务器文件路径。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


KnowledgeCategory = Literal["REQUIREMENTS", "BUSINESS_PROCESS", "API_SPEC", "FIELD_DICTIONARY", "BUSINESS_RULE"]


class KnowledgeBaseResponse(BaseModel):
    """项目知识库摘要。"""

    id: int
    project_id: int
    name: str
    description: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeDocumentResponse(BaseModel):
    """文档列表行及当前启用版本状态。"""

    id: int
    knowledge_base_id: int
    title: str
    category: KnowledgeCategory
    status: Literal["ACTIVE", "DISABLED", "DELETED"]
    active_version_id: int | None = None
    active_version_number: int | None = None
    latest_version_id: int | None = None
    latest_version_number: int | None = None
    latest_parse_status: str | None = None
    latest_parse_error: str | None = None
    parse_status: str | None = None
    parse_error: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentVersionResponse(BaseModel):
    """文档版本状态；仅返回解析元数据，不暴露存储键。"""

    id: int
    document_id: int
    version_number: int
    file_name: str
    media_type: str
    file_size: int
    sha256: str
    parse_status: str
    parse_error: str | None = None
    is_active: bool = False
    created_at: datetime
    parsed_at: datetime | None = None


class KnowledgeChunkResponse(BaseModel):
    """正文预览及原文定位。"""

    id: int
    document_version_id: int
    ordinal: int
    heading_path: str | None = None
    locator: str
    content: str


class KnowledgeDocumentStatusUpdate(BaseModel):
    """启用或停用文档；已删除文档不可恢复。"""

    enabled: bool


class KnowledgeDocumentListResponse(BaseModel):
    """项目知识库文档列表。"""

    items: list[KnowledgeDocumentResponse]
    total: int


class KnowledgeVersionListResponse(BaseModel):
    """文档版本列表。"""

    items: list[KnowledgeDocumentVersionResponse]


class KnowledgeChunkListResponse(BaseModel):
    """文档版本正文分页。"""

    items: list[KnowledgeChunkResponse]
    total: int
    page: int
    page_size: int


class KnowledgeDocumentUploadFields(BaseModel):
    """上传文档的表单元数据。"""

    title: str = Field(min_length=1, max_length=200)
    category: KnowledgeCategory
    document_id: int | None = Field(default=None, gt=0)
