"""缺陷来源服务：校验项目权限并原子关联真实执行或疑似问题。"""
import hashlib
import json

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.features.defects.models.source_link import DefectSourceLink
from app.features.defects.schemas import DefectSourceRequest
from app.features.defects.services.defect_service import DefectService
from app.features.security_testing.models.finding import SecurityFinding
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found


class DefectSourceService:
    """缺陷来源的权限、并发去重和事务边界。"""

    def __init__(self):
        """复用缺陷服务的项目可见性和写入权限。"""
        self.defects = DefectService()

    def _source(self, db: Session, source_type: str, source_id: int, user: User, *, lock: bool = False):
        """解析真实来源并校验项目可见性；不存在和越权均返回 404。"""
        model = CaseExecution if source_type == "CASE_EXECUTION" else SecurityFinding
        query = db.query(model).filter(model.id == source_id)
        if lock:
            # 同一来源的重复创建串行化，避免重复请求创建多个缺陷。
            query = query.with_for_update()
        source = query.first()
        if source is None:
            raise not_found("来源不存在")
        run = db.get(TestRun, source.test_run_id) if source_type == "CASE_EXECUTION" else None
        project_id = run.project_id if run is not None else getattr(source, "project_id", None)
        if project_id is None:
            raise not_found("来源不存在")
        project = self.defects._get_project_or_404(db, project_id, user)
        return source, project

    def list_for_source(self, db: Session, source_type: str, source_id: int, user: User):
        """按授权来源列出关联；来源被删除时返回 404。"""
        self._source(db, source_type, source_id, user)
        field = DefectSourceLink.case_execution_id if source_type == "CASE_EXECUTION" else DefectSourceLink.security_finding_id
        return db.query(DefectSourceLink).filter(field == source_id).order_by(DefectSourceLink.id.desc()).all()

    def source_context(self, db: Session, source_type: str, source_id: int, user: User):
        """返回不包含证据的来源定位信息。"""
        source, project = self._source(db, source_type, source_id, user)
        return {"project_id": project.id, "source_type": source_type, "source_id": source_id, "test_run_id": source.test_run_id}

    def list_for_bug(self, db: Session, bug_id: int, user: User):
        """按授权缺陷列出其仍然存在的来源。"""
        self.defects.get_bug_or_404(db, bug_id, user)
        return db.query(DefectSourceLink).filter_by(bug_id=bug_id).order_by(DefectSourceLink.id.desc()).all()

    def link(self, db: Session, body: DefectSourceRequest, actor: User):
        """人工确认后原子创建缺陷和来源，或幂等关联现有缺陷。"""
        source, project = self._source(db, body.source_type, body.source_id, actor, lock=True)
        self.defects._check_writable(db, project, actor)
        if (body.bug_id is None) == (body.bug is None):
            raise bad_request("请选择创建缺陷或关联已有缺陷")
        if body.source_type == "CASE_EXECUTION" and source.status not in {"FAILED", "ERROR"}:
            raise bad_request("只有失败或错误的用例执行可关联缺陷")
        if body.bug is not None and body.bug.project_id != project.id:
            raise not_found("来源不存在")
        request_digest = hashlib.sha256(json.dumps(body.model_dump(exclude={"request_key"}), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing_request = db.query(DefectSourceLink).filter_by(project_id=project.id, request_key=body.request_key).first()
        source_field = "case_execution_id" if body.source_type == "CASE_EXECUTION" else "security_finding_id"
        if existing_request:
            if existing_request.request_digest != request_digest:
                raise conflict("请求标识已用于其他关联")
            return existing_request
        if body.bug_id is not None:
            bug = self.defects.get_bug_or_404(db, body.bug_id, actor)
            if bug.project_id != project.id:
                raise not_found("缺陷不存在")
            existing = db.query(DefectSourceLink).filter_by(bug_id=bug.id, **{source_field: body.source_id}).first()
            if existing:
                return existing
        else:
            # 创建缺陷、通知和关联属于同一事务，失败时不会留下半成品。
            bug = self.defects.create_bug(db, body.bug, actor=actor, commit=False)
        link = DefectSourceLink(project_id=project.id, bug_id=bug.id, created_by=actor.id, request_key=body.request_key, request_digest=request_digest, **{source_field: body.source_id})
        db.add(link)
        try:
            db.commit()
        except IntegrityError:
            # 不同来源同时复用请求标识时，唯一约束负责最终仲裁。
            db.rollback()
            raise conflict("关联或请求标识已存在，请刷新后重试")
        db.refresh(link)
        return link
