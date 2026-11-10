"""把 Super Agent 的未落库草稿收成批次，并在人工接受后写入正式用例。

不修改 case_generation 的工具契约。方向只决定调用哪些已授权模块：
API→api，UI→web，AI→ai 与 asr，security 仅在用户勾选且主 Agent 已绑定时加入。
单模块失败只记在批次错误里，已成功的草稿仍可审核。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Text, cast, func
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition
from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.identity import User
from app.core.notifications.notify import notify
from app.features.test_management.models.case_generation import CaseDraft, CaseGenerationAudit, CaseGenerationBatch
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_case_precondition import TestCasePrecondition
from app.features.test_management.models.test_scope import TestCaseScope
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.schemas.generation import (
    BatchReviewItem,
    BatchReviewRequest,
    BatchReviewResponse,
    CaseDraftResponse,
    CaseGenerationAuditResponse,
    DraftDecisionResponse,
    DraftRejectRequest,
    DraftUpdateRequest,
    GenerationAgentOption,
    GenerationBatchListItem,
    GenerationBatchListResponse,
    GenerationBatchResponse,
    GenerationStartRequest,
    GenerationTrace,
    RegenerateRequest,
)
from app.features.test_management.scope_placement import DIRECTIONS
from app.features.test_management.services.generation_quality import BOUNDARY_WORDS, check_draft
from app.features.test_management.services.scope_service import ScopeService
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.skills.models import SkillDefinition
from app.tools.builtin.case_generation.contracts import DesignCase, GenerationRequest

_DIRECTION_MODULES = {"API": ("api",), "UI": ("web",), "AI": ("ai", "asr")}
_TARGET_BY_DIRECTION = {"API": "API", "UI": "WEB", "AI": "AI"}
_CASE_TYPE_WORDS = (
    ("SECURITY", ("安全", "越权")),
    ("PERMISSION", ("权限", "鉴权")),
    ("BOUNDARY", ("边界",)),
    ("NEGATIVE", ("负向", "负面")),
    ("EXCEPTION", ("异常",)),
    ("BUSINESS", ("业务",)),
    ("FUNCTIONAL", ("功能",)),
)


def modules_for(direction: str, include_security: bool, available: set[str]) -> tuple[list[str], list[dict]]:
    """按方向选出要调用的生成模块。安全模块没绑定时跳过，不让整次生成失败。"""
    if direction not in _DIRECTION_MODULES:
        raise bad_request("测试方向取值非法")
    required = [item for item in _DIRECTION_MODULES[direction] if item in available]
    missing = [item for item in _DIRECTION_MODULES[direction] if item not in available]
    if not required:
        raise bad_request("主 Agent 没有绑定该测试方向需要的子 Agent")
    notes = [{"module": item, "status": "SKIPPED", "error": "主 Agent 未绑定该方向的子 Agent，已跳过"} for item in missing]
    if include_security:
        if "security" in available:
            required.append("security")
        else:
            notes.append({"module": "security", "status": "SKIPPED", "error": "主 Agent 未绑定安全子 Agent，已跳过"})
    return required, notes


class GenerationService:
    """生成批次与草稿审核。写方法在本服务内提交。"""

    def list_agents(self, db: Session, project_id: int, user: User) -> list[GenerationAgentOption]:
        """列出启用的用例生成主 Agent。不返回指令、Skill 正文或工具参数。"""
        get_project_or_404(db, project_id, user)
        rows = db.query(AgentDefinition).filter(
            AgentDefinition.is_enabled.is_(True),
            AgentDefinition.workflow_template == "case_generation",
        ).all()
        children = {row.id: row for row in db.query(AgentDefinition).all()}
        options = []
        for row in rows:
            if not row.child_agent_ids:
                continue
            modules = []
            for child_id in row.child_agent_ids:
                child = children.get(child_id)
                if child is None:
                    continue
                for key in child.tool_keys or []:
                    prefix = "case_generation.generate_"
                    if key.startswith(prefix):
                        modules.append(key[len(prefix):])
            if modules:
                options.append(GenerationAgentOption(id=row.id, name=row.name, version=row.version, modules=modules))
        return options

    def start(
        self, db: Session, project_id: int, body: GenerationStartRequest, *, actor: User, provider_factory=None,
    ) -> GenerationBatchResponse:
        """调用现有主子 Agent 链路，并把返回的草稿落库。调用失败时不写批次。"""
        require_writable_project(db, project_id, actor)
        if body.direction not in DIRECTIONS:
            raise bad_request("测试方向取值非法")
        scope_node_id = body.scope_node_id
        if scope_node_id is not None:
            node = ScopeService()._node_in_project(db, scope_node_id, project_id)
            if node.direction != body.direction:
                raise bad_request("所选范围不属于该测试方向")
        supervisor = db.get(AgentDefinition, body.agent_id)
        if supervisor is None or not supervisor.is_enabled:
            raise not_found("主 Agent 不存在")
        available = self._available_modules(db, supervisor)
        modules, notes = modules_for(body.direction, body.include_security, available)
        from app.agents.services.case_generation_service import generate_case_suite
        suite = generate_case_suite(
            db, actor, body.agent_id,
            GenerationRequest(
                project_id=project_id,
                requirements=body.requirements,
                modules=modules,
                cases_per_module=body.cases_per_module,
                model_config_id=body.model_config_id,
            ),
            provider_factory=provider_factory,
        )
        return self.persist(
            db, actor, project_id=project_id, direction=body.direction, scope_node_id=scope_node_id,
            requirements=body.requirements, suite=suite, extra_notes=notes,
        )

    def persist(
        self, db: Session, actor: User, *, project_id: int, direction: str, scope_node_id: int | None,
        requirements: str, suite: dict, extra_notes: list[dict] | None = None,
    ) -> GenerationBatchResponse:
        """把一次生成结果写成批次和草稿。失败模块不产生草稿。"""
        supervisor = suite.get("supervisor") or {}
        errors = list(extra_notes or [])
        batch = CaseGenerationBatch(
            project_id=project_id,
            direction=direction,
            scope_node_id=scope_node_id,
            supervisor_agent_id=supervisor.get("id"),
            supervisor_version=int(supervisor.get("version") or 1),
            supervisor_name=str(supervisor.get("name") or "主 Agent"),
            model_config_id=supervisor.get("model_config_id"),
            model_name=supervisor.get("model_name"),
            requirements=requirements,
            modules_json=[item.get("module") for item in suite.get("modules") or []],
            status=str(suite.get("status") or "FAILED"),
            review_summary=(suite.get("review") or {}).get("summary"),
            review_gaps_json=list((suite.get("review") or {}).get("gaps") or []),
            module_errors_json=[],
            created_by=actor.id,
        )
        db.add(batch)
        db.flush()
        for module in suite.get("modules") or []:
            if module.get("status") != "SUCCEEDED":
                errors.append({
                    "module": module.get("module"),
                    "status": module.get("status") or "FAILED",
                    "error": module.get("error") or "模块用例生成失败",
                })
                continue
            skills = self._skill_versions(db, module.get("id"))
            for raw in module.get("cases") or []:
                try:
                    case = DesignCase.model_validate(raw)
                except Exception:
                    errors.append({"module": module.get("module"), "status": "FAILED", "error": "草稿结构无效，已跳过"})
                    continue
                db.add(CaseDraft(
                    batch_id=batch.id,
                    module=str(module.get("module") or ""),
                    child_agent_id=module.get("id"),
                    child_version=int(module.get("version") or 1),
                    child_name=str(module.get("name") or ""),
                    model_config_id=module.get("model_config_id"),
                    model_name=module.get("model_name"),
                    skill_versions_json=skills,
                    title=case.title[:200],
                    priority=case.priority,
                    payload_json=case.model_dump(),
                    original_payload_json=case.model_dump(),
                    status="PENDING",
                ))
        batch.module_errors_json = errors
        batch.module_metrics_json = self._metrics(suite)
        # SessionLocal autoflush=False，先落盘再按库内全量草稿重算质量。
        db.flush()
        self._refresh_quality(db, batch)
        self._audit(db, batch, None, "CREATE", actor, {"direction": direction, "modules": list(batch.modules_json or [])})
        db.commit()
        db.refresh(batch)
        return self._batch_response(db, batch)

    def get_batch(self, db: Session, batch_id: int, user: User) -> GenerationBatchResponse:
        """读取批次和其中的草稿。"""
        batch = self._visible_batch(db, batch_id, user)
        return self._batch_response(db, batch)

    def update_draft(self, db: Session, draft_id: int, body: DraftUpdateRequest, *, actor: User) -> CaseDraftResponse:
        """修改待审核草稿。已接受或已拒绝的草稿不能再改。"""
        draft = self._writable_draft(db, draft_id, actor)
        if draft.status != "PENDING":
            raise bad_request("只有待审核草稿可以修改")
        data = body.model_dump(exclude_unset=True)
        payload = dict(draft.payload_json or {})
        if "title" in data and data["title"]:
            draft.title = data["title"].strip()
            payload["title"] = draft.title
        if "priority" in data and data["priority"]:
            draft.priority = data["priority"]
            payload["priority"] = draft.priority
        for key in ("requirement", "preconditions", "test_data", "steps", "expected_results"):
            if key in data and data[key] is not None:
                payload[key] = data[key]
        draft.payload_json = payload
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        draft.quality_json = self._quality_for(db, batch, draft)
        self._audit(db, batch, draft, "EDIT", actor, {"fields": sorted(data.keys())})
        db.commit()
        db.refresh(draft)
        return self._draft_response(draft)

    def accept_draft(self, db: Session, draft_id: int, *, actor: User) -> DraftDecisionResponse:
        """接受草稿并写入正式用例。重复接受返回原用例，不会再造一条。"""
        draft = self._writable_draft(db, draft_id, actor, lock=True)
        if draft.status == "ACCEPTED" and draft.test_case_id:
            return DraftDecisionResponse(draft_id=draft.id, status=draft.status, test_case_id=draft.test_case_id, source_type="AI")
        if draft.status != "PENDING":
            raise bad_request("该草稿已审核，不能入库")
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        if batch is None:
            raise not_found("生成批次不存在")
        case = self._import_draft(db, batch, draft, actor)
        draft.status = "ACCEPTED"
        draft.test_case_id = case.id
        draft.import_error = None
        draft.reviewed_by = actor.id
        draft.reviewed_at = datetime.now()
        self._audit(db, batch, draft, "APPROVE", actor, {"test_case_id": case.id})
        notify(
            db, user_id=actor.id, event_type="test.case.created",
            title=f"你已接受生成用例「{case.name}」", project_id=batch.project_id,
            actor_id=actor.id, actor_username=actor.username, detail={"case_id": case.id, "draft_id": draft.id},
        )
        db.commit()
        return DraftDecisionResponse(draft_id=draft.id, status="ACCEPTED", test_case_id=case.id, source_type="AI")

    def reject_draft(self, db: Session, draft_id: int, body: DraftRejectRequest | None = None, *, actor: User) -> DraftDecisionResponse:
        """拒绝草稿。不创建用例；可通过恢复接口回到待审核。"""
        draft = self._writable_draft(db, draft_id, actor)
        if draft.status != "PENDING":
            raise bad_request("该草稿已审核")
        comment = (body.comment if body else None) or None
        draft.status = "REJECTED"
        draft.review_comment = comment
        draft.reviewed_by = actor.id
        draft.reviewed_at = datetime.now()
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        self._audit(db, batch, draft, "REJECT", actor, {"comment": comment})
        db.commit()
        return DraftDecisionResponse(draft_id=draft.id, status="REJECTED", test_case_id=None, source_type=None)

    def reopen_draft(self, db: Session, draft_id: int, *, actor: User) -> CaseDraftResponse:
        """把已拒绝的草稿恢复为待审核。已入库（接受）的草稿不能回退。"""
        draft = self._writable_draft(db, draft_id, actor)
        if draft.status == "ACCEPTED":
            raise bad_request("已入库的草稿不能恢复，请在用例库中处理正式用例")
        if draft.status != "REJECTED":
            raise bad_request("只有已拒绝的草稿可以恢复")
        draft.status = "PENDING"
        draft.review_comment = None
        draft.reviewed_by = None
        draft.reviewed_at = None
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        draft.quality_json = self._quality_for(db, batch, draft)
        self._audit(db, batch, draft, "REOPEN", actor, {})
        db.commit()
        db.refresh(draft)
        return self._draft_response(draft)

    def list_batches(
        self, db: Session, project_id: int, user: User, *,
        page: int = 1, page_size: int = 20, direction: str | None = None,
        status: str | None = None, module: str | None = None, keyword: str | None = None,
    ) -> GenerationBatchListResponse:
        """项目内生成批次分页列表。module 过滤匹配的是批次包含的生成模块。"""
        get_project_or_404(db, project_id, user)
        page = max(page, 1)
        page_size = min(max(page_size, 1), 200)
        query = db.query(CaseGenerationBatch).filter(CaseGenerationBatch.project_id == project_id)
        if direction:
            query = query.filter(CaseGenerationBatch.direction == direction)
        if status:
            query = query.filter(CaseGenerationBatch.status == status)
        if module:
            # JSON 数组整体转文本后做包含匹配，避免方言相关的 JSON 操作符。
            query = query.filter(cast(CaseGenerationBatch.modules_json, Text).like(f'%"{module}"%'))
        if keyword:
            query = query.filter(CaseGenerationBatch.requirements.ilike(f"%{keyword.strip()}%"))
        total = query.count()
        status_counts = dict(
            (row.status, row.count)
            for row in query.with_entities(CaseGenerationBatch.status, func.count().label("count"))
            .group_by(CaseGenerationBatch.status)
            .all()
        )
        batches = query.order_by(CaseGenerationBatch.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        draft_counts = {}
        if batches:
            rows = (
                db.query(CaseDraft.batch_id, CaseDraft.status, func.count())
                .filter(CaseDraft.batch_id.in_([batch.id for batch in batches]))
                .group_by(CaseDraft.batch_id, CaseDraft.status)
                .all()
            )
            for batch_id, draft_status, count in rows:
                draft_counts.setdefault(batch_id, {})[draft_status] = count
        items = []
        for batch in batches:
            counts = draft_counts.get(batch.id, {})
            items.append(GenerationBatchListItem(
                id=batch.id,
                project_id=batch.project_id,
                direction=batch.direction,
                status=batch.status,
                supervisor_name=batch.supervisor_name,
                modules=list(batch.modules_json or []),
                draft_total=sum(counts.values()),
                pending_count=counts.get("PENDING", 0),
                accepted_count=counts.get("ACCEPTED", 0),
                rejected_count=counts.get("REJECTED", 0),
                module_error_count=sum(1 for item in (batch.module_errors_json or []) if item.get("status") == "FAILED"),
                created_by=batch.created_by,
                created_at=batch.created_at,
            ))
        return GenerationBatchListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            completed_count=status_counts.get("COMPLETED", 0),
            partial_failed_count=status_counts.get("PARTIAL_FAILED", 0),
            failed_count=status_counts.get("FAILED", 0),
        )

    def batch_review(self, db: Session, batch_id: int, body: BatchReviewRequest, *, actor: User) -> BatchReviewResponse:
        """批量审核。accept 逐条入库并给出逐条结果；confirm 缺失时拒绝执行。"""
        if not body.confirm:
            raise bad_request("批量操作需要二次确认（confirm=true）")
        batch = self._writable_batch(db, batch_id, actor)
        query = db.query(CaseDraft).filter(CaseDraft.batch_id == batch.id, CaseDraft.status == "PENDING")
        if body.scope == "module":
            if not body.module:
                raise bad_request("按模块批量审核必须指定 module")
            query = query.filter(CaseDraft.module == body.module)
        elif body.scope == "drafts":
            if not body.draft_ids:
                raise bad_request("指定草稿批量审核必须提供 draft_ids")
            query = query.filter(CaseDraft.id.in_(body.draft_ids))
        drafts = query.order_by(CaseDraft.id.asc()).all()
        items: list[BatchReviewItem] = []
        if body.action == "accept":
            for draft in drafts:
                try:
                    with db.begin_nested():
                        case = self._import_draft(db, batch, draft, actor)
                        draft.status = "ACCEPTED"
                        draft.test_case_id = case.id
                        draft.import_error = None
                        draft.reviewed_by = actor.id
                        draft.reviewed_at = datetime.now()
                        self._audit(db, batch, draft, "APPROVE", actor, {"test_case_id": case.id, "batch_op": True})
                    items.append(BatchReviewItem(draft_id=draft.id, ok=True, test_case_id=case.id))
                except HTTPException as exc:
                    message = str(exc.detail)[:500]
                    draft.import_error = message
                    items.append(BatchReviewItem(draft_id=draft.id, ok=False, error=message))
        else:
            for draft in drafts:
                draft.status = "REJECTED"
                draft.review_comment = body.comment
                draft.reviewed_by = actor.id
                draft.reviewed_at = datetime.now()
                self._audit(db, batch, draft, "REJECT", actor, {"comment": body.comment, "batch_op": True})
                items.append(BatchReviewItem(draft_id=draft.id, ok=True))
        succeeded = sum(1 for item in items if item.ok)
        self._audit(db, batch, None, "BATCH_REVIEW", actor, {
            "action": body.action, "scope": body.scope, "module": body.module,
            "total": len(items), "succeeded": succeeded, "failed": len(items) - succeeded,
        })
        db.commit()
        return BatchReviewResponse(batch_id=batch.id, action=body.action, affected=succeeded, items=items)

    def regenerate(self, db: Session, batch_id: int, body: RegenerateRequest, *, actor: User, provider_factory=None) -> GenerationBatchResponse:
        """只重新生成失败模块。已成功与已审核草稿保持原样。"""
        batch = self._writable_batch(db, batch_id, actor)
        failed = [item["module"] for item in (batch.module_errors_json or []) if item.get("status") == "FAILED"]
        if not failed:
            raise bad_request("本批次没有失败模块需要重新生成")
        supervisor = db.get(AgentDefinition, batch.supervisor_agent_id) if batch.supervisor_agent_id else None
        if supervisor is None or not supervisor.is_enabled:
            raise bad_request("主 Agent 不存在或已停用，不能重新生成")
        from app.agents.services.case_generation_service import generate_case_suite
        suite = generate_case_suite(
            db, actor, supervisor.id,
            GenerationRequest(
                project_id=batch.project_id,
                requirements=batch.requirements,
                modules=failed,
                cases_per_module=body.cases_per_module,
                model_config_id=body.model_config_id or batch.model_config_id,
            ),
            provider_factory=provider_factory,
        )
        errors = [item for item in (batch.module_errors_json or []) if item.get("module") not in failed]
        for module in suite.get("modules") or []:
            if module.get("status") != "SUCCEEDED":
                errors.append({
                    "module": module.get("module"),
                    "status": module.get("status") or "FAILED",
                    "error": module.get("error") or "模块用例生成失败",
                })
                continue
            skills = self._skill_versions(db, module.get("id"))
            for raw in module.get("cases") or []:
                try:
                    case = DesignCase.model_validate(raw)
                except Exception:
                    errors.append({"module": module.get("module"), "status": "FAILED", "error": "草稿结构无效，已跳过"})
                    continue
                db.add(CaseDraft(
                    batch_id=batch.id,
                    module=str(module.get("module") or ""),
                    child_agent_id=module.get("id"),
                    child_version=int(module.get("version") or 1),
                    child_name=str(module.get("name") or ""),
                    model_config_id=module.get("model_config_id"),
                    model_name=module.get("model_name"),
                    skill_versions_json=skills,
                    title=case.title[:200],
                    priority=case.priority,
                    payload_json=case.model_dump(),
                    original_payload_json=case.model_dump(),
                    status="PENDING",
                ))
        batch.module_errors_json = errors
        metrics = list(batch.module_metrics_json or [])
        metrics.extend(self._metrics(suite))
        batch.module_metrics_json = metrics
        review = suite.get("review") or {}
        if review.get("status") == "SUCCEEDED":
            batch.review_summary = review.get("summary")
            batch.review_gaps_json = list(review.get("gaps") or [])
        remaining_failed = [item for item in errors if item.get("status") == "FAILED"]
        has_drafts = db.query(CaseDraft.id).filter(CaseDraft.batch_id == batch.id).first() is not None
        if not has_drafts:
            batch.status = "FAILED"
        elif remaining_failed:
            batch.status = "PARTIAL_FAILED"
        else:
            batch.status = "COMPLETED" if review.get("status") == "SUCCEEDED" else "PARTIAL_FAILED"
        db.flush()
        self._refresh_quality(db, batch)
        self._audit(db, batch, None, "REGENERATE", actor, {
            "modules": failed,
            "remaining_failed": [item.get("module") for item in remaining_failed],
        })
        db.commit()
        db.refresh(batch)
        return self._batch_response(db, batch)

    def list_audits(self, db: Session, batch_id: int, user: User) -> list[CaseGenerationAuditResponse]:
        """批次维度审计记录，按时间正序。"""
        batch = self._visible_batch(db, batch_id, user)
        rows = (
            db.query(CaseGenerationAudit)
            .filter(CaseGenerationAudit.batch_id == batch.id)
            .order_by(CaseGenerationAudit.id.asc())
            .all()
        )
        return [
            CaseGenerationAuditResponse(
                id=row.id, batch_id=row.batch_id, draft_id=row.draft_id, action=row.action,
                actor_id=row.actor_id, detail=dict(row.detail_json or {}), created_at=row.created_at,
            )
            for row in rows
        ]

    def trace(self, db: Session, case_id: int) -> GenerationTrace | None:
        """正式用例详情用的生成追溯。手工用例返回空。"""
        draft = db.query(CaseDraft).filter(CaseDraft.test_case_id == case_id).first()
        if draft is None:
            return None
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        if batch is None:
            return None
        return GenerationTrace(
            batch_id=batch.id,
            supervisor_agent_id=batch.supervisor_agent_id,
            supervisor_version=batch.supervisor_version,
            supervisor_name=batch.supervisor_name,
            model_config_id=draft.model_config_id or batch.model_config_id,
            model_name=draft.model_name or batch.model_name,
            module=draft.module,
            child_agent_id=draft.child_agent_id,
            child_version=draft.child_version,
            child_name=draft.child_name,
            skill_versions=list(draft.skill_versions_json or []),
            review_status=draft.status,
            review_summary=batch.review_summary,
        )

    def _available_modules(self, db: Session, supervisor: AgentDefinition) -> set[str]:
        modules = set()
        for child_id in supervisor.child_agent_ids or []:
            child = db.get(AgentDefinition, child_id)
            if child is None:
                continue
            for key in child.tool_keys or []:
                prefix = "case_generation.generate_"
                if key.startswith(prefix):
                    modules.add(key[len(prefix):])
        return modules

    def _skill_versions(self, db: Session, agent_id: int | None) -> list[dict]:
        if agent_id is None:
            return []
        agent = db.get(AgentDefinition, agent_id)
        if agent is None or not agent.skill_keys:
            return []
        rows = db.query(SkillDefinition).filter(SkillDefinition.key.in_(agent.skill_keys)).all()
        return [{"key": row.key, "version": row.version} for row in rows]

    def _case_type(self, case: DesignCase) -> str:
        text = " ".join(case.coverage)
        for value, words in _CASE_TYPE_WORDS:
            if any(word in text for word in words):
                return value
        return "FUNCTIONAL"

    def _import_draft(self, db: Session, batch: CaseGenerationBatch, draft: CaseDraft, actor: User) -> TestCase:
        """把一条草稿落成正式用例（DRAFT 态）。项目内重名直接冲突，不自动改名。"""
        payload = DesignCase.model_validate(draft.payload_json)
        name = payload.title.strip()[:200] or "未命名用例"
        if db.query(TestCase.id).filter(TestCase.project_id == batch.project_id, TestCase.name == name).first() is not None:
            raise conflict(f"项目内已存在同名测试用例「{name}」，请修改草稿标题后再入库")
        case = TestCase(
            project_id=batch.project_id,
            name=name,
            description=payload.requirement[:1000],
            priority=payload.priority,
            case_type=self._case_type(payload),
            target_type=_TARGET_BY_DIRECTION[batch.direction],
            status="DRAFT",
            enabled=True,
            source_type="AI",
            generation_version=batch.supervisor_version,
            generation_batch_id=batch.id,
            created_by=actor.id,
        )
        db.add(case)
        db.flush()
        for index, text in enumerate(payload.preconditions):
            db.add(TestCasePrecondition(
                test_case_id=case.id, type="TEXT", target="前置条件", operator="EQ",
                expected_value=text[:2000], sort=index,
            ))
        for index, text in enumerate(payload.test_data):
            db.add(TestCaseData(
                test_case_id=case.id, name=f"数据{index + 1}"[:100], value_type="STRING",
                value=text[:2000], source_type="STATIC", required=False, sort=index,
            ))
        for index, text in enumerate(payload.steps):
            db.add(TestStep(test_case_id=case.id, name=text[:200], step_type="ACTION", sort=index))
        for index, text in enumerate(payload.expected_results):
            db.add(TestAssertion(
                test_case_id=case.id, assertion_type="CONTAINS", operator="EQ",
                expected_value=text[:2000], required=True, sort=index,
            ))
        ScopeService().attach_new_case(db, case)
        if batch.scope_node_id is not None:
            # 生成时选了范围，就覆盖默认待整理归属。被测对象外键仍按用例自己的字段，不跟着目录改。
            db.query(TestCaseScope).filter(TestCaseScope.test_case_id == case.id).delete()
            db.add(TestCaseScope(test_case_id=case.id, scope_node_id=batch.scope_node_id))
        return case

    @staticmethod
    def _metrics(suite: dict) -> list[dict]:
        """从生成结果提取模块耗时与 token 指标；只保留数值与状态。"""
        metrics: list[dict] = []
        for module in suite.get("modules") or []:
            entry: dict[str, Any] = {
                "module": module.get("module"),
                "status": module.get("status"),
                "duration_ms": module.get("duration_ms"),
                "usage": module.get("usage") or {},
            }
            metrics.append(entry)
        review = suite.get("review") or {}
        if review:
            metrics.append({
                "module": "supervisor_review",
                "status": review.get("status"),
                "duration_ms": review.get("duration_ms"),
                "usage": review.get("usage") or {},
            })
        return metrics

    def _quality_for(self, db: Session, batch: CaseGenerationBatch | None, draft: CaseDraft) -> list[dict]:
        """重算一条草稿的规则校验结果。批次不存在时按空批次处理。"""
        if batch is None:
            return []
        siblings = [
            row.title
            for row in db.query(CaseDraft).filter(CaseDraft.batch_id == batch.id, CaseDraft.id != draft.id).all()
        ]
        module_payloads = [
            dict(row.payload_json or {})
            for row in db.query(CaseDraft).filter(
                CaseDraft.batch_id == batch.id, CaseDraft.module == draft.module, CaseDraft.id != draft.id,
            ).all()
        ]
        module_payloads.append(dict(draft.payload_json or {}))
        has_boundary = any(
            any(word in " ".join(str(item) for item in (payload.get("coverage") or [])).lower() for word in BOUNDARY_WORDS)
            for payload in module_payloads
        )
        return check_draft(
            db,
            project_id=batch.project_id,
            payload={**dict(draft.payload_json or {}), "title": draft.title},
            sibling_titles=siblings,
            module_has_boundary=has_boundary,
        )

    def _refresh_quality(self, db: Session, batch: CaseGenerationBatch) -> None:
        """批次内全部草稿重算规则校验。生成与再生成落库前调用。"""
        drafts = db.query(CaseDraft).filter(CaseDraft.batch_id == batch.id).all()
        module_has_boundary: dict[str, bool] = {}
        for draft in drafts:
            coverage = " ".join(str(item) for item in ((draft.payload_json or {}).get("coverage") or []))
            if any(word in coverage.lower() for word in BOUNDARY_WORDS):
                module_has_boundary[draft.module] = True
        titles = [draft.title for draft in drafts]
        for index, draft in enumerate(drafts):
            # 按位置排除自身，同值标题仍然互相可见，才能发现批内重复。
            siblings = [title for offset, title in enumerate(titles) if offset != index]
            draft.quality_json = check_draft(
                db,
                project_id=batch.project_id,
                payload={**dict(draft.payload_json or {}), "title": draft.title},
                sibling_titles=siblings,
                module_has_boundary=module_has_boundary.get(draft.module, False),
            )

    @staticmethod
    def _audit(
        db: Session, batch: CaseGenerationBatch | None, draft: CaseDraft | None,
        action: str, actor: User, detail: dict,
    ) -> None:
        """写一行审核审计。batch 缺失时静默跳过（不阻断主流程）。"""
        if batch is None:
            return
        db.add(CaseGenerationAudit(
            project_id=batch.project_id,
            batch_id=batch.id,
            draft_id=draft.id if draft else None,
            action=action,
            actor_id=actor.id,
            detail_json=detail,
        ))

    def _writable_batch(self, db: Session, batch_id: int, actor: User) -> CaseGenerationBatch:
        batch = db.get(CaseGenerationBatch, batch_id)
        if batch is None:
            raise not_found("生成批次不存在")
        require_writable_project(db, batch.project_id, actor)
        return batch

    def _visible_batch(self, db: Session, batch_id: int, user: User) -> CaseGenerationBatch:
        batch = db.get(CaseGenerationBatch, batch_id)
        if batch is None:
            raise not_found("生成批次不存在")
        get_project_or_404(db, batch.project_id, user)
        return batch

    def _writable_draft(self, db: Session, draft_id: int, actor: User, *, lock: bool = False) -> CaseDraft:
        query = db.query(CaseDraft).filter(CaseDraft.id == draft_id)
        if lock:
            # 入库加行锁：并发接受同一草稿时后者等待，由状态判断兜底幂等。
            query = query.with_for_update()
        draft = query.first()
        if draft is None:
            raise not_found("用例草稿不存在")
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        if batch is None:
            raise not_found("生成批次不存在")
        require_writable_project(db, batch.project_id, actor)
        return draft

    def _batch_response(self, db: Session, batch: CaseGenerationBatch) -> GenerationBatchResponse:
        drafts = db.query(CaseDraft).filter(CaseDraft.batch_id == batch.id).order_by(CaseDraft.id.asc()).all()
        return GenerationBatchResponse(
            id=batch.id,
            project_id=batch.project_id,
            direction=batch.direction,
            scope_node_id=batch.scope_node_id,
            supervisor_agent_id=batch.supervisor_agent_id,
            supervisor_version=batch.supervisor_version,
            supervisor_name=batch.supervisor_name,
            model_config_id=batch.model_config_id,
            model_name=batch.model_name,
            status=batch.status,
            review_summary=batch.review_summary,
            review_gaps=list(batch.review_gaps_json or []),
            module_errors=list(batch.module_errors_json or []),
            module_metrics=list(batch.module_metrics_json or []),
            drafts=[self._draft_response(row) for row in drafts],
            created_at=batch.created_at,
        )

    def _draft_response(self, draft: CaseDraft) -> CaseDraftResponse:
        return CaseDraftResponse(
            id=draft.id,
            batch_id=draft.batch_id,
            module=draft.module,
            child_agent_id=draft.child_agent_id,
            child_version=draft.child_version,
            child_name=draft.child_name,
            model_config_id=draft.model_config_id,
            model_name=draft.model_name,
            skill_versions=list(draft.skill_versions_json or []),
            title=draft.title,
            priority=draft.priority,
            payload=dict(draft.payload_json or {}),
            original_payload=dict(draft.original_payload_json or {}),
            quality=list(draft.quality_json or []),
            status=draft.status,
            review_comment=draft.review_comment,
            reviewed_at=draft.reviewed_at,
            test_case_id=draft.test_case_id,
            import_error=draft.import_error,
            updated_at=draft.updated_at,
        )
