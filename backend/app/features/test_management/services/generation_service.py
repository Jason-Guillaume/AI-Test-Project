"""把 Super Agent 的未落库草稿收成批次，并在人工接受后写入正式用例。

不修改 case_generation 的工具契约。方向只决定调用哪些已授权模块：
API→api，UI→web，AI→ai 与 asr，security 仅在用户勾选且主 Agent 已绑定时加入。
单模块失败只记在批次错误里，已成功的草稿仍可审核。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition
from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.notifications.notify import notify
from app.features.test_management.models.case_generation import CaseDraft, CaseGenerationBatch
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_case_precondition import TestCasePrecondition
from app.features.test_management.models.test_scope import TestCaseScope
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.schemas.generation import (
    CaseDraftResponse,
    DraftDecisionResponse,
    DraftUpdateRequest,
    GenerationAgentOption,
    GenerationBatchResponse,
    GenerationStartRequest,
    GenerationTrace,
)
from app.features.test_management.scope_placement import DIRECTIONS
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
                    status="PENDING",
                ))
        batch.module_errors_json = errors
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
        db.commit()
        db.refresh(draft)
        return self._draft_response(draft)

    def accept_draft(self, db: Session, draft_id: int, *, actor: User) -> DraftDecisionResponse:
        """接受草稿并写入正式用例。重复接受不会再造一条用例。"""
        draft = self._writable_draft(db, draft_id, actor)
        if draft.status == "ACCEPTED" and draft.test_case_id:
            return DraftDecisionResponse(draft_id=draft.id, status=draft.status, test_case_id=draft.test_case_id, source_type="AI")
        if draft.status != "PENDING":
            raise bad_request("该草稿已审核，不能入库")
        batch = db.get(CaseGenerationBatch, draft.batch_id)
        if batch is None:
            raise not_found("生成批次不存在")
        payload = DesignCase.model_validate(draft.payload_json)
        case = TestCase(
            project_id=batch.project_id,
            name=self._unique_name(db, batch.project_id, payload.title),
            description=payload.requirement[:1000],
            priority=payload.priority,
            case_type=self._case_type(payload),
            target_type=_TARGET_BY_DIRECTION[batch.direction],
            status="ACTIVE",
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
        draft.status = "ACCEPTED"
        draft.test_case_id = case.id
        notify(
            db, user_id=actor.id, event_type="test.case.created",
            title=f"你已接受生成用例「{case.name}」", project_id=batch.project_id,
            actor_id=actor.id, actor_username=actor.username, detail={"case_id": case.id, "draft_id": draft.id},
        )
        db.commit()
        return DraftDecisionResponse(draft_id=draft.id, status="ACCEPTED", test_case_id=case.id, source_type="AI")

    def reject_draft(self, db: Session, draft_id: int, *, actor: User) -> DraftDecisionResponse:
        """拒绝草稿。不创建用例，也不能再接受。"""
        draft = self._writable_draft(db, draft_id, actor)
        if draft.status != "PENDING":
            raise bad_request("该草稿已审核")
        draft.status = "REJECTED"
        db.commit()
        return DraftDecisionResponse(draft_id=draft.id, status="REJECTED", test_case_id=None, source_type=None)

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

    def _unique_name(self, db: Session, project_id: int, title: str) -> str:
        base = title.strip()[:200] or "未命名用例"
        if db.query(TestCase.id).filter(TestCase.project_id == project_id, TestCase.name == base).first() is None:
            return base
        suffix = 2
        while suffix < 100:
            candidate = f"{base[:190]} #{suffix}"
            if db.query(TestCase.id).filter(TestCase.project_id == project_id, TestCase.name == candidate).first() is None:
                return candidate
            suffix += 1
        raise bad_request("用例名称冲突过多，请修改草稿标题")

    def _visible_batch(self, db: Session, batch_id: int, user: User) -> CaseGenerationBatch:
        batch = db.get(CaseGenerationBatch, batch_id)
        if batch is None:
            raise not_found("生成批次不存在")
        get_project_or_404(db, batch.project_id, user)
        return batch

    def _writable_draft(self, db: Session, draft_id: int, actor: User) -> CaseDraft:
        draft = db.get(CaseDraft, draft_id)
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
            status=draft.status,
            test_case_id=draft.test_case_id,
            updated_at=draft.updated_at,
        )
