"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import Task, TaskCommand, TaskEvent, TaskMessage, TaskRun
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


class TaskService:
    """稳定领域门面；各资源由唯一实现持有。"""

    def create_task(self, db: Session, project_id: int, body: TaskCreate, *, actor: User) -> dict[str, Any]:
        """校验已确认的测试资产或安全评估范围，创建首个运行与对应 Worker。"""
        project = TaskAccessService.get_project_for_write(db, project_id, actor)
        case_ids = list(dict.fromkeys(body.case_ids))
        security_assessment = body.security_assessment.model_dump() if body.security_assessment else None
        web_authoring = body.web_authoring.model_dump() if body.web_authoring else None
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
                return TaskQueryService.task_detail(db, existing)

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
        )
        db.add(task)
        db.flush()
        run = create_run(db, task, actor, run_number=1, target_type=target_type, agent_bundle=agent_bundle)
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
                    return TaskQueryService.task_detail(db, existing)
            raise
        db.refresh(task)
        return TaskQueryService.task_detail(db, task)

    def list_available_agents(self, db: Session, project_id: int, *, actor: User, target_type: str) -> list[dict[str, Any]]:
        """委托规范职责入口，保留调用契约。"""
        return list_available_agents(db, project_id, actor=actor, target_type=target_type)


    def list_tasks(
        self, db: Session, user: User, *, page: int, page_size: int,
        project_id: int | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        """兼容入口：委托只读查询服务列出可见任务。"""
        return TaskQueryService.list_tasks(db, user, page=page, page_size=page_size, project_id=project_id, status=status)

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
