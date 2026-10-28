"""项目知识库读写、上传、版本管理与持久化解析作业服务。

所有读写均先验证项目授权。上传内容限制为 2 MiB，存储文件名由服务端生成，
新版本解析成功前不替换上一份可用版本。
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.features.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeParseJob,
)
from app.features.knowledge.parsers.document_parser import parse_document
from app.features.knowledge.schemas import (
    KnowledgeBaseResponse,
    KnowledgeChunkListResponse,
    KnowledgeChunkResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentVersionResponse,
    KnowledgeVersionListResponse,
)
from app.features.business.services._access import get_project_or_404, require_writable_project
from app.models.identity import User
from app.shared.config import settings
from app.shared.errors import bad_request, conflict, not_found


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
PARSER_VERSION = "1"
_ALLOWED_EXTENSIONS = {"md", "markdown", "txt", "docx", "pdf", "json", "yaml", "yml"}
_CATEGORY_NAMES = {
    "REQUIREMENTS", "BUSINESS_PROCESS", "API_SPEC", "FIELD_DICTIONARY", "BUSINESS_RULE",
}
_MEDIA_TYPES = {
    "md": "text/markdown", "markdown": "text/markdown", "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf", "json": "application/json", "yaml": "application/yaml", "yml": "application/yaml",
}


class KnowledgeService:
    """项目知识库服务；实例无状态，可由路由及解析 Worker 复用。"""

    def get_base(self, db: Session, project_id: int, user: User) -> KnowledgeBaseResponse | None:
        """读取当前项目知识库；不存在时返回空，不在 GET 请求中隐式建库。"""
        get_project_or_404(db, project_id, user)
        row = db.query(KnowledgeBase).filter(KnowledgeBase.project_id == project_id).first()
        return KnowledgeBaseResponse.model_validate(row) if row else None

    def create_base(self, db: Session, project_id: int, user: User) -> KnowledgeBaseResponse:
        """为项目创建默认知识库；并发重试时回读已创建的库。"""
        require_writable_project(db, project_id, user)
        existing = db.query(KnowledgeBase).filter(KnowledgeBase.project_id == project_id).first()
        if existing:
            return KnowledgeBaseResponse.model_validate(existing)
        row = KnowledgeBase(project_id=project_id, name="项目知识库", created_by=user.id)
        db.add(row)
        try:
            db.commit()
        except Exception:
            db.rollback()
            existing = db.query(KnowledgeBase).filter(KnowledgeBase.project_id == project_id).first()
            if existing is None:
                raise
            return KnowledgeBaseResponse.model_validate(existing)
        db.refresh(row)
        return KnowledgeBaseResponse.model_validate(row)

    def list_documents(self, db: Session, base_id: int, user: User) -> KnowledgeDocumentListResponse:
        """列出知识库文档，并附上当前可用版本的解析状态。"""
        base = self._base_or_404(db, base_id, user)
        rows = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.knowledge_base_id == base.id,
            KnowledgeDocument.deleted_at.is_(None),
        ).order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id.desc()).all()
        active_ids = [row.active_version_id for row in rows if row.active_version_id]
        versions = {
            row.id: row for row in db.query(KnowledgeDocumentVersion).filter(
                KnowledgeDocumentVersion.id.in_(active_ids or [-1]),
            ).all()
        }
        items = []
        for document in rows:
            version = versions.get(document.active_version_id)
            latest = self._latest_version(db, document.id)
            items.append(KnowledgeDocumentResponse(
                id=document.id,
                knowledge_base_id=document.knowledge_base_id,
                title=document.title,
                category=document.category,
                status=document.status,
                active_version_id=document.active_version_id,
                active_version_number=version.version_number if version else None,
                latest_version_id=latest.id if latest else None,
                latest_version_number=latest.version_number if latest else None,
                latest_parse_status=latest.parse_status if latest else None,
                latest_parse_error=latest.parse_error if latest else None,
                parse_status=version.parse_status if version else self._latest_parse_status(db, document.id),
                parse_error=version.parse_error if version else self._latest_parse_error(db, document.id),
                file_name=version.file_name if version else self._latest_file_name(db, document.id),
                file_size=version.file_size if version else self._latest_file_size(db, document.id),
                created_at=document.created_at,
                updated_at=document.updated_at,
            ))
        return KnowledgeDocumentListResponse(items=items, total=len(items))

    def upload_document(
        self,
        db: Session,
        base_id: int,
        *,
        title: str,
        category: str,
        file_name: str,
        content: bytes,
        user: User,
        document_id: int | None = None,
    ) -> dict[str, Any]:
        """保存文档新版本并登记持久化解析作业，不等待解析完成。"""
        base = self._base_or_404(db, base_id, user, write=True)
        # Serialize project uploads so duplicate-content and duplicate-title checks
        # remain valid even when two members upload at the same time.
        base = db.query(KnowledgeBase).filter(KnowledgeBase.id == base.id).with_for_update().one()
        if not base.enabled:
            raise conflict("项目知识库已停用")
        title = title.strip()
        file_name = self._safe_file_name(file_name)
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if not title:
            raise bad_request("文档名称不能为空")
        if category not in _CATEGORY_NAMES:
            raise bad_request("文档分类不受支持")
        if extension not in _ALLOWED_EXTENSIONS:
            raise bad_request("仅支持 Markdown、TXT、DOCX、文本型 PDF、JSON 和 YAML 文件")
        if not content:
            raise bad_request("文档内容为空")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise bad_request("文档大小不能超过 2 MiB")

        if document_id is None:
            document = db.query(KnowledgeDocument).filter(
                KnowledgeDocument.knowledge_base_id == base.id,
                KnowledgeDocument.title == title,
                KnowledgeDocument.deleted_at.is_(None),
            ).first()
            if document:
                raise conflict("同名文档已存在，请选择该文档新增版本或更改名称")
            document = KnowledgeDocument(
                knowledge_base_id=base.id,
                title=title[:200],
                category=category,
                created_by=user.id,
            )
            db.add(document)
            db.flush()
        else:
            document = db.query(KnowledgeDocument).filter(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.knowledge_base_id == base.id,
                KnowledgeDocument.deleted_at.is_(None),
            ).with_for_update().first()
            if document is None:
                raise not_found("知识文档不存在")
            document.title = title[:200]
            document.category = category
            document.status = "ACTIVE"

        digest = hashlib.sha256(content).hexdigest()
        duplicate = db.query(KnowledgeDocumentVersion).join(
            KnowledgeDocument, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
        ).filter(
            KnowledgeDocument.knowledge_base_id == base.id,
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocumentVersion.sha256 == digest,
        ).first()
        if duplicate:
            db.rollback()
            raise conflict("项目内已存在相同文件内容；请在已有文档中复用，或上传不同版本")

        latest = db.query(KnowledgeDocumentVersion).filter(
            KnowledgeDocumentVersion.document_id == document.id,
        ).order_by(KnowledgeDocumentVersion.version_number.desc()).first()
        version_number = (latest.version_number if latest else 0) + 1
        storage_key = uuid.uuid4().hex
        path = self._storage_path(storage_key)
        temporary = path.with_suffix(".uploading")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(content)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise bad_request("文档保存失败，请检查知识库存储配置") from exc

        version = KnowledgeDocumentVersion(
            document_id=document.id,
            version_number=version_number,
            file_name=file_name,
            media_type=_MEDIA_TYPES[extension],
            file_size=len(content),
            sha256=digest,
            storage_key=storage_key,
            parse_status="PENDING",
            created_by=user.id,
        )
        try:
            db.add(version)
            db.flush()
            job = KnowledgeParseJob(document_version_id=version.id)
            db.add(job)
            db.commit()
        except Exception:
            db.rollback()
            path.unlink(missing_ok=True)
            raise
        db.refresh(version)
        return {
            "document": self._document_summary(db, document),
            "version": KnowledgeDocumentVersionResponse.model_validate(version),
            "parse_job": {"id": job.id, "status": job.status},
        }

    def list_versions(self, db: Session, document_id: int, user: User) -> KnowledgeVersionListResponse:
        """读取文档全部版本及其解析和启用状态。"""
        document = self._document_or_404(db, document_id, user)
        rows = db.query(KnowledgeDocumentVersion).filter(
            KnowledgeDocumentVersion.document_id == document.id,
        ).order_by(KnowledgeDocumentVersion.version_number.desc()).all()
        return KnowledgeVersionListResponse(items=[
            KnowledgeDocumentVersionResponse(
                **KnowledgeDocumentVersionResponse.model_validate(row).model_dump(),
                is_active=row.id == document.active_version_id,
            ) for row in rows
        ])

    def list_chunks(
        self, db: Session, version_id: int, user: User, *, page: int = 1, page_size: int = 50,
    ) -> KnowledgeChunkListResponse:
        """分页读取正文分块，限制单页以避免返回整份大文档。"""
        self._version_or_404(db, version_id, user)
        query = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_version_id == version_id)
        total = int(query.count())
        rows = query.order_by(KnowledgeChunk.ordinal.asc()).offset((page - 1) * page_size).limit(page_size).all()
        return KnowledgeChunkListResponse(
            items=[KnowledgeChunkResponse.model_validate(row) for row in rows],
            total=total, page=page, page_size=page_size,
        )

    def set_document_enabled(self, db: Session, document_id: int, enabled: bool, user: User) -> KnowledgeDocumentResponse:
        """启用或停用项目文档；停用后不可用于新组装任务。"""
        document = self._document_or_404(db, document_id, user, write=True)
        if document.deleted_at is not None:
            raise not_found("知识文档不存在")
        document.status = "ACTIVE" if enabled else "DISABLED"
        db.commit()
        return self._document_summary(db, document)

    def delete_document(self, db: Session, document_id: int, user: User) -> None:
        """撤出检索并清理文件正文；保留版本行供历史草稿审计。"""
        document = self._document_or_404(db, document_id, user, write=True)
        versions = db.query(KnowledgeDocumentVersion).filter(
            KnowledgeDocumentVersion.document_id == document.id,
        ).all()
        paths = [self._storage_path(row.storage_key) for row in versions if row.storage_key]
        document.status = "DELETED"
        document.deleted_at = datetime.now()
        document.active_version_id = None
        for version in versions:
            version.storage_key = None
            version.parse_status = "DELETED"
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_version_id.in_([v.id for v in versions] or [-1])).delete(synchronize_session=False)
        db.query(KnowledgeParseJob).filter(KnowledgeParseJob.document_version_id.in_([v.id for v in versions] or [-1])).delete(synchronize_session=False)
        db.commit()
        for path in paths:
            path.unlink(missing_ok=True)

    def retry_parse(self, db: Session, version_id: int, user: User) -> dict[str, Any]:
        """对失败版本重新排队；版本成功前仍使用旧的 active_version。"""
        version, document = self._version_or_404(db, version_id, user, write=True, with_document=True)
        if document.status == "DELETED" or not version.storage_key:
            raise not_found("文档版本不存在")
        if version.parse_status == "PROCESSING":
            raise conflict("文档正在解析")
        job = db.query(KnowledgeParseJob).filter(
            KnowledgeParseJob.document_version_id == version.id,
        ).with_for_update().first()
        if job is None:
            job = KnowledgeParseJob(document_version_id=version.id)
            db.add(job)
        else:
            job.status = "PENDING"
            job.available_at = datetime.now()
            job.claimed_at = None
            job.error_message = None
        version.parse_status = "PENDING"
        version.parse_error = None
        db.commit()
        return {"version_id": version.id, "status": "PENDING"}

    def process_one_parse_job(self, db: Session) -> bool:
        """领取并解析一个持久化作业；Worker 重启后可恢复超时租约。"""
        now = datetime.now()
        expired_before = now - timedelta(minutes=15)
        job = db.query(KnowledgeParseJob).filter(
            KnowledgeParseJob.available_at <= now,
            or_(
                KnowledgeParseJob.status == "PENDING",
                and_(KnowledgeParseJob.status == "PROCESSING", KnowledgeParseJob.claimed_at < expired_before),
            ),
        ).order_by(KnowledgeParseJob.id.asc()).with_for_update(skip_locked=True).first()
        if job is None:
            db.rollback()
            return False
        version = db.get(KnowledgeDocumentVersion, job.document_version_id)
        document = db.get(KnowledgeDocument, version.document_id) if version else None
        if version is None or document is None or not version.storage_key or document.deleted_at:
            job.status = "FAILED"
            job.error_message = "文档已删除或文件已清理"
            db.commit()
            return True
        job.status = "PROCESSING"
        job.claimed_at = now
        job.attempt_count += 1
        job.error_message = None
        version.parse_status = "PROCESSING"
        version.parse_error = None
        db.commit()
        try:
            content = self._storage_path(version.storage_key).read_bytes()
            parsed = parse_document(version.file_name, content)
            if not parsed or sum(len(item.content.strip()) for item in parsed) == 0:
                raise ValueError("文档未提取到可用正文")
            locked_document = db.query(KnowledgeDocument).filter(
                KnowledgeDocument.id == document.id,
            ).with_for_update().first()
            locked_version = db.get(KnowledgeDocumentVersion, version.id)
            if locked_document is None or locked_version is None or locked_document.deleted_at is not None or not locked_version.storage_key:
                job.status = "FAILED"
                job.claimed_at = None
                job.error_message = "文档已删除或文件已清理"
                if locked_version is not None:
                    locked_version.parse_status = "DELETED"
                    locked_version.parse_error = None
                db.commit()
                return True
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_version_id == version.id).delete(synchronize_session=False)
            db.add_all([
                KnowledgeChunk(
                    document_version_id=version.id,
                    ordinal=item.ordinal,
                    heading_path=item.heading_path,
                    locator=item.locator,
                    content=item.content,
                    search_text=item.content.casefold(),
                ) for item in parsed
            ])
            latest_version_id = db.query(KnowledgeDocumentVersion.id).filter(
                KnowledgeDocumentVersion.document_id == locked_document.id,
            ).order_by(KnowledgeDocumentVersion.version_number.desc()).limit(1).scalar()
            if latest_version_id == locked_version.id:
                locked_document.active_version_id = locked_version.id
            version.parse_status = "READY"
            version.parse_error = None
            version.parser_version = PARSER_VERSION
            version.parsed_at = datetime.now()
            job.status = "SUCCEEDED"
            job.claimed_at = None
            job.error_message = None
            db.commit()
        except Exception as exc:  # noqa: BLE001 — 解析细节不向 API 回传本地路径或堆栈。
            db.rollback()
            failed_job = db.get(KnowledgeParseJob, job.id)
            failed_version = db.get(KnowledgeDocumentVersion, job.document_version_id)
            if failed_job is not None:
                failed_job.status = "FAILED"
                failed_job.claimed_at = None
                failed_job.error_message = self._safe_error(exc)
            if failed_version is not None:
                failed_document = db.get(KnowledgeDocument, failed_version.document_id)
                if failed_version.storage_key and failed_document is not None and failed_document.deleted_at is None:
                    failed_version.parse_status = "FAILED"
                    failed_version.parse_error = self._safe_error(exc)
            db.commit()
        return True

    @staticmethod
    def load_assembly_chunks(
        db: Session, version_ids: list[int], *, require_active_version: bool = True,
    ) -> list[dict[str, Any]]:
        """读取固定版本正文；正式校验默认要求当前活动版本，生成阶段沿用任务快照。"""
        query = db.query(KnowledgeChunk, KnowledgeDocumentVersion, KnowledgeDocument).join(
            KnowledgeDocumentVersion, KnowledgeChunk.document_version_id == KnowledgeDocumentVersion.id,
        ).join(KnowledgeDocument, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id).join(
            KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id,
        ).filter(
            KnowledgeDocumentVersion.id.in_(version_ids),
            KnowledgeDocumentVersion.parse_status == "READY",
            KnowledgeDocument.status == "ACTIVE",
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeBase.enabled.is_(True),
        )
        if require_active_version:
            query = query.filter(KnowledgeDocument.active_version_id == KnowledgeDocumentVersion.id)
        rows = query.order_by(KnowledgeDocumentVersion.id.asc(), KnowledgeChunk.ordinal.asc()).all()
        return [{
            "chunk_id": chunk.id,
            "document_version_id": version.id,
            "document_title": document.title,
            "heading_path": chunk.heading_path,
            "locator": chunk.locator,
            "content": chunk.content,
        } for chunk, version, document in rows]

    @staticmethod
    def _storage_path(storage_key: str | None) -> Path:
        """将数据库随机键解析到知识库专用目录，不接受路径片段。"""
        if not storage_key or not re.fullmatch(r"[a-f0-9]{32}", storage_key):
            raise FileNotFoundError("存储文件引用无效")
        configured = getattr(settings, "KNOWLEDGE_STORAGE_DIR", None)
        root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[4] / ".data" / "knowledge"
        return root.resolve() / storage_key[:2] / storage_key

    @staticmethod
    def _safe_file_name(value: str) -> str:
        """去除路径段和控制字符，避免客户端文件名进入存储路径。"""
        value = (value or "document").replace("\\", "/").split("/")[-1]
        value = re.sub(r"[\x00-\x1f\x7f]", "", value).strip(" .")
        return value[:255] or "document.txt"

    @staticmethod
    def _safe_error(error: Exception) -> str:
        """将解析器异常压缩为不含路径与堆栈的可读错误。"""
        message = str(error).splitlines()[0][:900]
        return message or f"文档解析失败：{type(error).__name__}"

    def _base_or_404(self, db: Session, base_id: int, user: User, *, write: bool = False) -> KnowledgeBase:
        """取知识库并复核其所属项目权限。"""
        base = db.get(KnowledgeBase, base_id)
        if base is None:
            raise not_found("项目知识库不存在")
        if write:
            require_writable_project(db, base.project_id, user)
        else:
            get_project_or_404(db, base.project_id, user)
        return base

    def _document_or_404(self, db: Session, document_id: int, user: User, *, write: bool = False) -> KnowledgeDocument:
        """取文档并按项目授权过滤。"""
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            raise not_found("知识文档不存在")
        self._base_or_404(db, document.knowledge_base_id, user, write=write)
        if document.deleted_at is not None:
            raise not_found("知识文档不存在")
        return document

    def _version_or_404(
        self, db: Session, version_id: int, user: User, *, write: bool = False,
        with_document: bool = False,
    ):
        """取版本并复核所属项目权限。"""
        row = db.query(KnowledgeDocumentVersion, KnowledgeDocument).join(
            KnowledgeDocument, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
        ).filter(KnowledgeDocumentVersion.id == version_id).first()
        if row is None:
            raise not_found("文档版本不存在")
        version, document = row
        self._base_or_404(db, document.knowledge_base_id, user, write=write)
        if document.deleted_at is not None:
            raise not_found("文档版本不存在")
        return (version, document) if with_document else version

    def _document_summary(self, db: Session, document: KnowledgeDocument) -> KnowledgeDocumentResponse:
        """将文档和当前版本状态组装成稳定列表响应。"""
        version = db.get(KnowledgeDocumentVersion, document.active_version_id) if document.active_version_id else None
        latest = self._latest_version(db, document.id)
        return KnowledgeDocumentResponse(
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            title=document.title,
            category=document.category,
            status=document.status,
            active_version_id=document.active_version_id,
            active_version_number=version.version_number if version else None,
            latest_version_id=latest.id if latest else None,
            latest_version_number=latest.version_number if latest else None,
            latest_parse_status=latest.parse_status if latest else None,
            latest_parse_error=latest.parse_error if latest else None,
            parse_status=version.parse_status if version else self._latest_parse_status(db, document.id),
            parse_error=version.parse_error if version else self._latest_parse_error(db, document.id),
            file_name=version.file_name if version else self._latest_file_name(db, document.id),
            file_size=version.file_size if version else self._latest_file_size(db, document.id),
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    @staticmethod
    def _latest_version(db: Session, document_id: int) -> KnowledgeDocumentVersion | None:
        """读取最新版本，用于尚无可用版本时显示解析进度。"""
        return db.query(KnowledgeDocumentVersion).filter(
            KnowledgeDocumentVersion.document_id == document_id,
        ).order_by(KnowledgeDocumentVersion.version_number.desc()).first()

    def _latest_parse_status(self, db: Session, document_id: int) -> str | None:
        row = self._latest_version(db, document_id)
        return row.parse_status if row else None

    def _latest_parse_error(self, db: Session, document_id: int) -> str | None:
        row = self._latest_version(db, document_id)
        return row.parse_error if row else None

    def _latest_file_name(self, db: Session, document_id: int) -> str | None:
        row = self._latest_version(db, document_id)
        return row.file_name if row else None

    def _latest_file_size(self, db: Session, document_id: int) -> int | None:
        row = self._latest_version(db, document_id)
        return row.file_size if row else None
