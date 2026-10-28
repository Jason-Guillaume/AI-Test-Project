"""统一任务读写、权限、可靠命令与审计事件服务。

路由层仅处理参数和身份依赖；本服务拥有任务事务边界，并通过项目角色校验保护运行、消息和产物引用。
后台执行由 tasks.runtime.worker 驱动，业务执行仍委托给现有 API 测试与报告能力。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskCommand,
    TaskEvent,
    TaskMessage,
    TaskPlan,
    TaskResourceRef,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)
from app.features.tasks.schemas import (
    TaskCommandCreate,
    TaskCreate,
    TaskMessageCreate,
    TaskWorkItemResponse,
)
from app.features.business_assembly.schemas import AssemblyTaskCreate
from app.features.test_management.models.test_case import TestCase
from app.models.configuration import ModelConfiguration
from app.features.environment_configuration.services.environment_service import resolve_project_environment
from app.features.agent_governance.models import AgentDefinition, MCPServer, SkillDefinition, SkillUsageEvent
from app.models.identity import OrganizationMember, User
from app.models.project import Project
from app.shared.errors import bad_request, conflict, forbidden, not_found
from app.shared.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    is_platform_admin,
    project_role_for,
)
from app.features.agent.providers.sanitizer import sanitize_context, sanitize_text


RUN_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED", "SUPERSEDED"})
RUN_PAUSE_STATUSES = frozenset({"PAUSED", "PAUSE_REQUESTED"})
RETRYABLE_RUN_STATUSES = frozenset({"FAILED", "RECONCILIATION_REQUIRED", "SUCCEEDED_WITH_ISSUES"})
RETRYABLE_WORK_ITEM_KINDS = frozenset({
    "PLAN", "CHAT", "REPORT", "FINALIZE", "EXECUTE_API", "EXECUTE_WEB", "EXECUTE_WEB_AUTHORING", "EXECUTE_SECURITY", "ASSEMBLE_BUSINESS",
})
UNCERTAIN_INVOCATION_STATUSES = frozenset({"STARTED", "NEEDS_RECONCILIATION"})

TASK_NOTIFICATION_EVENTS = {
    "plan.proposed": ("task.plan_ready", "任务方案待确认"),
    "run.completed": ("task.completed", "任务已完成"),
    "run.completed_with_issues": ("task.completed_with_issues", "任务完成但有问题"),
    "work_item.failed": ("task.failed", "任务执行失败"),
    "llm.fallback_exhausted": ("task.waiting_model", "任务等待模型配置恢复"),
    "run.reconciliation_required": ("task.reconciliation_required", "任务执行结果待核对"),
}

TASK_AGENT_BASE_TOOLS = {
    "test_asset.get_existing_cases",
    "execution.get_test_run",
    "execution.create_test_run",
    "report.generate",
    "report.review",
}
TASK_AGENT_API_TOOLS = {"api_catalog.search_api"}
TASK_AGENT_SECURITY_TOOLS = {
    "security.preview_plan",
    "security.list_strategies",
    "security.read_api_context",
    "security.read_findings",
    "security.confirm_plan",
    "security.execute_cases",
    "execution.get_test_run",
    "report.generate",
    "report.review",
}


class TaskService:
    """统一任务服务；实例无状态，可在路由间安全复用。"""

    def create_task(self, db: Session, project_id: int, body: TaskCreate, *, actor: User) -> dict[str, Any]:
        """校验已确认的测试资产或安全评估范围，创建首个运行与对应 Worker。"""
        project = self._get_project_for_write(db, project_id, actor)
        case_ids = list(dict.fromkeys(body.case_ids))
        security_assessment = body.security_assessment.model_dump() if body.security_assessment else None
        web_authoring = body.web_authoring.model_dump() if body.web_authoring else None
        if body.task_mode == "WEB_AUTHORING":
            if case_ids or security_assessment or web_authoring is None:
                raise bad_request("交互式 Web 编写需提供会话范围，且不能绑定用例或安全评估")
            from app.features.web_ui.models import WebAuthProfile

            auth_profile_id = web_authoring.get("auth_profile_id")
            if auth_profile_id:
                profile = db.get(WebAuthProfile, int(auth_profile_id))
                if profile is None or profile.project_id != project.id or profile.environment_id != body.environment_id:
                    raise not_found("登录态配置不存在或不属于当前项目/环境")
                if profile.expires_at <= datetime.now():
                    raise bad_request("登录态已过期，请重新配置")
            target_type = "WEB_AUTHORING"
        elif web_authoring is not None:
            raise bad_request("只有交互式 Web 编写任务可以附带 Web 会话范围")
        elif security_assessment:
            if case_ids:
                raise bad_request("自研安全评估任务不能同时绑定 API 或 Web 功能用例")
            target_type = "SECURITY"
            from app.features.api_catalog.models.api_interface import ApiInterface
            from app.features.security_testing.models import SecurityStrategy

            api_ids = list(dict.fromkeys(int(i) for i in (security_assessment.get("api_ids") or [])))
            legacy_api_id = security_assessment.get("api_id")
            if not api_ids and legacy_api_id:
                api_ids = [int(legacy_api_id)]
            if not api_ids or len(api_ids) > 10:
                raise bad_request("自研安全评估需选择 1 到 10 个登记 API")
            api_rows = db.query(ApiInterface).filter(
                ApiInterface.id.in_(api_ids), ApiInterface.project_id == project.id,
            ).all()
            api_by_id = {row.id: row for row in api_rows}
            if len(api_by_id) != len(api_ids):
                raise not_found("部分目标接口不存在或不属于当前项目")
            if any(row.status != "ACTIVE" for row in api_rows):
                raise bad_request("自研安全评估只能选择 ACTIVE API")
            baseline_api_ids = {
                row.api_id for row in db.query(TestCase.api_id).filter(
                    TestCase.project_id == project.id,
                    TestCase.api_id.in_(api_ids),
                    TestCase.target_type == "API",
                    TestCase.case_type != "SECURITY",
                    TestCase.status == "ACTIVE",
                    TestCase.enabled.is_(True),
                ).all()
            }
            missing_baselines = [api_id for api_id in api_ids if api_id not in baseline_api_ids]
            if missing_baselines:
                raise bad_request(f"API {missing_baselines} 缺少已启用的 ACTIVE 功能用例，不能作为安全变异基线")
            security_assessment["api_ids"] = api_ids
            security_assessment["api_id"] = api_ids[0]
            web_session_id = security_assessment.get("web_session_id")
            if web_session_id:
                from app.features.web_ui.models import WebAgentSession
                from app.features.web_ui.runtime.session_manager import registry

                web_session = db.query(WebAgentSession).filter(
                    WebAgentSession.id == int(web_session_id),
                    WebAgentSession.project_id == project.id,
                    WebAgentSession.status == "ACTIVE",
                ).first()
                if web_session is None or web_session.task_run_id is not None or registry.get_session(web_session.id) is None:
                    raise bad_request("Web 页面检查需选择当前项目中仍打开的受控会话")
                security_assessment["web_session_id"] = web_session.id
            security_assessment["strategy_ids"] = list(dict.fromkeys(int(i) for i in security_assessment["strategy_ids"]))
            strategies = db.query(SecurityStrategy).filter(
                SecurityStrategy.id.in_(security_assessment["strategy_ids"]),
                SecurityStrategy.enabled.is_(True),
                (SecurityStrategy.project_id.is_(None)) | (SecurityStrategy.project_id == project.id),
            ).all()
            if len(strategies) != len(security_assessment["strategy_ids"]):
                raise not_found("部分安全策略不存在、已停用或不属于当前项目")
        else:
            if not case_ids:
                raise bad_request("API / Web 任务至少选择一个已确认用例，或创建自研安全评估任务")
            cases = db.query(TestCase).filter(TestCase.id.in_(case_ids)).all()
            if len(cases) != len(case_ids):
                raise not_found("部分测试用例不存在")
            case_by_id = {case.id: case for case in cases}
            target_types: set[str] = set()
            for case_id in case_ids:
                case = case_by_id[case_id]
                if case.project_id != project.id:
                    raise not_found("测试用例不存在")
                if not case.enabled or case.status != "ACTIVE" or case.target_type not in {"API", "WEB"}:
                    raise bad_request("任务仅支持已启用且已确认的 API 或 Web 用例")
                target_types.add(case.target_type)
                if case.target_type == "API" and case.api_id is None:
                    raise bad_request("API 用例缺少接口定义")
                if case.target_type == "WEB":
                    from app.features.web_ui.models import WebCase
                    from app.features.web_ui.services.web_ui_service import case_response
                    if db.get(WebCase, case.id) is None or not case_response(db, case).get("confirmed"):
                        raise bad_request("Web 用例必须先在 Web 管理页确认当前版本")
            if len(target_types) != 1:
                raise bad_request("一个任务运行需选择同一执行器类型的用例；API 与 Web 请分别创建任务")
            target_type = next(iter(target_types))
        environment = resolve_project_environment(db, project.id, body.environment_id)
        if security_assessment and security_assessment.get("web_session_id"):
            if web_session.environment_id != environment.id:
                raise bad_request("Web 页面检查会话与安全评估执行环境必须一致")

        goal = sanitize_text(body.goal).strip()
        title = sanitize_text(body.title or "").strip() or goal[:80]

        if body.request_key:
            existing = (
                db.query(Task)
                .filter(Task.created_by == actor.id, Task.request_key == body.request_key)
                .first()
            )
            if existing is not None:
                if (
                    existing.project_id != project.id
                    or existing.goal != goal
                    or existing.title != title[:200]
                    or existing.environment_id != environment.id
                    or existing.input_case_ids != case_ids
                    or (existing.security_assessment_json or None) != security_assessment
                    or existing.agent_definition_id != body.agent_definition_id
                    or existing.task_mode != body.task_mode
                    or (existing.web_authoring_json or None) != web_authoring
                ):
                    raise conflict("相同 request_key 已用于不同任务内容")
                return self._task_detail(db, existing)

        agent_bundle = self._resolve_agent_profile(
            db,
            project_id=project.id,
            agent_definition_id=body.agent_definition_id,
            actor=actor,
            target_type="WEB" if target_type == "WEB_AUTHORING" else target_type,
        )
        if security_assessment and security_assessment.get("web_session_id") and agent_bundle:
            if "security.inspect_web_session" not in (agent_bundle["snapshot"].get("tool_keys") or []):
                raise bad_request("所选安全 Agent 未获授权检查受控 Web 会话")

        task = Task(
            project_id=project.id,
            created_by=actor.id,
            agent_definition_id=body.agent_definition_id,
            title=title[:200],
            goal=goal,
            environment_id=environment.id,
            input_case_ids=case_ids,
            task_mode=body.task_mode,
            web_authoring_json=web_authoring,
            security_assessment_json=security_assessment,
            request_key=body.request_key,
        )
        db.add(task)
        db.flush()
        run = self._create_run(db, task, actor, run_number=1, target_type=target_type, agent_bundle=agent_bundle)
        task.status = run.status
        try:
            db.commit()
        except IntegrityError:
            # 同一用户并发重放相同 request_key 时由唯一约束裁决，回读胜出的任务而不重复排程。
            db.rollback()
            if body.request_key:
                existing = db.query(Task).filter(
                    Task.created_by == actor.id, Task.request_key == body.request_key,
                ).first()
                if existing is not None and (
                    existing.project_id == project.id
                    and existing.goal == goal
                    and existing.title == title[:200]
                    and existing.environment_id == environment.id
                    and existing.input_case_ids == case_ids
                    and (existing.security_assessment_json or None) == security_assessment
                    and existing.agent_definition_id == body.agent_definition_id
                    and existing.task_mode == body.task_mode
                    and (existing.web_authoring_json or None) == web_authoring
                ):
                    return self._task_detail(db, existing)
            raise
        db.refresh(task)
        return self._task_detail(db, task)

    def create_business_assembly_task(
        self, db: Session, project_id: int, body: AssemblyTaskCreate, *, actor: User,
    ) -> dict[str, Any]:
        """创建无需测试环境的业务组装任务，并冻结可用知识版本范围。"""
        project = self._get_project_for_write(db, project_id, actor)
        version_ids = list(dict.fromkeys(body.document_version_ids))
        if len(version_ids) != len(body.document_version_ids):
            raise bad_request("知识文档版本不能重复选择")
        from app.features.knowledge.models import KnowledgeDocument, KnowledgeDocumentVersion

        versions = db.query(KnowledgeDocumentVersion, KnowledgeDocument).join(
            KnowledgeDocument, KnowledgeDocumentVersion.document_id == KnowledgeDocument.id,
        ).filter(KnowledgeDocumentVersion.id.in_(version_ids)).all()
        valid = {
            version.id for version, document in versions
            if document.knowledge_base_id
            and document.status == "ACTIVE"
            and document.deleted_at is None
            and document.active_version_id == version.id
            and version.parse_status == "READY"
        }
        if valid != set(version_ids):
            raise not_found("部分知识文档版本未启用、未解析完成或不属于当前项目")
        from app.features.knowledge.models import KnowledgeBase

        base_project_ids = {
            base.project_id for base in db.query(KnowledgeBase).filter(
                KnowledgeBase.id.in_({document.knowledge_base_id for _, document in versions}),
                KnowledgeBase.enabled.is_(True),
            ).all()
        }
        if base_project_ids != {project.id}:
            raise not_found("部分知识文档版本未启用、未解析完成或不属于当前项目")

        goal = sanitize_text(body.goal).strip()
        title = sanitize_text(body.title or "").strip() or goal[:80]
        selection = {"document_version_ids": version_ids}
        existing = db.query(Task).filter(
            Task.created_by == actor.id,
            Task.request_key == body.request_key,
        ).first()
        if existing is not None:
            if (
                existing.project_id != project.id
                or existing.task_mode != "BUSINESS_ASSEMBLY"
                or existing.goal != goal
                or existing.title != title[:200]
                or (existing.business_assembly_json or {}) != selection
            ):
                raise conflict("相同 request_key 已用于不同任务内容")
            return self._task_detail(db, existing)

        # 组装只调用当前项目成员已获授权的模型，不绑定测试环境或测试执行 Agent。
        task = Task(
            project_id=project.id,
            created_by=actor.id,
            title=title[:200],
            goal=goal,
            environment_id=None,
            input_case_ids=[],
            task_mode="BUSINESS_ASSEMBLY",
            business_assembly_json=selection,
            request_key=body.request_key,
        )
        db.add(task)
        db.flush()
        run = self._create_run(db, task, actor, run_number=1, target_type="BUSINESS_ASSEMBLY")
        task.status = run.status
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(Task).filter(
                Task.created_by == actor.id, Task.request_key == body.request_key,
            ).first()
            if existing is not None and (
                existing.project_id == project.id
                and existing.task_mode == "BUSINESS_ASSEMBLY"
                and existing.goal == goal
                and existing.title == title[:200]
                and (existing.business_assembly_json or {}) == selection
            ):
                return self._task_detail(db, existing)
            raise
        db.refresh(task)
        return self._task_detail(db, task)

    def list_available_agents(
        self, db: Session, project_id: int, *, actor: User, target_type: str,
    ) -> list[dict[str, Any]]:
        """列出当前任务可以完整执行的 Agent；不给普通用户暴露内部提示词与 Skill 正文。"""
        project = self._get_project_for_write(db, project_id, actor)
        models = db.query(ModelConfiguration).filter(ModelConfiguration.is_enabled.is_(True)).all()
        if not is_platform_admin(actor):
            if project.organization_id is None:
                return []
            membership = db.query(OrganizationMember).filter(
                OrganizationMember.organization_id == project.organization_id,
                OrganizationMember.user_id == actor.id,
            ).first()
            if membership is None or not membership.agent_enabled:
                return []
            allowed_ids = {str(item) for item in (membership.allowed_model_ids or [])}
            models = [model for model in models if model.domain_id in allowed_ids]
        allowed_model_ids = {model.id for model in models}
        if not allowed_model_ids:
            return []

        required_tools = self._required_agent_tools(target_type)
        enabled_skill_keys = {
            key for (key,) in db.query(SkillDefinition.key).filter(SkillDefinition.is_enabled.is_(True)).all()
        }
        rows = db.query(AgentDefinition).filter(AgentDefinition.is_enabled.is_(True)).order_by(
            AgentDefinition.name.asc(), AgentDefinition.id.asc(),
        ).all()
        options: list[dict[str, Any]] = []
        for row in rows:
            if not self._agent_workflow_matches(row.workflow_template, target_type):
                continue
            if not required_tools.issubset(set(row.tool_keys or [])):
                continue
            if row.model_config_id is not None and row.model_config_id not in allowed_model_ids:
                continue
            if not row.model_config_id and not allowed_model_ids:
                continue
            mcp_ok = True
            for tool_key in row.tool_keys or []:
                if not tool_key.startswith("mcp:"):
                    continue
                try:
                    _, server_id_text, tool_name = tool_key.split(":", 2)
                    server = db.get(MCPServer, int(server_id_text))
                except (ValueError, TypeError):
                    server = None
                    tool_name = ""
                tool = next((item for item in (server.discovered_tools_json or []) if item.get("name") == tool_name), None) if server else None
                if (
                    server is None or not server.is_enabled or server.connection_status != "connected"
                    or tool_name not in (server.approved_tools_json or []) or tool is None
                    or (tool.get("annotations") or {}).get("readOnlyHint") is not True
                ):
                    mcp_ok = False
                    break
            if not mcp_ok:
                continue
            skill_keys = row.skill_keys or []
            if len(set(skill_keys)) != len(skill_keys) or not set(skill_keys).issubset(enabled_skill_keys):
                continue
            child_ids = row.child_agent_ids or []
            if child_ids:
                children = db.query(AgentDefinition).filter(AgentDefinition.id.in_(child_ids)).all()
                if len(children) != len(set(child_ids)) or any(not item.is_enabled or item.child_agent_ids or item.tool_keys for item in children):
                    continue
                if any(item.model_config_id is not None and item.model_config_id not in allowed_model_ids for item in children):
                    continue
                child_skills = {key for (key,) in db.query(SkillDefinition.key).filter(
                    SkillDefinition.key.in_({key for item in children for key in (item.skill_keys or [])}),
                    SkillDefinition.is_enabled.is_(True),
                ).all()} if any(item.skill_keys for item in children) else set()
                if any(not set(item.skill_keys or []).issubset(child_skills) for item in children):
                    continue
            options.append({
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "workflow_template": row.workflow_template,
                "version": row.version,
            })
        return options

    @staticmethod
    def _required_agent_tools(target_type: str) -> set[str]:
        """处理`required`智能体工具相关数据。"""
        if target_type == "SECURITY":
            return set(TASK_AGENT_SECURITY_TOOLS)
        required = set(TASK_AGENT_BASE_TOOLS)
        if target_type == "API":
            required.update(TASK_AGENT_API_TOOLS)
        return required

    @staticmethod
    def _agent_workflow_matches(workflow: str, target_type: str) -> bool:
        """处理智能体工作流`matches`相关数据。"""
        compatible = {
            "API": {"api_test", "reporting"},
            "WEB": {"web_ui", "reporting"},
            "SECURITY": {"security"},
        }
        return workflow in compatible.get(target_type, set())

    def _resolve_agent_profile(
        self, db: Session, *, project_id: int, agent_definition_id: int | None,
        actor: User, target_type: str,
    ) -> dict[str, Any] | None:
        """解析并冻结 Agent、Skill 与经项目组织授权的模型配置。"""
        if agent_definition_id is None:
            return None
        definition = db.get(AgentDefinition, agent_definition_id)
        if definition is None:
            raise not_found("Agent 配置不存在")
        if not definition.is_enabled:
            raise bad_request("所选 Agent 已停用")
        if not self._agent_workflow_matches(definition.workflow_template, target_type):
            raise bad_request("所选 Agent 工作流与任务执行类型不匹配")
        required_tools = self._required_agent_tools(target_type)
        missing_tools = required_tools - set(definition.tool_keys or [])
        if missing_tools:
            raise bad_request("所选 Agent 缺少当前任务所需的工具授权，请在 Agent 治理中心补齐权限")

        skill_rows = db.query(SkillDefinition).filter(
            SkillDefinition.key.in_(definition.skill_keys or []),
        ).all() if definition.skill_keys else []
        skills_by_key = {row.key: row for row in skill_rows}
        if len(skills_by_key) != len(definition.skill_keys or []) or any(
            not skills_by_key[key].is_enabled for key in (definition.skill_keys or [])
        ):
            raise bad_request("所选 Agent 关联的 Skill 不存在或已停用")
        skills = [skills_by_key[key] for key in (definition.skill_keys or [])]
        if sum(sum(len(content) for content in (skill.files_json or {"SKILL.md": skill.content}).values()) for skill in skills) > 100_000:
            raise bad_request("所选 Agent 的 Skill 内容过大，请减少关联 Skill")

        settings = dict(definition.settings_json or {})
        binding = settings.get("model_binding")
        requested_model_id = definition.model_config_id if binding in {None, "agent"} else None
        model = self._resolve_authorized_model(
            db, project_id, actor, requested_model_id=requested_model_id,
        )
        child_rows_from_db = db.query(AgentDefinition).filter(
            AgentDefinition.id.in_(definition.child_agent_ids or []),
        ).all() if definition.child_agent_ids else []
        child_by_id = {child.id: child for child in child_rows_from_db}
        child_rows = [child_by_id[child_id] for child_id in (definition.child_agent_ids or []) if child_id in child_by_id]
        if len(child_rows) != len(definition.child_agent_ids or []) or any(
            not child.is_enabled or child.child_agent_ids or child.tool_keys for child in child_rows
        ):
            raise bad_request("所选 Agent 的子 Agent 已停用或配置不再有效")
        child_snapshots = []
        for child in child_rows:
            child_skills_by_key = {
                skill.key: skill for skill in db.query(SkillDefinition).filter(
                    SkillDefinition.key.in_(child.skill_keys or []),
                ).all()
            } if child.skill_keys else {}
            if len(child_skills_by_key) != len(child.skill_keys or []) or any(
                not child_skills_by_key[key].is_enabled for key in (child.skill_keys or [])
            ):
                raise bad_request(f"子 Agent「{child.name}」关联的 Skill 不存在或已停用")
            child_model = self._resolve_authorized_model(
                db, project_id, actor,
                requested_model_id=child.model_config_id if child.model_config_id is not None else model.id,
            )
            child_model_snapshot = self._model_snapshot(child_model)
            child_snapshots.append({
                "id": child.id,
                "key": child.key,
                "name": child.name,
                "version": child.version,
                "instruction": child.instruction,
                "model_config_id": child_model.id,
                "fallback_model_config_ids": child_model_snapshot.get("fallback_model_config_ids", []),
                "skills": [
                    {
                        "key": skill.key, "name": skill.name, "version": skill.version,
                        "content": skill.content,
                    }
                    for skill in (child_skills_by_key[key] for key in (child.skill_keys or []))
                ],
            })
        mcp_tools_snapshot = []
        resolved_tool_keys = list(dict.fromkeys([
            *(definition.tool_keys or []),
            *(key for skill in skills for key in (skill.mcp_tool_keys_json or [])),
        ]))
        for tool_key in resolved_tool_keys:
            if not tool_key.startswith("mcp:"):
                continue
            try:
                _, server_id_text, tool_name = tool_key.split(":", 2)
                server = db.get(MCPServer, int(server_id_text))
            except (ValueError, TypeError):
                server = None
                tool_name = ""
            discovered = next(
                (item for item in (server.discovered_tools_json or []) if item.get("name") == tool_name), None,
            ) if server is not None else None
            if (
                server is None or not server.is_enabled or server.connection_status != "connected"
                or tool_name not in (server.approved_tools_json or []) or discovered is None
                or (discovered.get("annotations") or {}).get("readOnlyHint") is not True
            ):
                raise bad_request("Agent 关联的 MCP 工具当前未连接、未审批或不再标记为只读")
            mcp_tools_snapshot.append({
                "key": tool_key,
                "server_id": server.id,
                "server_name": server.name,
                "tool_name": tool_name,
                "description": discovered.get("description", "")[:1000],
                "input_schema": discovered.get("inputSchema") or {"type": "object", "properties": {}},
            })
        return {
            "definition": definition,
            "model": model,
            "snapshot": {
                "id": definition.id,
                "key": definition.key,
                "name": definition.name,
                "version": definition.version,
                "workflow_template": definition.workflow_template,
                "instruction": definition.instruction,
                "tool_keys": resolved_tool_keys,
                "settings_json": settings,
                "triggers_json": list(definition.triggers_json or []),
                "child_agent_ids": list(definition.child_agent_ids or []),
                "skills": [
                    {
                        "key": skill.key,
                        "name": skill.name,
                        "version": skill.version,
                        "content": skill.content,
                        "files_json": dict(skill.files_json or {"SKILL.md": skill.content}),
                        "mcp_tool_keys_json": list(skill.mcp_tool_keys_json or []),
                    }
                    for skill in skills
                ],
                "child_agents": child_snapshots,
                "mcp_tools": mcp_tools_snapshot,
            },
        }

    def list_tasks(
        self, db: Session, user: User, *, page: int, page_size: int,
        project_id: int | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        """列出当前用户可见项目的任务，采用仓库统一分页形状。"""
        visible_ids = accessible_project_ids(db, user)
        query = db.query(Task)
        if project_id is not None:
            self._get_project_for_read(db, project_id, user)
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            # 空可见集合用 [-1] 占位，避免 IN () 在不同数据库上行为不一致。
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        if status:
            query = query.filter(Task.status == status)
        total = int(query.order_by(None).with_entities(func.count()).scalar() or 0)
        rows = query.order_by(Task.updated_at.desc(), Task.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        latest_by_task = self._latest_runs(db, [row.id for row in rows])
        items = [self._task_response(row, latest_by_task.get(row.id)) for row in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_task(self, db: Session, task_id: int, user: User) -> dict[str, Any]:
        """读取任务与最新运行；跨项目不可见统一返回 404。"""
        task = self._get_task_for_read(db, task_id, user)
        return self._task_detail(db, task)

    def get_run_detail(self, db: Session, run_id: int, user: User) -> dict[str, Any]:
        """读取运行、方案、独立参与者和子任务。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        # 各查询在 READ COMMITTED 下可能跨过 Planner 的一次提交；最后刷新运行权威状态，
        # 避免同一响应同时出现“方案已持久化、运行仍在规划中”的短暂混合视图。
        plans = db.query(TaskPlan).filter(TaskPlan.task_run_id == run.id).order_by(TaskPlan.version.asc()).all()
        agents = db.query(TaskAgentInstance).filter(TaskAgentInstance.task_run_id == run.id).order_by(TaskAgentInstance.id.asc()).all()
        work_items = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id).order_by(TaskWorkItem.sequence.asc(), TaskWorkItem.id.asc()).all()
        tool_invocations = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.task_run_id == run.id,
        ).order_by(TaskToolInvocation.created_at.asc(), TaskToolInvocation.id.asc()).all()
        db.refresh(run)
        invocations_by_work_item: dict[int, list[TaskToolInvocation]] = {}
        for invocation in tool_invocations:
            invocations_by_work_item.setdefault(invocation.work_item_id, []).append(invocation)
        work_item_responses = []
        for work_item in work_items:
            block_reason = self._retry_block_reason(
                run,
                work_item,
                invocations_by_work_item.get(work_item.id, []),
            )
            response = TaskWorkItemResponse.model_validate(work_item).model_dump()
            response["retryable"] = block_reason is None
            response["retry_block_reason"] = block_reason
            work_item_responses.append(response)
        return {
            "run": self._run_response(run),
            "plans": plans,
            "agents": agents,
            "work_items": work_item_responses,
            "tool_invocations": tool_invocations,
        }

    def list_messages(self, db: Session, run_id: int, user: User) -> list[TaskMessage]:
        """读取所选运行内的全部参与者会话消息。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        return db.query(TaskMessage).filter(TaskMessage.task_run_id == run.id).order_by(TaskMessage.id.asc()).all()

    def send_message(
        self, db: Session, run_id: int, body: TaskMessageCreate, *, actor: User,
    ) -> dict[str, Any]:
        """向主 Agent 或明确指定的 Worker 投递消息；目标更新形成新的运行版本。"""
        # 消息事件序号按运行行串行递增；请求去重也在同一锁内完成。
        run, task = self._get_run_for_write(db, run_id, actor, lock=True)
        prior = db.query(TaskMessage).filter(
            TaskMessage.task_run_id == run.id,
            TaskMessage.client_message_id == body.client_message_id,
        ).first()
        if prior is not None:
            if (
                prior.message_type != body.message_type
                or prior.content != sanitize_text(body.content)
                or (body.recipient_instance_id is not None and prior.agent_instance_id != body.recipient_instance_id)
            ):
                raise conflict("相同 client_message_id 已用于不同消息内容")
            return {"message": prior, "run": self._run_response(run), "created_run_id": prior.metadata_json.get("created_run_id")}

        if body.message_type in {"TEXT", "GOAL_UPDATE"}:
            recipient = self._agent_by_role(db, run.id, "MAIN")
            if body.recipient_instance_id is not None and body.recipient_instance_id != recipient.id:
                raise bad_request("任务级消息必须发送给任务主 Agent")
        else:
            if body.recipient_instance_id is None:
                raise bad_request("补充要求必须指定接收的 Worker")
            recipient = db.get(TaskAgentInstance, body.recipient_instance_id)
            if recipient is None or recipient.task_run_id != run.id or recipient.role not in {"API_WORKER", "UI_WORKER"}:
                raise not_found("指定的执行 Worker 不存在")
            accepting_work = db.query(TaskWorkItem.id).filter(
                TaskWorkItem.task_run_id == run.id,
                TaskWorkItem.agent_instance_id == recipient.id,
                TaskWorkItem.kind.in_(("EXECUTE_API", "EXECUTE_WEB")),
                TaskWorkItem.status.in_(("PENDING", "FAILED")),
            ).first()
            if accepting_work is None:
                raise conflict("指定的 Worker 当前没有可接收要求的执行工作")

        created_run_id = None
        message = TaskMessage(
            task_run_id=run.id,
            agent_instance_id=recipient.id,
            sender_type="USER",
            sender_user_id=actor.id,
            message_type=body.message_type,
            content=sanitize_text(body.content),
            metadata_json={},
            status="RECEIVED",
            client_message_id=body.client_message_id,
        )
        db.add(message)
        db.flush()

        if body.message_type == "GOAL_UPDATE":
            task.goal = sanitize_text(body.content).strip()
            if run.lease_owner and run.lease_expires_at and run.lease_expires_at > datetime.now():
                # 有在途操作时先请求其在安全边界收尾；新目标使用独立运行，不覆盖旧产物。
                run.status = "CANCEL_REQUESTED"
            else:
                run.status = "SUPERSEDED"
                db.query(TaskWorkItem).filter(
                    TaskWorkItem.task_run_id == run.id,
                    TaskWorkItem.status == "PENDING",
                ).update({TaskWorkItem.status: "CANCELLED"}, synchronize_session=False)
            next_number = int(db.query(func.max(TaskRun.run_number)).filter(TaskRun.task_id == task.id).scalar() or 0) + 1
            case = db.query(TestCase).filter(TestCase.id.in_(task.input_case_ids or [])).first()
            target_type = (
                "BUSINESS_ASSEMBLY" if task.task_mode == "BUSINESS_ASSEMBLY"
                else "WEB_AUTHORING" if task.task_mode == "WEB_AUTHORING"
                else "SECURITY" if task.security_assessment_json
                else (case.target_type if case is not None else "API")
            )
            new_run = self._create_run(db, task, actor, run_number=next_number, target_type=target_type)
            task.status = new_run.status
            created_run_id = new_run.id
            message.status = "PROCESSED"
            message.processed_at = datetime.now()
            message.metadata_json = {"created_run_id": new_run.id}
            self._append_event(db, run, "goal.updated", {"new_run_id": new_run.id}, actor_user_id=actor.id)
        elif recipient.role == "MAIN":
            # 普通消息由后台主 Agent 回复，HTTP 请求只持久化邮箱和工作项后立即返回。
            self._enqueue_work(
                db, run, recipient, work_key=f"chat:{message.id}", kind="CHAT",
                input_json={"message_id": message.id}, sequence=1000 + message.id,
            )
            self._append_event(db, run, "message.received", {"message_id": message.id, "role": recipient.role}, actor_user_id=actor.id)
        else:
            self._append_event(
                db, run, "message.received",
                {"message_id": message.id, "role": recipient.role, "agent_instance_id": recipient.id},
                actor_user_id=actor.id,
            )
        db.commit()
        db.refresh(message)
        return {"message": message, "run": self._run_response(run), "created_run_id": created_run_id}

    def create_command(
        self, db: Session, run_id: int, body: TaskCommandCreate, *, actor: User,
    ) -> TaskCommand:
        """持久化并原子应用幂等控制命令。"""
        if body.command_type != "APPROVE_PLAN" and body.security_risk_confirmed:
            raise bad_request("高风险安全用例确认只能用于方案确认命令")
        run, task = self._get_run_for_write(db, run_id, actor, lock=True)
        prior = db.query(TaskCommand).filter(
            TaskCommand.task_run_id == run.id,
            TaskCommand.idempotency_key == body.idempotency_key,
        ).first()
        if prior is not None:
            expected_payload = self._command_payload(body)
            if prior.command_type != body.command_type or prior.payload != expected_payload:
                raise conflict("相同 idempotency_key 已用于不同命令")
            if prior.status == "COMPLETED":
                return prior
            command = prior
        else:
            command = TaskCommand(
                task_run_id=run.id,
                requested_by=actor.id,
                command_type=body.command_type,
                idempotency_key=body.idempotency_key,
                payload=self._command_payload(body),
            )
            db.add(command)
            db.flush()

        if body.command_type == "APPROVE_PLAN":
            self._approve_plan(
                db, run, actor,
                security_risk_confirmed=body.security_risk_confirmed,
            )
        elif body.command_type == "PAUSE":
            self._pause(db, run, actor)
        elif body.command_type == "RESUME":
            self._resume(db, run, actor)
        elif body.command_type == "CANCEL":
            self._cancel(db, run, actor)
        elif body.command_type == "RETRY":
            self._retry(db, run, actor, body.work_item_id)

        command.status = "COMPLETED"
        command.response_json = {"status": run.status, "stage": run.stage}
        command.processed_at = datetime.now()
        self._sync_task_status(db, task, run)
        db.commit()
        db.refresh(command)
        return command

    def list_events(self, db: Session, run_id: int, user: User, *, after_seq: int, limit: int = 200) -> list[TaskEvent]:
        """按游标续读已提交事件；重复轮询不会改变运行状态。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        return (
            db.query(TaskEvent)
            .filter(TaskEvent.task_run_id == run.id, TaskEvent.event_seq > after_seq)
            .order_by(TaskEvent.event_seq.asc()).limit(min(max(limit, 1), 200)).all()
        )

    def list_resources(self, db: Session, run_id: int, user: User) -> list[dict[str, Any]]:
        """读取运行引用并附上可读名称；业务资源仍由原管理模块提供详情。"""
        run, task = self._get_run_for_read(db, run_id, user)
        refs = db.query(TaskResourceRef).filter(
            TaskResourceRef.task_run_id == run.id,
        ).order_by(TaskResourceRef.id.asc()).all()
        names = self._resource_display_names(db, refs)
        return [
            self._resource_response(
                ref,
                display_name=names.get((ref.resource_type, ref.resource_id)),
                task_id=task.id,
                task_title=task.title,
                run_number=run.run_number,
            )
            for ref in refs
        ]

    def find_tasks_for_resource(
        self, db: Session, user: User, *, resource_type: str, resource_id: str,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """按原业务资源反查其来源任务，供管理页显示双向关联。"""
        visible_ids = accessible_project_ids(db, user)
        query = (
            db.query(TaskResourceRef)
            .join(TaskRun, TaskRun.id == TaskResourceRef.task_run_id)
            .join(Task, Task.id == TaskRun.task_id)
            .filter(TaskResourceRef.resource_type == resource_type, TaskResourceRef.resource_id == resource_id)
        )
        if project_id is not None:
            self._get_project_for_read(db, project_id, user)
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        rows = query.add_columns(Task.id, Task.title, TaskRun.run_number).order_by(
            TaskResourceRef.created_at.desc(), TaskResourceRef.id.desc(),
        ).limit(50).all()
        refs = [row[0] for row in rows]
        names = self._resource_display_names(db, refs)
        return [
            self._resource_response(
                ref,
                display_name=names.get((ref.resource_type, ref.resource_id)),
                task_id=task_id,
                task_title=task_title,
                run_number=run_number,
            )
            for ref, task_id, task_title, run_number in rows
        ]

    @staticmethod
    def _resource_response(
        ref: TaskResourceRef, *, display_name: str | None,
        task_id: int, task_title: str, run_number: int,
    ) -> dict[str, Any]:
        """保留资源引用字段并补上其所属任务与可读名称。"""
        result = {column.name: getattr(ref, column.name) for column in ref.__table__.columns}
        result.update({
            "display_name": display_name,
            "task_id": task_id,
            "task_title": task_title,
            "run_number": run_number,
        })
        return result

    @staticmethod
    def _resource_display_names(db: Session, refs: list[TaskResourceRef]) -> dict[tuple[str, str], str]:
        """按业务类型批量读取引用名称，避免资源列表产生 N+1 查询。"""
        ids_by_type: dict[str, set[int]] = {}
        for ref in refs:
            try:
                ids_by_type.setdefault(ref.resource_type, set()).add(int(ref.resource_id))
            except (TypeError, ValueError):
                continue
        names: dict[tuple[str, str], str] = {}
        if ids := ids_by_type.get("TEST_CASE"):
            rows = db.query(TestCase.id, TestCase.name).filter(TestCase.id.in_(ids)).all()
            names.update({("TEST_CASE", str(row.id)): row.name for row in rows})
        if ids := ids_by_type.get("TEST_RUN"):
            from app.features.test_management.models.execution import TestRun

            rows = db.query(TestRun.id, TestRun.status).filter(TestRun.id.in_(ids)).all()
            names.update({("TEST_RUN", str(row.id)): f"测试运行 #{row.id} · {row.status}" for row in rows})
        if ids := ids_by_type.get("REPORT"):
            from app.features.reports.models.report import TestReport

            rows = db.query(TestReport.id, TestReport.report_no).filter(TestReport.id.in_(ids)).all()
            names.update({("REPORT", str(row.id)): row.report_no or f"测试报告 #{row.id}" for row in rows})
        if ids := ids_by_type.get("SECURITY_FINDING"):
            from app.features.security_testing.models import SecurityFinding

            rows = db.query(SecurityFinding.id, SecurityFinding.title).filter(SecurityFinding.id.in_(ids)).all()
            names.update({("SECURITY_FINDING", str(row.id)): f"疑似问题：{row.title}" for row in rows})
        if ids := ids_by_type.get("API"):
            from app.features.api_catalog.models.api_interface import ApiInterface

            rows = db.query(ApiInterface.id, ApiInterface.name, ApiInterface.method, ApiInterface.path).filter(ApiInterface.id.in_(ids)).all()
            names.update({
                ("API", str(row.id)): f"{row.method} {row.path} · {row.name}"
                for row in rows
            })
        if ids := ids_by_type.get("SECURITY_STRATEGY"):
            from app.features.security_testing.models import SecurityStrategy

            rows = db.query(SecurityStrategy.id, SecurityStrategy.name).filter(SecurityStrategy.id.in_(ids)).all()
            names.update({("SECURITY_STRATEGY", str(row.id)): row.name for row in rows})
        if ids := ids_by_type.get("WEB_AGENT_SESSION"):
            from app.features.web_ui.models import WebAgentSession

            rows = db.query(WebAgentSession.id).filter(WebAgentSession.id.in_(ids)).all()
            names.update({
                ("WEB_AGENT_SESSION", str(row.id)): f"受控浏览器会话 #{row.id}"
                for row in rows
            })
        return names

    # ------------------------------------------------------------------ 任务与运行构造

    def _create_run(
        self, db: Session, task: Task, actor: User, *, run_number: int, target_type: str,
        agent_bundle: dict[str, Any] | None = None,
    ) -> TaskRun:
        """创建隔离运行并固定 Agent、Skill、工具与模型快照；模型凭据不会进入快照。"""
        if task.agent_definition_id is not None and agent_bundle is None:
            agent_bundle = self._resolve_agent_profile(
                db,
                project_id=task.project_id,
                agent_definition_id=task.agent_definition_id,
                actor=actor,
                target_type="WEB" if target_type == "WEB_AUTHORING" else target_type,
            )
        model = agent_bundle["model"] if agent_bundle else self._resolve_authorized_model(db, task.project_id, actor)
        model_snapshot = self._model_snapshot(model)
        agent_snapshot = agent_bundle["snapshot"] if agent_bundle else None
        run = TaskRun(
            task_id=task.id,
            run_number=run_number,
            created_by=actor.id,
            status="QUEUED",
            stage="ASSEMBLY_QUEUED" if target_type == "BUSINESS_ASSEMBLY" else "PLANNING",
            goal_snapshot=task.goal,
            input_snapshot={
                "project_id": task.project_id,
                "environment_id": task.environment_id,
                "case_ids": list(task.input_case_ids or []),
                "target_type": target_type,
                "task_mode": task.task_mode,
                "web_authoring": dict(task.web_authoring_json) if task.web_authoring_json else None,
                "business_assembly": dict(task.business_assembly_json) if task.business_assembly_json else None,
                "security_assessment": dict(task.security_assessment_json) if task.security_assessment_json else None,
                # 仅供已经排队的历史运行恢复；新 API 不再接受 ZAP 扫描配置。
                "security_scan": dict(task.security_scan_json) if task.security_scan_json else None,
                "agent_definition": agent_snapshot,
            },
        )
        db.add(run)
        db.flush()
        if agent_snapshot and agent_snapshot.get("skills"):
            skill_keys = [item["key"] for item in agent_snapshot["skills"]]
            skill_ids = db.query(SkillDefinition.id, SkillDefinition.key).filter(SkillDefinition.key.in_(skill_keys)).all()
            db.add_all([
                SkillUsageEvent(
                    skill_definition_id=skill_id,
                    agent_definition_id=agent_snapshot["id"],
                    task_run_id=run.id,
                )
                for skill_id, _ in skill_ids
            ])

        if target_type == "BUSINESS_ASSEMBLY":
            roles = [
                ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
                ("ASSEMBLER", "业务组装 Agent", "QUEUED", []),
            ]
        elif target_type == "SECURITY":
            roles = [
                ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
                ("PLANNER", "Security Planner", "QUEUED", ["security-plan.preview"]),
                ("SECURITY_WORKER", "安全执行 Worker", "WAITING_APPROVAL", ["security-plan.confirm", "security-case.run"]),
            ]
        elif target_type == "WEB_AUTHORING":
            roles = [
                ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
                ("PLANNER", "Web 编写 Planner", "QUEUED", []),
                ("UI_WORKER", "任务内 UI Worker", "WAITING_APPROVAL", ["web-authoring.start", "web-authoring.turn", "web-case.draft"]),
            ]
        else:
            roles = [
                ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
                ("PLANNER", "Planner", "QUEUED", []),
                (("API_WORKER", "API Worker", "WAITING_APPROVAL", ["test-run.create"])
                 if target_type == "API" else
                 ("UI_WORKER", "UI Worker", "WAITING_APPROVAL", ["web-test-run.create"])),
            ]
        if target_type not in {"WEB_AUTHORING", "BUSINESS_ASSEMBLY"}:
            roles.extend([
                ("REVIEWER", "审阅 Agent", "WAITING_DEPENDENCY", ["report.review"]),
                ("REPORT_AGENT", "报告 Agent", "WAITING_DEPENDENCY", ["report.generate"]),
            ])
        agents: dict[str, TaskAgentInstance] = {}
        for role, name, state, tools in roles:
            role_tools = (
                list(tools) if target_type == "WEB_AUTHORING" and role == "UI_WORKER"
                else self._role_tools_for_agent(role, tools, agent_snapshot)
            )
            instance = TaskAgentInstance(
                task_run_id=run.id,
                instance_key=role.lower(),
                role=role,
                display_name=name,
                status=state,
                model_config_id=model.id if model else None,
                config_snapshot={
                    **model_snapshot,
                    "agent_version": agent_snapshot["version"] if agent_snapshot else None,
                    "agent_name": agent_snapshot["name"] if agent_snapshot else None,
                },
                skills_json=[skill["key"] for skill in agent_snapshot["skills"]] if agent_snapshot else [],
                tool_allowlist_json=role_tools,
            )
            db.add(instance)
            agents[role] = instance
        for child in (agent_snapshot or {}).get("child_agents", []):
            db.add(TaskAgentInstance(
                task_run_id=run.id,
                instance_key=f"child_agent:{child['id']}",
                role="SUB_AGENT",
                display_name=child["name"],
                status="WAITING_DEPENDENCY",
                model_config_id=child["model_config_id"],
                config_snapshot={"agent_version": child["version"], "agent_name": child["name"]},
                skills_json=[item["key"] for item in child.get("skills", [])],
                tool_allowlist_json=[],
            ))
        db.flush()

        if target_type == "BUSINESS_ASSEMBLY":
            initial_work = self._enqueue_work(
                db, run, agents["ASSEMBLER"], work_key="business-assembly:v1", kind="ASSEMBLE_BUSINESS",
                input_json={"document_version_ids": list((task.business_assembly_json or {}).get("document_version_ids") or [])},
                sequence=10,
            )
        else:
            initial_work = self._enqueue_work(
                db, run, agents["PLANNER"], work_key="plan:v1", kind="PLAN",
                input_json={
                    "case_ids": list(task.input_case_ids or []),
                    "environment_id": task.environment_id,
                    "target_type": target_type,
                    "security_assessment": dict(task.security_assessment_json) if task.security_assessment_json else None,
                    "web_authoring": dict(task.web_authoring_json) if task.web_authoring_json else None,
                }, sequence=10,
            )
        if target_type == "BUSINESS_ASSEMBLY":
            for version_id in (task.business_assembly_json or {}).get("document_version_ids", []):
                self._add_resource_ref(db, run, "INPUT", "KNOWLEDGE_DOCUMENT_VERSION", str(version_id), metadata={})
        for case_id in task.input_case_ids or []:
            self._add_resource_ref(db, run, "INPUT", "TEST_CASE", str(case_id), metadata={"confirmed": True})
        if task.environment_id is not None:
            self._add_resource_ref(db, run, "INPUT", "ENVIRONMENT", str(task.environment_id), metadata={})
        if task.security_assessment_json:
            api_ids = task.security_assessment_json.get("api_ids") or [task.security_assessment_json.get("api_id")]
            for api_id in dict.fromkeys(int(item) for item in api_ids if item):
                self._add_resource_ref(
                    db, run, "INPUT", "API", str(api_id),
                    metadata={"security_assessment": True},
                )
            for strategy_id in task.security_assessment_json.get("strategy_ids", []):
                self._add_resource_ref(
                    db, run, "INPUT", "SECURITY_STRATEGY", str(strategy_id), metadata={},
                )
            if task.security_assessment_json.get("web_session_id"):
                self._add_resource_ref(
                    db, run, "INPUT", "WEB_AGENT_SESSION",
                    str(task.security_assessment_json["web_session_id"]),
                    metadata={"passive_security_inspection": True},
                )
        self._append_event(
            db, run, "run.created",
            {"run_number": run.run_number, "plan_work_item_id": initial_work.id, "roles": [role[0] for role in roles] + ["SUB_AGENT"] * len((agent_snapshot or {}).get("child_agents", []))},
            actor_user_id=actor.id,
        )
        return run

    @staticmethod
    def _role_tools_for_agent(role: str, baseline: list[str], snapshot: dict[str, Any] | None) -> list[str]:
        """将平台 Agent 工具键收敛到现有任务节点真实实现的能力名称。"""
        if snapshot is None or role == "MAIN":
            return baseline
        grants = set(snapshot.get("tool_keys") or [])
        bindings = {
            "PLANNER": {
                "api_catalog.search_api": "api-catalog.search",
                "test_asset.get_existing_cases": "test-asset.read",
                "security.preview_plan": "security-plan.preview",
                "security.list_strategies": "security-strategy.read",
                "security.read_api_context": "security-context.read",
                "security.read_findings": "security-findings.read",
                "security.inspect_web_session": "security-web.inspect",
            },
            "API_WORKER": {"execution.create_test_run": "test-run.create"},
            "UI_WORKER": {"execution.create_test_run": "web-test-run.create"},
            "SECURITY_WORKER": {
                "security.preview_plan": "security-plan.preview",
                "security.confirm_plan": "security-plan.confirm",
                "security.execute_cases": "security-case.run",
            },
            "REPORT_AGENT": {
                "execution.get_test_run": "test-run.read",
                "report.generate": "report.generate",
            },
            "REVIEWER": {
                "execution.get_test_run": "test-run.read",
                "report.review": "report.review",
            },
        }
        selected = bindings.get(role, {})
        allowed = {runtime_name for key, runtime_name in selected.items() if key in grants}
        if role == "PLANNER":
            allowed.update(key for key in grants if key.startswith("mcp:"))
        return sorted(allowed)

    @staticmethod
    def _resolve_authorized_model(
        db: Session, project_id: int, actor: User, *, requested_model_id: int | None = None,
    ) -> ModelConfiguration:
        """按现有组织智能体开关与模型白名单选择任务模型。"""
        project = db.get(Project, project_id)
        if project is None:
            raise not_found("项目不存在")
        query = db.query(ModelConfiguration).filter(ModelConfiguration.is_enabled.is_(True))
        if is_platform_admin(actor):
            # 平台管理员沿用全平台模型管理权限，优先使用现有默认模型。
            if requested_model_id is not None:
                model = query.filter(ModelConfiguration.id == requested_model_id).first()
                if model is None:
                    raise bad_request("Agent 绑定的模型配置不存在或已停用")
                return model
            model = query.order_by(ModelConfiguration.is_default.desc(), ModelConfiguration.sort_order.asc(), ModelConfiguration.id.asc()).first()
        else:
            if project.organization_id is None:
                raise forbidden("当前项目未配置组织级智能体模型授权")
            membership = db.query(OrganizationMember).filter(
                OrganizationMember.organization_id == project.organization_id,
                OrganizationMember.user_id == actor.id,
            ).first()
            if membership is None or not membership.agent_enabled:
                raise forbidden("当前组织未向你开放智能体能力")
            allowed_ids = [str(item) for item in (membership.allowed_model_ids or [])]
            if not allowed_ids:
                raise forbidden("当前组织未向你分配智能体模型")
            if requested_model_id is not None:
                model = query.filter(
                    ModelConfiguration.id == requested_model_id,
                    ModelConfiguration.domain_id.in_(allowed_ids),
                ).first()
                if model is None:
                    raise forbidden("Agent 绑定的模型未获当前组织授权")
                return model
            model = query.filter(ModelConfiguration.domain_id.in_(allowed_ids)).order_by(
                ModelConfiguration.is_default.desc(), ModelConfiguration.sort_order.asc(), ModelConfiguration.id.asc(),
            ).first()
        if model is None:
            raise bad_request("没有可用的智能体模型配置")
        return model

    @staticmethod
    def assert_agent_model_access(
        db: Session, project_id: int, actor: User, model_config_id: int | None,
    ) -> ModelConfiguration:
        """每轮后台模型调用前复核配置启用态与发起人的当前组织授权。"""
        if model_config_id is None:
            raise RuntimeError("任务未绑定模型配置，已停止智能体调用")
        model = db.get(ModelConfiguration, model_config_id)
        if model is None or not model.is_enabled:
            raise RuntimeError("任务模型配置已删除或停用，已停止智能体调用")
        project = db.get(Project, project_id)
        if project is None:
            raise RuntimeError("任务项目不存在")
        if is_platform_admin(actor):
            return model
        if project.organization_id is None:
            raise RuntimeError("任务项目未配置组织级智能体模型授权")
        membership = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == actor.id,
        ).first()
        allowed_ids = {str(item) for item in (membership.allowed_model_ids or [])} if membership else set()
        if membership is None or not membership.agent_enabled or model.domain_id not in allowed_ids:
            raise RuntimeError("任务发起人的智能体模型授权已撤销，已停止新的智能体调用")
        return model

    @staticmethod
    def assert_agent_runtime_access(db: Session, task: Task, run: TaskRun, actor: User) -> None:
        """每个工作项执行前复核 Agent 启用状态与当前组织智能体开关。"""
        snapshot = (run.input_snapshot or {}).get("agent_definition") or {}
        definition_id = snapshot.get("id")
        if definition_id is None:
            return
        definition = db.get(AgentDefinition, int(definition_id))
        if definition is None or not definition.is_enabled:
            raise RuntimeError("任务所选 Agent 已删除或停用，已阻止新的 Agent 工作项")
        child_ids = [int(item.get("id")) for item in snapshot.get("child_agents", []) if item.get("id") is not None]
        if child_ids:
            enabled_child_ids = {
                row.id for row in db.query(AgentDefinition).filter(
                    AgentDefinition.id.in_(child_ids), AgentDefinition.is_enabled.is_(True),
                ).all()
            }
            if enabled_child_ids != set(child_ids):
                raise RuntimeError("任务所选子 Agent 已删除或停用，已阻止新的子节点执行")
        project = db.get(Project, task.project_id)
        if project is None:
            raise RuntimeError("任务项目不存在")
        if is_platform_admin(actor):
            return
        if project.organization_id is None:
            raise RuntimeError("任务项目未配置组织级智能体授权")
        membership = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == actor.id,
        ).first()
        if membership is None or not membership.agent_enabled:
            raise RuntimeError("任务发起人的组织智能体开关已关闭，已阻止新的 Agent 工作项")

    @staticmethod
    def _model_snapshot(model: ModelConfiguration | None) -> dict[str, Any]:
        """只快照非敏感模型身份与调用参数；密钥仍由现有模型配置加密管理。"""
        if model is None:
            return {"binding": "default", "available": False}
        return {
            "binding": "explicit",
            "model_config_id": model.id,
            "domain_id": model.domain_id,
            "label": model.label,
            "provider": model.provider,
            "model_name": model.model_name,
            "temperature": model.temperature,
            "max_tokens": model.max_tokens,
            "timeout": model.timeout,
            "fallback_model_config_ids": list(model.fallback_model_ids or []),
        }

    @staticmethod
    def _enqueue_work(
        db: Session, run: TaskRun, agent: TaskAgentInstance | None, *, work_key: str,
        kind: str, input_json: dict[str, Any], sequence: int,
    ) -> TaskWorkItem:
        """按运行内键去重登记工作项，重复 HTTP 命令不会复制任务副作用。"""
        existing = db.query(TaskWorkItem).filter(
            TaskWorkItem.task_run_id == run.id, TaskWorkItem.work_key == work_key,
        ).first()
        if existing is not None:
            return existing
        work = TaskWorkItem(
            task_run_id=run.id,
            agent_instance_id=agent.id if agent else None,
            work_key=work_key,
            kind=kind,
            sequence=sequence,
            status="PENDING",
            input_json=sanitize_context(input_json),
            idempotency_key=f"run:{run.id}:{work_key}",
        )
        db.add(work)
        db.flush()
        return work

    # ------------------------------------------------------------------ 命令与状态转换

    def _approve_plan(
        self, db: Session, run: TaskRun, actor: User, *, security_risk_confirmed: bool = False,
    ) -> None:
        """人工确认持久化方案后，只派发其固定范围内的执行工作。"""
        if run.status != "WAITING_CONFIRMATION" or run.stage != "PLAN_REVIEW":
            raise conflict("当前运行没有待确认的测试方案")
        plan = db.query(TaskPlan).filter(TaskPlan.task_run_id == run.id, TaskPlan.version == run.current_plan_version).with_for_update().first()
        if plan is None or plan.status != "PROPOSED":
            raise conflict("当前测试方案已被处理")
        target_type = run.input_snapshot.get("target_type", "API")
        project_id = int(run.input_snapshot["project_id"])
        plan_work = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.kind == "PLAN").order_by(TaskWorkItem.id.desc()).first()
        if target_type == "WEB_AUTHORING":
            if security_risk_confirmed:
                raise bad_request("交互式 Web 编写不接受安全风险确认参数")
            selection = run.input_snapshot.get("web_authoring") or {}
            if run.input_snapshot.get("task_mode") != "WEB_AUTHORING" or not selection:
                raise conflict("Web 编写任务缺少服务端记录的会话范围")
            worker_agent = self._agent_by_role(db, run.id, "UI_WORKER")
            work = self._enqueue_work(
                db, run, worker_agent, work_key=f"web-authoring-start:v{plan.version}",
                kind="EXECUTE_WEB_AUTHORING",
                input_json={
                    "plan_id": plan.id,
                    "environment_id": run.input_snapshot.get("environment_id"),
                    "web_authoring": selection,
                }, sequence=20,
            )
            run.stage = "WEB_AUTHORING_START"
            worker_agent.status = "QUEUED"
        elif target_type == "SECURITY":
            selection = run.input_snapshot.get("security_assessment") or {}
            from app.features.api_catalog.models.api_interface import ApiInterface

            api_ids = list(dict.fromkeys(
                int(item) for item in (selection.get("api_ids") or [selection.get("api_id")]) if item
            ))
            api_rows = db.query(ApiInterface).filter(
                ApiInterface.id.in_(api_ids or [-1]), ApiInterface.project_id == project_id,
            ).all()
            if len(api_rows) != len(api_ids) or any(item.status != "ACTIVE" for item in api_rows):
                raise conflict("部分安全评估目标 API 已删除、停用或不属于当前项目")
            preview = plan.plan_json.get("security_assessment_preview") or {}
            preview_plans = list(preview.get("plans") or [])
            if not selection or not preview_plans or set(preview.get("api_ids") or []) != set(api_ids):
                raise conflict("安全评估方案缺少已登记策略的预览结果")
            if preview.get("truncated"):
                raise conflict("安全计划超过单次预览上限，请减少策略后重新规划")

            from app.features.security_testing.models import SecurityCase, SecurityPlan
            from app.features.security_testing.services.case_service import SecurityCaseService
            from app.features.agent.tools.security_tool import confirm_plan

            confirmed_plan_ids: list[int] = []
            accepted_indexes_by_plan: dict[int, list[int]] = {}
            runnable_item_count = 0
            runnable_high_risk_count = 0
            for api_plan in preview_plans:
                api_id = int((api_plan.get("api") or {}).get("id") or 0)
                plan_preview = api_plan.get("plan") or {}
                plan_items = list(plan_preview.get("items") or [])
                if api_id not in api_ids:
                    raise conflict("安全计划中的 API 范围无效")
                if plan_preview.get("truncated") or int(plan_preview.get("estimated_count") or 0) > len(plan_items):
                    raise conflict("单个 API 的安全计划超过预览上限，请减少策略后重新规划")
                runnable_items = [item for item in plan_items if not item.get("blocked_reason")]
                runnable_item_count += len(runnable_items)
                runnable_high_risk_count += sum(bool(item.get("confirmation_required")) for item in runnable_items)
                accepted_items = [
                    item for item in runnable_items
                    if security_risk_confirmed or not item.get("confirmation_required")
                ]
                plan_id = int(plan_preview.get("plan_id") or 0)
                security_plan = db.get(SecurityPlan, plan_id)
                if security_plan is None or security_plan.project_id != project_id or security_plan.api_id != api_id:
                    raise conflict("安全计划已不存在或目标 API 不匹配")
                expected_strategy_ids = set(int(item) for item in selection.get("strategy_ids", []))
                if set(int(item) for item in (security_plan.strategy_ids or [])) != expected_strategy_ids:
                    raise conflict("安全计划策略与任务批准范围不一致")
                if security_plan.status == "DRAFT":
                    if accepted_items:
                        indexes = [int(item["index"]) for item in accepted_items]
                        confirm_plan(db, security_plan.id, actor, accepted_item_indexes=indexes)
                        accepted_indexes_by_plan[security_plan.id] = indexes
                        confirmed_plan_ids.append(security_plan.id)
                elif security_plan.status == "CONFIRMED":
                    accepted_indexes_by_plan[security_plan.id] = [int(item["index"]) for item in accepted_items]
                    confirmed_plan_ids.append(security_plan.id)
                else:
                    raise conflict("安全计划已被丢弃或不能确认")

            if runnable_high_risk_count and not security_risk_confirmed and runnable_item_count == runnable_high_risk_count:
                raise bad_request("当前批次只有高风险变异，请在确认方案时显式授权")
            if not confirmed_plan_ids:
                raise bad_request("当前安全计划没有可执行项")

            security_cases = db.query(SecurityCase).filter(
                SecurityCase.plan_id.in_(confirmed_plan_ids),
                SecurityCase.test_case_id.in_(db.query(TestCase.id).filter(TestCase.project_id == project_id)),
            ).all()
            if security_risk_confirmed:
                for security_case in security_cases:
                    if security_case.confirmation_required and not (security_case.confirmed_by and security_case.confirmed_at):
                        SecurityCaseService.confirm_risk(db, security_case.id, actor=actor)
            enabled_case_ids = {
                row.id for row in db.query(TestCase).filter(
                    TestCase.id.in_([item.test_case_id for item in security_cases]),
                    TestCase.project_id == project_id,
                    TestCase.enabled.is_(True),
                    TestCase.status == "ACTIVE",
                ).all()
            }
            eligible_security_case_ids = [
                row.id for row in security_cases
                if row.test_case_id in enabled_case_ids
                and (not row.confirmation_required or bool(row.confirmed_by and row.confirmed_at))
            ]
            if not eligible_security_case_ids:
                raise bad_request("确认后没有可执行的安全用例")

            security_agent = self._agent_by_role(db, run.id, "SECURITY_WORKER")
            if security_agent is None:
                raise conflict("安全执行 Worker 实例不存在")
            for security_plan_id in confirmed_plan_ids:
                invocation_key = f"security-plan-confirm:{security_plan_id}"
                invocation = db.query(TaskToolInvocation).filter(
                    TaskToolInvocation.task_run_id == run.id,
                    TaskToolInvocation.invocation_key == invocation_key,
                ).first()
                if invocation is None:
                    db.add(TaskToolInvocation(
                        task_run_id=run.id,
                        work_item_id=plan_work.id if plan_work else None,
                        agent_instance_id=security_agent.id,
                        invocation_key=invocation_key,
                        tool_name="security.confirm_plan",
                        status="SUCCEEDED",
                        input_json={
                            "security_plan_id": security_plan_id,
                            "accepted_indexes": accepted_indexes_by_plan.get(security_plan_id, []),
                            "confirmed_by": actor.id,
                        },
                        result_json={
                            "security_case_ids": [item.id for item in security_cases if item.plan_id == security_plan_id],
                        },
                        finished_at=datetime.now(),
                    ))
            work = self._enqueue_work(
                db, run, security_agent, work_key=f"security-execution:v{plan.version}", kind="EXECUTE_SECURITY",
                input_json={
                    "security_plan_ids": confirmed_plan_ids,
                    "security_case_ids": eligible_security_case_ids,
                    "environment_id": run.input_snapshot.get("environment_id"),
                    "api_ids": api_ids,
                },
                sequence=20,
            )
            run.input_snapshot = {
                **dict(run.input_snapshot or {}),
                "security_assessment_approval": {
                    "confirmed_by": actor.id,
                    "confirmed_at": datetime.now().isoformat(),
                    "risk_confirmed": bool(security_risk_confirmed),
                    "security_plan_ids": confirmed_plan_ids,
                },
            }
            run.stage = "SECURITY_EXECUTION"
            security_agent.status = "QUEUED"
        else:
            if security_risk_confirmed:
                raise bad_request("当前任务没有待确认的高风险安全用例")
            if run.input_snapshot.get("security_scan"):
                raise conflict("历史 ZAP 任务已停用；请创建自研安全评估任务")
            worker_role = "API_WORKER" if target_type == "API" else "UI_WORKER"
            worker_kind = "EXECUTE_API" if target_type == "API" else "EXECUTE_WEB"
            worker_agent = self._agent_by_role(db, run.id, worker_role)
            work = self._enqueue_work(
                db, run, worker_agent, work_key=f"{target_type.lower()}-execution:v{plan.version}", kind=worker_kind,
                input_json={"plan_id": plan.id, "case_ids": list(run.input_snapshot.get("case_ids", [])), "environment_id": run.input_snapshot.get("environment_id"), "target_type": target_type},
                sequence=20,
            )
            run.stage = "API_EXECUTION" if target_type == "API" else "WEB_EXECUTION"
            worker_agent.status = "QUEUED"
        if plan_work is not None:
            from app.features.tasks.models import TaskWorkItemDependency
            db.add(TaskWorkItemDependency(work_item_id=work.id, depends_on_id=plan_work.id))
        plan.status = "ACCEPTED"
        plan.accepted_at = datetime.now()
        run.status = "QUEUED"
        self._append_event(
            db, run, "plan.accepted",
            {"plan_id": plan.id, "work_item_id": work.id, "security_assessment": target_type == "SECURITY"},
            actor_user_id=actor.id,
        )

    @staticmethod
    def _command_payload(body: TaskCommandCreate) -> dict[str, Any]:
        """构造幂等比较用的命令内容，批准说明经脱敏后写入审计载荷。"""
        payload: dict[str, Any] = {}
        if body.work_item_id:
            payload["work_item_id"] = body.work_item_id
        if body.security_risk_confirmed:
            payload["security_risk_confirmed"] = True
        return payload

    def _pause(self, db: Session, run: TaskRun, actor: User) -> None:
        """运行中的暂停在当前工作项安全边界生效，待确认状态可立即暂停。"""
        if run.status in RUN_TERMINAL_STATUSES or run.status in RUN_PAUSE_STATUSES:
            raise conflict("当前运行不能重复暂停")
        run.status = "PAUSE_REQUESTED" if run.status == "RUNNING" else "PAUSED"
        if run.input_snapshot.get("target_type") == "WEB_AUTHORING" and run.status == "PAUSED":
            worker = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
            if worker is not None:
                worker.status = "PAUSED"
        self._append_event(db, run, "run.pause_requested", {"effective_at": "安全边界"}, actor_user_id=actor.id)

    def _resume(self, db: Session, run: TaskRun, actor: User) -> None:
        """恢复暂停运行；方案仍待审阅时回到确认态，不越过人工确认。"""
        if run.status != "PAUSED":
            raise conflict("当前运行未暂停")
        has_pending = db.query(TaskWorkItem.id).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING").first()
        if run.stage == "PLAN_REVIEW":
            run.status = "WAITING_CONFIRMATION"
        elif has_pending:
            if run.stage == "WAITING_MODEL":
                # 管理员修复模型路由后显式恢复，才刷新冻结快照并开启新一轮有限重试额度。
                agents = db.query(TaskAgentInstance).filter(TaskAgentInstance.task_run_id == run.id).all()
                for agent in agents:
                    model_id = agent.model_config_id or (agent.config_snapshot or {}).get("model_config_id")
                    model = db.get(ModelConfiguration, model_id) if model_id else None
                    if model is not None:
                        agent.config_snapshot = self._model_snapshot(model)
                pending = db.query(TaskWorkItem).filter(
                    TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING",
                ).all()
                for work in pending:
                    work.max_attempts = max(work.max_attempts, work.attempt_count + 3)
                    work.available_at = None
                    work.error_code = None
                    work.error_message = None
                run.error_code = None
                run.error_message = None
                run.stage = "MODEL_RETRY"
            run.status = "QUEUED"
        elif run.input_snapshot.get("target_type") == "WEB_AUTHORING" and run.stage in {
            "WEB_AUTHORING", "WEB_STEP_REVIEW", "WEB_SESSION_CLOSED", "WEB_DRAFT_REVIEW",
        }:
            run.status = "WAITING_CONFIRMATION"
            worker = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
            if worker is not None:
                worker.status = "ACTIVE"
        else:
            raise conflict("当前运行没有可继续的工作项")
        self._append_event(db, run, "run.resumed", {"status": run.status}, actor_user_id=actor.id)

    def _cancel(self, db: Session, run: TaskRun, actor: User) -> None:
        """取消在途工作采用协作式标记；未领取工作立即终止。"""
        if run.status in RUN_TERMINAL_STATUSES or run.status == "CANCEL_REQUESTED":
            raise conflict("当前运行不能重复取消")
        if run.status == "RUNNING":
            run.status = "CANCEL_REQUESTED"
        else:
            run.status = "CANCELLED"
            run.finished_at = datetime.now()
            db.query(TaskWorkItem).filter(
                TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING",
            ).update({TaskWorkItem.status: "CANCELLED"}, synchronize_session=False)
        if run.input_snapshot.get("target_type") == "WEB_AUTHORING":
            from app.features.web_ui.models import WebAgentSession
            from app.features.web_ui.runtime.session_manager import registry

            sessions = db.query(WebAgentSession).filter(
                WebAgentSession.task_run_id == run.id,
                WebAgentSession.status == "ACTIVE",
            ).all()
            for session in sessions:
                registry.close_session(session.id)
                session.status = "CLOSED"
                session.closed_at = datetime.now()
            worker = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
            if worker is not None and run.status == "CANCELLED":
                worker.status = "CANCELLED"
            if run.status == "CANCELLED":
                run.stage = "CANCELLED"
        # 历史 ZAP Job 可能仍在外部运行；只为旧任务登记取消请求，不再启动扫描器。
        from app.features.security_testing.zap.contracts import JOB_TERMINAL_STATUSES
        from app.features.security_testing.zap.models.job import SecurityScanJob
        from app.features.security_testing.zap.services import job_service

        scan_refs = db.query(TaskResourceRef).filter(
            TaskResourceRef.task_run_id == run.id,
            TaskResourceRef.resource_type == "SECURITY_SCAN_JOB",
        ).all()
        for ref in scan_refs:
            try:
                scan_job = db.get(SecurityScanJob, int(ref.resource_id))
            except (TypeError, ValueError):
                scan_job = None
            if scan_job is not None and scan_job.status not in JOB_TERMINAL_STATUSES:
                job_service.cancel(db, scan_job.project_id, actor, scan_job.id)
        self._append_event(db, run, "run.cancel_requested", {"status": run.status}, actor_user_id=actor.id)

    def _retry(self, db: Session, run: TaskRun, actor: User, work_item_id: int | None) -> None:
        """仅重试明确失败且副作用可判定的工作项；未知回执必须人工核对。"""
        if work_item_id is None:
            raise bad_request("重试必须指定失败的工作项")
        if run.status not in RETRYABLE_RUN_STATUSES:
            raise conflict("当前运行状态不支持重试")
        work = db.query(TaskWorkItem).filter(
            TaskWorkItem.id == work_item_id, TaskWorkItem.task_run_id == run.id,
        ).with_for_update().first()
        if work is None or work.status != "FAILED":
            raise not_found("可重试的失败工作项不存在")
        invocations = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.work_item_id == work.id,
        ).all()
        block_reason = self._retry_block_reason(run, work, invocations)
        if block_reason:
            raise conflict(block_reason)
        work.status = "PENDING"
        work.available_at = None
        work.error_code = None
        work.error_message = None
        work.finished_at = None
        run.status = "QUEUED"
        if work.kind == "EXECUTE_SECURITY":
            run.stage = "SECURITY_EXECUTION"
        run.error_code = None
        run.error_message = None
        self._append_event(db, run, "work_item.retry_queued", {"work_item_id": work.id}, actor_user_id=actor.id)

    def _retry_block_reason(
        self,
        run: TaskRun,
        work: TaskWorkItem,
        invocations: list[TaskToolInvocation],
    ) -> str | None:
        """返回工作项当前不能重试的原因；返回 None 表示服务端允许重试。"""
        if run.status not in RETRYABLE_RUN_STATUSES:
            return "当前运行状态不支持重试"
        if work.status != "FAILED":
            return "只有失败的工作项可以重试"
        if work.kind in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY"} and any(
            invocation.status in UNCERTAIN_INVOCATION_STATUSES for invocation in invocations
        ):
            return "测试执行回执状态不明，请先从执行中心核对，不能自动重放"
        if work.kind == "SECURITY_SCAN":
            return "历史 ZAP 工作项已停用，不能重试"
        if work.kind not in RETRYABLE_WORK_ITEM_KINDS:
            return "该类工作项尚未接入安全重试"
        if work.attempt_count >= work.max_attempts:
            return "工作项已达到最大重试次数"
        return None

    # ------------------------------------------------------------------ 权限、事件与响应组装

    def _get_project_for_read(self, db: Session, project_id: int, user: User) -> Project:
        """读取项目并按 viewer+ 校验；不可见与不存在统一 404。"""
        project = db.get(Project, project_id)
        if project is None or not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
            raise not_found("项目不存在")
        return project

    def _get_project_for_write(self, db: Session, project_id: int, user: User) -> Project:
        """写任务至少需要项目 member；项目不可见仍统一 404。"""
        project = self._get_project_for_read(db, project_id, user)
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_MEMBER):
            raise forbidden("需要项目成员权限")
        return project

    def _get_task_for_read(self, db: Session, task_id: int, user: User) -> Task:
        """读取任务并回查所属项目权限。"""
        task = db.get(Task, task_id)
        if task is None:
            raise not_found("任务不存在")
        self._get_project_for_read(db, task.project_id, user)
        return task

    def _get_run_for_read(self, db: Session, run_id: int, user: User) -> tuple[TaskRun, Task]:
        """读取运行并校验所属任务项目权限。"""
        run = db.get(TaskRun, run_id)
        if run is None:
            raise not_found("任务运行不存在")
        task = self._get_task_for_read(db, run.task_id, user)
        return run, task

    def _get_run_for_write(
        self, db: Session, run_id: int, actor: User, *, lock: bool = False,
    ) -> tuple[TaskRun, Task]:
        """读取可写运行；状态变更调用方可要求行锁避免并发命令覆盖。"""
        query = db.query(TaskRun).filter(TaskRun.id == run_id)
        if lock:
            query = query.with_for_update()
        run = query.first()
        if run is None:
            raise not_found("任务运行不存在")
        task = db.get(Task, run.task_id)
        if task is None:
            raise not_found("任务不存在")
        self._get_project_for_write(db, task.project_id, actor)
        return run, task

    @staticmethod
    def _agent_by_role(db: Session, run_id: int, role: str) -> TaskAgentInstance:
        """取运行内固定角色实例；不存在时按数据完整性错误处理。"""
        agent = db.query(TaskAgentInstance).filter(
            TaskAgentInstance.task_run_id == run_id, TaskAgentInstance.role == role,
        ).first()
        if agent is None:
            raise not_found("任务参与者不存在")
        return agent

    @staticmethod
    def _append_event(
        db: Session, run: TaskRun, event_type: str, payload: dict[str, Any], *,
        actor_user_id: int | None = None, agent_instance_id: int | None = None,
    ) -> TaskEvent:
        """同事务递增运行游标并记录实际状态变化。"""
        run.event_seq += 1
        event = TaskEvent(
            task_run_id=run.id,
            event_seq=run.event_seq,
            event_type=event_type,
            actor_user_id=actor_user_id,
            agent_instance_id=agent_instance_id,
            payload=sanitize_context(payload),
        )
        db.add(event)
        notification = TASK_NOTIFICATION_EVENTS.get(event_type)
        if notification:
            task = db.get(Task, run.task_id)
            if task is not None and task.created_by is not None:
                from app.models.notification import Notification

                notification_type, title = notification
                db.add(Notification(
                    user_id=task.created_by,
                    project_id=task.project_id,
                    event_type=notification_type,
                    title=title,
                    body=task.title,
                    payload={"actor": actor_user_id, "detail": {"task_id": task.id, "run_id": run.id}},
                    is_read=False,
                ))
        return event

    @staticmethod
    def _add_resource_ref(
        db: Session, run: TaskRun, direction: str, resource_type: str, resource_id: str,
        *, agent_instance_id: int | None = None, version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskResourceRef:
        """按运行、方向、类型和资源 ID 去重引用，业务主表仍保持唯一事实源。"""
        existing = db.query(TaskResourceRef).filter(
            TaskResourceRef.task_run_id == run.id,
            TaskResourceRef.direction == direction,
            TaskResourceRef.resource_type == resource_type,
            TaskResourceRef.resource_id == resource_id,
        ).first()
        if existing is not None:
            return existing
        ref = TaskResourceRef(
            task_run_id=run.id,
            agent_instance_id=agent_instance_id,
            direction=direction,
            resource_type=resource_type,
            resource_id=resource_id,
            version=version,
            metadata_json=sanitize_context({**(metadata or {}), "task_id": run.task_id}),
        )
        db.add(ref)
        return ref

    @staticmethod
    def _sync_task_status(db: Session, task: Task, run: TaskRun) -> None:
        """只让最新 run 更新任务列表状态，旧运行收尾不覆盖新目标。"""
        latest_id = db.query(TaskRun.id).filter(TaskRun.task_id == task.id).order_by(TaskRun.run_number.desc()).limit(1).scalar()
        if latest_id == run.id:
            task.status = run.status

    def _task_detail(self, db: Session, task: Task) -> dict[str, Any]:
        """组装任务与最新运行响应。"""
        latest = db.query(TaskRun).filter(TaskRun.task_id == task.id).order_by(TaskRun.run_number.desc()).first()
        return self._task_response(task, latest)

    @staticmethod
    def _task_response(task: Task, run: TaskRun | None) -> dict[str, Any]:
        """生成稳定任务 DTO，避免响应 ORM 关系或秘密配置。"""
        return {
            "id": task.id,
            "project_id": task.project_id,
            "created_by": task.created_by,
            "title": task.title,
            "goal": task.goal,
            "environment_id": task.environment_id,
            "input_case_ids": task.input_case_ids or [],
            "status": task.status,
            "task_mode": task.task_mode,
            "archived": task.archived,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "latest_run": TaskService._run_response(run) if run is not None else None,
        }

    @staticmethod
    def _run_response(run: TaskRun) -> dict[str, Any]:
        """保留可审计的 Agent 版本信息，但不把内部指令与 Skill 正文回传给项目成员。"""
        input_snapshot = dict(run.input_snapshot or {})
        agent_snapshot = input_snapshot.get("agent_definition")
        if agent_snapshot:
            input_snapshot["agent_definition"] = {
                "name": agent_snapshot.get("name"),
                "version": agent_snapshot.get("version"),
                "workflow_template": agent_snapshot.get("workflow_template"),
                "tool_keys": list(agent_snapshot.get("tool_keys") or []),
                "child_agent_ids": list(agent_snapshot.get("child_agent_ids") or []),
                "child_agents": [
                    {"id": child.get("id"), "name": child.get("name"), "version": child.get("version")}
                    for child in (agent_snapshot.get("child_agents") or [])
                ],
                "mcp_tools": [
                    {"key": tool.get("key"), "server_name": tool.get("server_name"), "tool_name": tool.get("tool_name")}
                    for tool in (agent_snapshot.get("mcp_tools") or [])
                ],
                "skills": [
                    {"key": skill.get("key"), "name": skill.get("name"), "version": skill.get("version")}
                    for skill in (agent_snapshot.get("skills") or [])
                ],
            }
        return {
            "id": run.id,
            "task_id": run.task_id,
            "run_number": run.run_number,
            "status": run.status,
            "stage": run.stage,
            "goal_snapshot": run.goal_snapshot,
            "input_snapshot": input_snapshot,
            "current_plan_version": run.current_plan_version,
            "event_seq": run.event_seq,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "created_at": run.created_at,
        }

    @staticmethod
    def _latest_runs(db: Session, task_ids: list[int]) -> dict[int, TaskRun]:
        """数据库侧聚合每个任务的最新运行，避免读取并遍历完整历史。"""
        if not task_ids:
            return {}
        latest = db.query(TaskRun.task_id, func.max(TaskRun.run_number).label("run_number")).filter(
            TaskRun.task_id.in_(task_ids)
        ).group_by(TaskRun.task_id).subquery()
        return {
            run.task_id: run for run in db.query(TaskRun).join(
                latest, and_(TaskRun.task_id == latest.c.task_id, TaskRun.run_number == latest.c.run_number)
            ).all()
        }
