"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import Task, TaskCommand, TaskEvent, TaskMessage, TaskRun, TaskTemplate
from app.orchestration.tasks.schemas import TaskCommandCreate, TaskCreate, TaskMessageCreate
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import ModelConfiguration
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict, not_found
from app.core.security.sanitizer import sanitize_text
from app.orchestration.tasks.services.access import TaskAccessService
from app.orchestration.tasks.services.message_service import TaskMessageService
from app.orchestration.tasks.services.query_service import TaskQueryService
from app.orchestration.tasks.services.resource_service import TaskResourceService
from app.orchestration.tasks.services.state_service import append_event
from app.orchestration.tasks.services.assembly_service import assert_agent_model_access
from app.orchestration.tasks.services.assembly_service import assert_agent_runtime_access
from app.orchestration.tasks.services.command_service import create_command
from app.orchestration.tasks.services.run_service import create_run
from app.orchestration.tasks.services.state_service import enqueue_work
from app.orchestration.tasks.services.assembly_service import list_available_agents
from app.orchestration.tasks.services.assembly_service import resolve_agent_profile
from app.orchestration.tasks.schemas import VerificationTaskRequest


class TaskService:
    """稳定领域门面；各资源由唯一实现持有。"""

    def create_task(
        self, db: Session, project_id: int, body: TaskCreate, *, actor: User,
        _verification_source: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """校验已确认的测试资产或安全评估范围，创建首个运行与对应 Worker。"""
        project = TaskAccessService.get_project_for_write(db, project_id, actor)
        case_ids = list(dict.fromkeys(body.case_ids))
        security_assessment = body.security_assessment.model_dump() if body.security_assessment else None
        if security_assessment is not None:
            security_assessment["api_ids"] = list(dict.fromkeys(security_assessment.get("api_ids") or []))
            security_assessment["strategy_ids"] = list(dict.fromkeys(security_assessment.get("strategy_ids") or []))
        web_authoring = body.web_authoring.model_dump() if body.web_authoring else None
        goal = sanitize_text(body.goal).strip()
        title = sanitize_text(body.title or "").strip() or goal[:80]
        if (body.template_id is None) != (body.template_version is None):
            raise bad_request("任务模板 ID 与版本必须同时提供")
        submitted = body.model_dump(exclude={"request_key"})
        submitted.update({
            "title": title[:200],
            "goal": goal,
            "case_ids": case_ids,
            "security_assessment": security_assessment,
            "web_authoring": web_authoring,
        })
        request_digest = hashlib.sha256(json.dumps(
            {"project_id": project.id, "input": submitted, "verification_source": _verification_source},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()

        def replay_concurrent_request() -> dict[str, Any] | None:
            """Recover the winning row after a concurrent insert hits the unique key."""
            db.rollback()
            if not body.request_key:
                return None
            winner = db.query(Task).filter(
                Task.created_by == actor.id, Task.request_key == body.request_key,
            ).first()
            if winner is not None and winner.request_digest == request_digest:
                return TaskQueryService.task_detail(db, winner)
            return None

        if body.request_key:
            existing = db.query(Task).filter(
                Task.created_by == actor.id, Task.request_key == body.request_key,
            ).first()
            if existing is not None:
                if existing.request_digest is not None:
                    if existing.request_digest != request_digest:
                        raise conflict("相同 request_key 已用于不同任务内容")
                else:
                    latest = db.query(TaskRun).filter(TaskRun.task_id == existing.id).order_by(
                        TaskRun.run_number.desc(),
                    ).first()
                    snapshot = latest.input_snapshot or {} if latest else {}
                    template = snapshot.get("template") or {}
                    if (
                        existing.project_id != project.id or existing.goal != goal
                        or existing.title != title[:200] or existing.environment_id != body.environment_id
                        or existing.input_case_ids != case_ids
                        or (existing.security_assessment_json or None) != security_assessment
                        or existing.agent_definition_id != body.agent_definition_id
                        or existing.task_mode != body.task_mode
                        or (existing.web_authoring_json or None) != web_authoring
                        or (template.get("id"), template.get("version")) != (body.template_id, body.template_version)
                        or (snapshot.get("verification_source") or None) != _verification_source
                    ):
                        raise conflict("相同 request_key 已用于不同任务内容")
                return TaskQueryService.task_detail(db, existing)

        template_snapshot = None
        if body.template_id is not None or body.template_version is not None:
            from app.orchestration.tasks.services.template_service import TaskTemplateService

            template = TaskTemplateService.get(db, body.template_id, actor)
            if template.project_id != project.id:
                raise not_found("任务模板不存在")
            if not template.is_active or template.version != body.template_version:
                raise conflict("任务模板已停用或版本已更新，请重新选择模板")
            template_snapshot = {"id": template.id, "version": template.version, "name": template.name}
        if body.task_mode == "WEB_AUTHORING":
            if case_ids or security_assessment or web_authoring is None:
                raise bad_request("交互式 Web 编写需提供会话范围，且不能绑定用例或安全评估")
            from app.features.web_testing.models import WebAuthProfile

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
                from app.features.web_testing.models import WebAgentSession
                from app.execution.browser.session_manager import registry

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
                    from app.features.web_testing.models import WebCase
                    from app.features.web_testing.services.web_ui_service import case_response
                    if db.get(WebCase, case.id) is None or not case_response(db, case).get("confirmed"):
                        raise bad_request("Web 用例必须先在 Web 管理页确认当前版本")
            if len(target_types) != 1:
                raise bad_request("一个任务运行需选择同一执行器类型的用例；API 与 Web 请分别创建任务")
            target_type = next(iter(target_types))
        requested_target = "WEB_AUTHORING" if body.task_mode == "WEB_AUTHORING" else (
            "SECURITY" if security_assessment else (body.target_type if body.target_type in {"API", "WEB"} else None)
        )
        if requested_target is not None and requested_target != target_type:
            raise bad_request("所选执行类型与任务范围不匹配")
        environment = resolve_project_environment(db, project.id, body.environment_id)
        if security_assessment and security_assessment.get("web_session_id"):
            if web_session.environment_id != environment.id:
                raise bad_request("Web 页面检查会话与安全评估执行环境必须一致")

        agent_bundle = resolve_agent_profile(
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
            request_digest=request_digest if body.request_key else None,
        )
        db.add(task)
        try:
            db.flush()
        except IntegrityError:
            replayed = replay_concurrent_request()
            if replayed is not None:
                return replayed
            raise
        run = create_run(db, task, actor, run_number=1, target_type=target_type, agent_bundle=agent_bundle)
        if template_snapshot or _verification_source:
            snapshot = dict(run.input_snapshot or {})
            if template_snapshot:
                snapshot.update({
                    "template": template_snapshot,
                    "submitted_input": body.model_dump(exclude={"request_key"}),
                })
            if _verification_source:
                snapshot["verification_source"] = _verification_source
                TaskResourceService.add_resource_ref(
                    db, run, "INPUT", "BUG", str(_verification_source["bug_id"]),
                    metadata={"purpose": "defect_verification"},
                )
                TaskResourceService.add_resource_ref(
                    db, run, "INPUT", "CASE_EXECUTION", str(_verification_source["case_execution_id"]),
                    metadata={"purpose": "original_failure"},
                )
            run.input_snapshot = snapshot
        task.status = run.status
        try:
            db.commit()
        except IntegrityError:
            # 同一用户并发重放相同 request_key 时由唯一约束裁决，回读胜出的任务而不重复排程。
            replayed = replay_concurrent_request()
            if replayed is not None:
                return replayed
            raise
        db.refresh(task)
        return TaskQueryService.task_detail(db, task)

    def create_verification_task(
        self, db: Session, bug_id: int, body: VerificationTaskRequest, *, actor: User,
    ) -> dict[str, Any]:
        """从已修复缺陷创建标准任务；校验来源与单用例前置条件，再复用现有执行流。"""
        from app.features.defects.models import Bug, DefectSourceLink
        from app.features.test_management.models.execution import CaseExecution, TestRun
        from app.features.test_management.models.test_case import TestCase
        from app.features.test_management.models.test_case_precondition import TestCasePrecondition

        bug = db.get(Bug, bug_id)
        if bug is None:
            raise not_found("缺陷不存在")
        project = TaskAccessService.get_project_for_write(db, bug.project_id, actor)
        if bug.status != "已修复":
            raise bad_request("只有标记为已修复的缺陷可以发起验证")
        execution = db.get(CaseExecution, body.source_case_execution_id)
        source_link = db.query(DefectSourceLink).filter_by(
            bug_id=bug.id, case_execution_id=body.source_case_execution_id, project_id=project.id,
        ).first()
        if execution is None or source_link is None or execution.status not in {"FAILED", "ERROR"}:
            raise not_found("缺陷关联的失败执行不存在")
        original_run = db.get(TestRun, execution.test_run_id)
        if original_run is None or original_run.project_id != project.id or execution.test_case_id is None:
            raise not_found("来源执行不属于当前项目或用例已失效")
        case = db.get(TestCase, execution.test_case_id)
        if case is None or case.project_id != project.id:
            raise not_found("来源用例不存在")
        if not case.enabled or case.status != "ACTIVE" or case.target_type not in {"API", "WEB"}:
            raise bad_request("用例已停用或不支持任务验证，请先恢复有效资产")
        preconditions = db.query(TestCasePrecondition).filter(TestCasePrecondition.test_case_id == case.id).all()
        if any(row.type != "VARIABLE" for row in preconditions):
            raise bad_request("此用例包含尚不能自动解析的前置条件；请先补齐依赖或选用自包含用例，禁止只执行部分链路")

        existing = db.query(Task).filter(Task.created_by == actor.id, Task.request_key == body.request_key).first()
        expected_source = {"bug_id": bug.id, "case_execution_id": execution.id}
        selected_environment = resolve_project_environment(db, project.id, body.environment_id)
        if existing is not None:
            latest = db.query(TaskRun).filter(TaskRun.task_id == existing.id).order_by(TaskRun.run_number.desc()).first()
            actual_source = (latest.input_snapshot or {}).get("verification_source") if latest else None
            if (
                existing.project_id != project.id
                or existing.environment_id != selected_environment.id
                or actual_source != expected_source
            ):
                raise conflict("请求标识已用于其他任务、环境或来源")
            return TaskQueryService.task_detail(db, existing)

        result = self.create_task(db, project.id, TaskCreate(
            title=f"验证缺陷 #{bug.id}：{case.name}"[:200],
            goal=f"验证已修复缺陷 #{bug.id}（{bug.title}）。重新执行用例 #{case.id}：{case.name}。请依据最新执行证据判断修复是否生效，不自动关闭缺陷。",
            environment_id=body.environment_id,
            case_ids=[case.id],
            target_type=case.target_type,
            request_key=body.request_key,
        ), actor=actor, _verification_source=expected_source)
        return TaskQueryService.task_detail(db, db.get(Task, result["id"]))

    def list_available_agents(self, db: Session, project_id: int, *, actor: User, target_type: str) -> list[dict[str, Any]]:
        """委托规范职责入口，保留调用契约。"""
        return list_available_agents(db, project_id, actor=actor, target_type=target_type)


    def list_tasks(
        self, db: Session, user: User, *, page: int, page_size: int,
        project_id: int | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        """兼容入口：委托只读查询服务列出可见任务。"""
        return TaskQueryService.list_tasks(db, user, page=page, page_size=page_size, project_id=project_id, status=status)

    def task_summary(self, db: Session, user: User) -> dict[str, Any]:
        return TaskQueryService.task_summary(db, user)

    def get_task(self, db: Session, task_id: int, user: User) -> dict[str, Any]:
        """兼容入口：委托只读查询服务读取任务详情。"""
        return TaskQueryService.get_task(db, task_id, user)

    def get_run_detail(self, db: Session, run_id: int, user: User) -> dict[str, Any]:
        """兼容入口：委托只读查询服务读取运行详情。"""
        return TaskQueryService.get_run_detail(db, run_id, user)

    def list_messages(self, db: Session, run_id: int, user: User) -> list[TaskMessage]:
        """兼容入口：委托只读查询服务按原顺序读取消息。"""
        return TaskQueryService.list_messages(db, run_id, user)

    def send_message(
        self, db: Session, run_id: int, body: TaskMessageCreate, *, actor: User,
    ) -> dict[str, Any]:
        """兼容入口：委托消息服务，运行创建和工作入队只暴露窄协作回调。"""
        return TaskMessageService.send_message(
            db, run_id, body, actor=actor,
            create_run=create_run,
            enqueue_work=enqueue_work,
            append_event=append_event,
        )

    def create_command(self, db: Session, run_id: int, body: TaskCommandCreate, *, actor: User) -> TaskCommand:
        """委托规范职责入口，保留调用契约。"""
        return create_command(db, run_id, body, actor=actor)

    def list_events(self, db: Session, run_id: int, user: User, *, after_seq: int, limit: int = 200) -> list[TaskEvent]:
        """兼容入口：委托只读查询服务按事件游标读取事件。"""
        return TaskQueryService.list_events(db, run_id, user, after_seq=after_seq, limit=limit)

    def list_resources(self, db: Session, run_id: int, user: User) -> list[dict[str, Any]]:
        """兼容入口：委托资源服务读取批量命名后的运行资源。"""
        return TaskResourceService.list_resources(db, run_id, user)

    def find_tasks_for_resource(
        self, db: Session, user: User, *, resource_type: str, resource_id: str,
        project_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """兼容入口：委托资源服务按原资源标识反查任务来源。"""
        return TaskResourceService.find_tasks_for_resource(
            db, user, resource_type=resource_type, resource_id=resource_id, project_id=project_id,
        )


    @staticmethod
    def assert_agent_model_access(db: Session, project_id: int, actor: User, model_config_id: int | None) -> ModelConfiguration:
        """委托规范职责入口，保留调用契约。"""
        return assert_agent_model_access(db, project_id, actor, model_config_id)

    @staticmethod
    def assert_agent_runtime_access(db: Session, task: Task, run: TaskRun, actor: User) -> None:
        """委托规范职责入口，保留调用契约。"""
        return assert_agent_runtime_access(db, task, run, actor)
