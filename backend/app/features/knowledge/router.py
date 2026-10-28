"""项目知识库 API 路由。

读请求要求项目可见，上传、状态变更和删除要求项目 member+；
跨项目资源统一由服务层按不存在处理。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.features.knowledge.schemas import (
    KnowledgeBaseResponse,
    KnowledgeChunkListResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentStatusUpdate,
    KnowledgeVersionListResponse,
)
from app.features.knowledge.services.knowledge_service import KnowledgeService, MAX_DOCUMENT_BYTES
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db

router = APIRouter(tags=["项目知识库"])
service = KnowledgeService()


@router.get("/projects/{project_id}/knowledge-bases", response_model=list[KnowledgeBaseResponse], summary="列出项目知识库")
def list_knowledge_bases(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[KnowledgeBaseResponse]:
    """读取项目知识库；尚未创建时返回空列表。"""
    base = service.get_base(db, project_id, user)
    return [base] if base else []


@router.post("/projects/{project_id}/knowledge-bases", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED, summary="创建项目知识库")
def create_knowledge_base(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KnowledgeBaseResponse:
    """为当前项目创建默认知识库。"""
    return service.create_base(db, project_id, user)


@router.get("/knowledge-bases/{base_id}/documents", response_model=KnowledgeDocumentListResponse, summary="列出项目知识文档")
def list_documents(
    base_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KnowledgeDocumentListResponse:
    """列出文档版本、解析状态与失败原因。"""
    return service.list_documents(db, base_id, user)


@router.post("/knowledge-bases/{base_id}/documents", status_code=status.HTTP_202_ACCEPTED, summary="上传知识文档")
async def upload_document(
    base_id: int,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=200),
    category: str = Form(..., max_length=32),
    document_id: int | None = Form(None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """限 2 MiB 接收文件，保存后立即返回待解析版本。"""
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        from app.shared.errors import bad_request

        raise bad_request("文档大小不能超过 2 MiB")
    return service.upload_document(
        db,
        base_id,
        title=title,
        category=category,
        file_name=file.filename or "document.txt",
        content=content,
        document_id=document_id,
        user=user,
    )


@router.get("/knowledge-documents/{document_id}/versions", response_model=KnowledgeVersionListResponse, summary="列出文档版本")
def list_versions(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KnowledgeVersionListResponse:
    """读取版本历史与解析状态。"""
    return service.list_versions(db, document_id, user)


@router.get("/knowledge-document-versions/{version_id}/chunks", response_model=KnowledgeChunkListResponse, summary="预览知识文档正文")
def list_chunks(
    version_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> KnowledgeChunkListResponse:
    """分页读取正文块及来源定位。"""
    return service.list_chunks(db, version_id, user, page=page, page_size=page_size)


@router.patch("/knowledge-documents/{document_id}/status", summary="启用或停用知识文档")
def set_document_enabled(
    document_id: int,
    body: KnowledgeDocumentStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """停用文档后禁止将其用于新的业务组装。"""
    return service.set_document_enabled(db, document_id, body.enabled, user).model_dump(mode="json")


@router.post("/knowledge-document-versions/{version_id}/retry", status_code=status.HTTP_202_ACCEPTED, summary="重试知识文档解析")
def retry_parse(
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """将失败版本重新放入持久化解析队列。"""
    return service.retry_parse(db, version_id, user)


@router.delete("/knowledge-documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除项目知识文档")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """撤出检索并清理原文件及正文块，保留审计版本元数据。"""
    service.delete_document(db, document_id, user)
