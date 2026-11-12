"""Domain-aware soft deletion, scoped recycle-bin access, recovery and purge."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database.base import Base
from app.core.database.soft_delete import SoftDeleteBase
from app.core.http.errors import bad_request, conflict, forbidden, not_found
from app.core.models.data_lifecycle import LifecycleAuditEvent, RecycleBinItem
from app.core.models.identity import Organization, OrganizationMember, User
from app.core.models.notification import Notification
from app.core.models.project import ProjectMember, ProjectOutboundTarget
from app.core.models.project import Project
from app.core.models.configuration import Environment, ModelConfiguration
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion
from app.features.defects.models.bug import Bug
from app.features.defects.models.source_link import DefectSourceLink
from app.features.reports.models.report import TestReport
from app.core.security.roles import (
    ORG_ROLE_ADMIN, ORG_ROLE_OWNER,
    PROJECT_ROLE_MEMBER, PROJECT_ROLE_OWNER, PROJECT_ROLE_VIEWER,
    accessible_project_ids, has_project_role, is_platform_admin, organization_role, project_role_for,
)
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_domain import BusinessDomain
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_rule import BusinessRule
from app.features.business.models.business_state import BusinessState
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.models.business_variable_ref import BusinessVariableRef
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_change_log import ApiChangeLog
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_strategy import TestStrategy
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_scope import TestCaseScope, TestScopeNode
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_case_precondition import TestCasePrecondition
from app.features.test_management.models.test_plan import TestPlan, TestPlanSuite
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.models.test_suite import TestSuite, TestSuiteCase
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.web_testing.models import PageObject, WebAuthProfile
from app.features.security_testing.zap.contracts import JOB_INFLIGHT_STATUSES
from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.models.notification_record import NotificationRecord
from app.features.mocking.models import MockEndpoint, MockExecution, MockScenario, MockService, MockContext, TestCaseMock
from app.features.test_data.models import (
    DataProvider,
    DataPool,
    DataPoolItem,
    Fixture,
    FixtureDependency,
    FixtureExecution,
    FixtureStep,
    ProviderExecution,
    TargetDatabaseConnection,
    TestDataAsset,
)
from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.pool import DataPoolLease
from app.features.automation_center.models.entities import (
    AutomationExecution,
    AutomationIntegrationConfig,
    AutomationPipeline,
    AutomationProject,
)
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.services.access_service import require_admin as require_test_data_admin
from app.features.security_testing.models import (
    SecurityCase,
    SecurityFinding,
    SecurityMutationRule,
    SecurityStrategy,
)
from app.platform.environment_configuration.models import ProjectEnvironment
from app.agents.models import AgentDefinition, AgentDefinitionRevision, AgentSession
from app.skills.models import SkillDefinition, SkillDefinitionRevision, SkillUsageEvent
from app.mcp.models import MCPServer


RESOURCE_MODELS: dict[str, type[SoftDeleteBase]] = {
    "user": User,
    "project": Project,
    "organization": Organization,
    "agent_session": AgentSession,
    "test_case": TestCase,
    "test_point": TestPoint,
    "test_scope": TestScopeNode,
    "api_module": ApiModule,
    "api_interface": ApiInterface,
    "api_relation": ApiRelation,
    "business_domain": BusinessDomain,
    "business_flow": BusinessFlow,
    "business_action": BusinessAction,
    "business_rule": BusinessRule,
    "business_variable": BusinessVariable,
    "business_state": BusinessState,
    "business_binding": BusinessBinding,
    "business_precondition": BusinessPrecondition,
    "business_api_mapping": BusinessApiMapping,
    "business_variable_ref": BusinessVariableRef,
    "test_suite": TestSuite,
    "test_plan": TestPlan,
    "test_report": TestReport,
    "bug": Bug,
    "web_page": PageObject,
    "test_strategy": TestStrategy,
    "mock_service": MockService,
    "mock_endpoint": MockEndpoint,
    "mock_scenario": MockScenario,
    "test_data_asset": TestDataAsset,
    "data_provider": DataProvider,
    "fixture": Fixture,
    "data_pool": DataPool,
    "data_pool_item": DataPoolItem,
    "target_database_connection": TargetDatabaseConnection,
    "automation_integration": AutomationIntegrationConfig,
    "automation_project": AutomationProject,
    "security_strategy": SecurityStrategy,
    "security_rule": SecurityMutationRule,
    "environment": Environment,
    "knowledge_base": KnowledgeBase,
    "knowledge_document": KnowledgeDocument,
    "agent_definition": AgentDefinition,
    "skill_definition": SkillDefinition,
    "mcp_server": MCPServer,
    "notification_channel": NotificationChannel,
    "model_configuration": ModelConfiguration,
    "web_auth_profile": WebAuthProfile,
    "security_scan_target": SecurityScanTarget,
    "security_scan_profile": SecurityScanProfile,
    "security_scan_auth_profile": SecurityScanAuthProfile,
    "notification": Notification,
    "project_outbound_target": ProjectOutboundTarget,
    "project_member": ProjectMember,
    "organization_member": OrganizationMember,
    "test_step": TestStep,
    "test_assertion": TestAssertion,
    "test_case_precondition": TestCasePrecondition,
    "test_case_data": TestCaseData,
    "test_suite_case": TestSuiteCase,
    "test_plan_suite": TestPlanSuite,
}
PERMANENT_CONFIRMATION = "PERMANENTLY_DELETE"


def _now() -> datetime:
    # This project stores timestamps as timezone-naive UTC throughout its ORM.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _model(resource_type: str) -> type[SoftDeleteBase]:
    model = RESOURCE_MODELS.get(resource_type)
    if model is None:
        raise bad_request("该资源类型尚未接入回收站")
    return model


def _resource_meta(row: SoftDeleteBase) -> dict[str, Any]:
    fields = (
        "project_id", "name", "direction", "parent_id", "strategy_id", "test_point_id",
        "module_id", "method", "path", "domain_id", "flow_id", "action_id", "binding_id",
        "action_key", "entity", "is_default", "source_action_id", "target_action_id",
        "title", "report_no", "test_run_id", "severity", "status",
        "service_key", "mock_service_id", "mock_endpoint_id", "scenario_key", "is_default",
        "entity_type", "provider_type", "risk_level", "fixture_id", "strategy_key",
        "display_name", "is_active", "base_id", "category", "current_version_id",
        "key", "workflow_template", "purpose", "version", "is_enabled",
        "fixture_key", "pool_key", "pool_id", "environment_id", "scope",
        "callback_key", "integration_config_id",
        "owner_id", "organization_id", "username", "role", "is_active",
    )
    return {name: getattr(row, name) for name in fields if hasattr(row, name)}


def _resource_name(row: SoftDeleteBase) -> str:
    if hasattr(row, "name"):
        return str(getattr(row, "name"))
    if hasattr(row, "username"):
        return str(getattr(row, "username") or f"用户 #{row.id}")
    if hasattr(row, "title"):
        return str(getattr(row, "title"))
    if hasattr(row, "path"):
        return f"{getattr(row, 'method', '')} {row.path}".strip()
    if hasattr(row, "entity"):
        return f"{row.entity} 状态定义"
    if isinstance(row, BusinessVariableRef):
        return f"变量引用 #{row.source_action_id}.{row.source_variable} → #{row.target_action_id}.{row.target_variable}"
    if isinstance(row, ApiRelation):
        return f"接口关联 #{row.source_api_id} → #{row.target_api_id}"
    if isinstance(row, DataPoolItem):
        return f"数据池条目 #{row.id}"
    if isinstance(row, (ProjectMember, OrganizationMember)):
        return f"成员用户 #{row.user_id}"
    if isinstance(row, ProjectOutboundTarget):
        return f"{row.scheme}://{row.host}:{row.port}"
    if isinstance(row, ModelConfiguration):
        return str(row.label)
    if isinstance(row, TestSuiteCase):
        return f"套件 #{row.suite_id} · 用例 #{row.test_case_id}"
    if isinstance(row, TestPlanSuite):
        return f"计划 #{row.plan_id} · 套件 #{row.suite_id}"
    if isinstance(row, TestAssertion):
        return f"断言 {row.assertion_type}"
    if isinstance(row, TestCasePrecondition):
        return f"前置条件 {row.type}"
    return f"{type(row).__name__} #{row.id}"


def _contains_mcp_reference(value: Any, prefix: str) -> bool:
    if isinstance(value, str):
        return value.startswith(prefix)
    if isinstance(value, dict):
        return any(_contains_mcp_reference(item, prefix) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_mcp_reference(item, prefix) for item in value)
    return False


def _row_project_id(db: Session, row: SoftDeleteBase) -> int | None:
    """Resolve the owning project for config rows whose schema stores only parent IDs."""
    project_id = getattr(row, "project_id", None)
    if project_id is not None:
        return int(project_id)
    flow_id = getattr(row, "flow_id", None)
    if flow_id is not None:
        flow = db.query(BusinessFlow).execution_options(include_deleted=True).filter_by(id=flow_id).first()
        return flow.project_id if flow is not None else None
    action_id = getattr(row, "action_id", None)
    if action_id is not None:
        action = db.query(BusinessAction).execution_options(include_deleted=True).filter_by(id=action_id).first()
        flow = (
            db.query(BusinessFlow).execution_options(include_deleted=True).filter_by(id=action.flow_id).first()
            if action is not None else None
        )
        return flow.project_id if flow is not None else None
    binding_id = getattr(row, "binding_id", None)
    if binding_id is not None:
        binding = db.query(BusinessBinding).execution_options(include_deleted=True).filter_by(id=binding_id).first()
        return _row_project_id(db, binding) if binding is not None else None
    if isinstance(row, BusinessVariableRef):
        flow = db.query(BusinessFlow).execution_options(include_deleted=True).filter_by(id=row.flow_id).first()
        return flow.project_id if flow is not None else None
    if isinstance(row, DataPoolItem):
        pool = db.query(DataPool).execution_options(include_deleted=True).filter_by(id=row.pool_id).first()
        return pool.project_id if pool is not None else None
    test_case_id = getattr(row, "test_case_id", None)
    if test_case_id is not None:
        case = db.query(TestCase).execution_options(include_deleted=True).filter_by(id=test_case_id).first()
        return case.project_id if case is not None else None
    suite_id = getattr(row, "suite_id", None)
    if suite_id is not None and not isinstance(row, TestPlanSuite):
        suite = db.query(TestSuite).execution_options(include_deleted=True).filter_by(id=suite_id).first()
        return suite.project_id if suite is not None else None
    plan_id = getattr(row, "plan_id", None)
    if plan_id is not None:
        plan = db.query(TestPlan).execution_options(include_deleted=True).filter_by(id=plan_id).first()
        return plan.project_id if plan is not None else None
    return None


def _web_page_reference_count(db: Session, page_id: int, project_id: int) -> int:
    """Count active and recoverable Web cases that refer to an encrypted page object."""
    import json

    from app.core.security.crypto import decrypt_secret
    from app.features.test_management.models.test_step import TestStep

    rows = (
        db.query(TestStep)
        .join(TestCase, TestCase.id == TestStep.test_case_id)
        .execution_options(include_deleted=True)
        .filter(TestCase.project_id == project_id, TestStep.target_type == "WEB")
        .all()
    )
    count = 0
    for step in rows:
        encrypted = (step.config_json or {}).get("web_encrypted")
        if not encrypted:
            continue
        try:
            payload = json.loads(decrypt_secret(encrypted) or "")
        except Exception as exc:
            raise conflict("存在无法校验的 Web 步骤配置，请先修复后再删除页面对象") from exc
        if payload.get("page_object_id") == page_id:
            count += 1
    return count


def _connection_reference_count(db: Session, project_id: int, connection_id: int) -> int:
    """统计仍在使用该连接的活跃 Data Provider。已删除 Provider 不阻止软删除。"""
    rows = db.query(DataProvider.config_json).filter(DataProvider.project_id == project_id).all()
    return sum(
        1 for (config,) in rows
        if isinstance(config, dict) and config.get("connection_id") == connection_id
    )


def _scope_access(db: Session, project_id: int | None, actor: User, *, write: bool) -> int | None:
    if project_id is None:
        if not is_platform_admin(actor):
            raise not_found("回收站记录不存在")
        return None
    project = db.get(Project, project_id)
    if project is None:
        project = db.query(Project).execution_options(include_deleted=True).filter_by(id=project_id).first()
    role = project_role_for(db, project, actor) if project is not None else None
    if not has_project_role(role, PROJECT_ROLE_VIEWER):
        raise not_found("回收站记录不存在")
    if write and not has_project_role(role, PROJECT_ROLE_MEMBER):
        raise forbidden("需要项目成员权限")
    return project_id


def _assert_deletable(db: Session, resource_type: str, row: SoftDeleteBase, actor: User) -> None:
    """Reject protected/default resources and dependencies that would be stranded."""
    if resource_type == "agent_session":
        if row.task_run_id is not None:
            raise conflict("任务运行关联的 Agent 会话属于执行证据，不能删除")
    elif resource_type == "user":
        if not is_platform_admin(actor):
            raise forbidden("仅平台管理员可删除用户账号")
        if row.id == actor.id:
            raise forbidden("不能删除当前登录账号")
        if row.role == "admin":
            raise bad_request("不能删除平台管理员账号")
    elif resource_type == "organization":
        if not is_platform_admin(actor):
            raise forbidden("需要平台管理员权限")
        project_count = db.query(Project.id).execution_options(include_deleted=True).filter(
            Project.organization_id == row.id,
        ).count()
        if project_count:
            raise conflict(f"组织仍关联 {project_count} 个（含回收站）项目，请先迁移或处理项目")
    elif resource_type == "project":
        active_statuses = (
            "QUEUED", "PENDING", "RUNNING", "WAITING", "WAITING_WINDOW",
            "WAITING_CONFIRMATION", "PAUSED", "PAUSE_REQUESTED", "CANCEL_REQUESTED",
            "RECONCILIATION_REQUIRED",
        )
        from app.orchestration.tasks.models import Task, TaskRun

        if db.query(TaskRun.id).join(Task, Task.id == TaskRun.task_id).filter(
            Task.project_id == row.id,
            TaskRun.status.in_(active_statuses),
        ).first():
            raise conflict("项目仍有执行中或排队的任务运行，请等待任务进入终态后再删除")
        for mapper in Base.registry.mappers:
            model = mapper.class_
            if model is Project or not hasattr(model, "id") or not hasattr(model, "project_id"):
                continue
            if hasattr(model, "status") and db.query(model.id).filter(
                model.project_id == row.id, model.status.in_(active_statuses),
            ).first():
                raise conflict(f"项目仍有 {model.__tablename__} 活跃或排队记录，请等待任务完成后再删除")
            if model.__tablename__ == "task_template" and hasattr(model, "is_active") and db.query(model.id).filter(
                model.project_id == row.id, model.is_active.is_(True),
            ).first():
                raise conflict("项目仍有启用中的任务模板，请先停用模板再删除项目")
    elif resource_type == "agent_definition":
        if row.created_by is None:
            raise forbidden("平台内置 Agent 不可删除")
        parents = db.query(AgentDefinition).filter(AgentDefinition.id != row.id).all()
        if any(row.id in (parent.child_agent_ids or []) for parent in parents):
            raise conflict("该 Agent 仍被启用或可用的父 Agent 引用，请先移除父子关系")
        from app.orchestration.tasks.models import Task, TaskRun

        active_task = db.query(Task.id).filter(
            Task.agent_definition_id == row.id,
            Task.status.in_(
                ("QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED", "PAUSE_REQUESTED",
                 "CANCEL_REQUESTED", "RECONCILIATION_REQUIRED"),
            ),
        ).first()
        if active_task:
            raise conflict("该 Agent 仍被排队或执行中的任务使用，请等待任务进入终态后再删除")
        active_runs = db.query(TaskRun, Task.agent_definition_id).join(
            Task, Task.id == TaskRun.task_id,
        ).filter(TaskRun.status.in_(
            ("QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED", "PAUSE_REQUESTED",
             "CANCEL_REQUESTED", "RECONCILIATION_REQUIRED"),
        )).all()
        for run, task_agent_id in active_runs:
            if task_agent_id == row.id:
                raise conflict("该 Agent 正被排队或执行中的任务使用，请等待任务进入终态后再删除")
            snapshot = (run.input_snapshot or {}).get("agent_definition") or {}
            profiles = [snapshot, *(snapshot.get("child_agents") or [])]
            if any(profile.get("id") == row.id for profile in profiles):
                raise conflict("该 Agent 正被排队或执行中的任务快照引用，请等待任务进入终态后再删除")
    elif resource_type == "skill_definition":
        if row.created_by is None:
            raise forbidden("平台内置 Skill 不可删除")
        agents = db.query(AgentDefinition).all()
        if any(row.key in (agent.skill_keys or []) for agent in agents):
            raise conflict("该 Skill 仍被 Agent 配置引用，请先从 Agent 配置中移除")
        from app.orchestration.tasks.models import TaskRun

        active_runs = db.query(TaskRun).filter(TaskRun.status.in_(
            ("QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED", "PAUSE_REQUESTED",
             "CANCEL_REQUESTED", "RECONCILIATION_REQUIRED"),
        )).all()
        for run in active_runs:
            agent = (run.input_snapshot or {}).get("agent_definition") or {}
            profiles = [agent, *(agent.get("child_agents") or [])]
            if any(
                any(skill.get("key") == row.key for skill in (profile.get("skills") or []))
                for profile in profiles
            ):
                raise conflict("该 Skill 仍被排队或执行中的任务快照引用，请等待任务进入终态后再删除")
    elif resource_type == "mcp_server":
        prefix = f"mcp:{row.id}:"
        if any(_contains_mcp_reference(agent.tool_keys or [], prefix) for agent in db.query(AgentDefinition).all()):
            raise conflict("该 MCP 服务仍被 Agent 工具授权引用，请先移除关联或停用 Agent")
        if any(
            _contains_mcp_reference(skill.mcp_tool_keys_json or [], prefix)
            for skill in db.query(SkillDefinition).all()
        ):
            raise conflict("该 MCP 服务仍被 Skill 配置引用，请先移除关联或停用 Skill")
        from app.orchestration.tasks.models import TaskRun

        active_runs = db.query(TaskRun).filter(TaskRun.status.in_(
            ("QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED", "PAUSE_REQUESTED",
             "CANCEL_REQUESTED", "RECONCILIATION_REQUIRED"),
        )).all()
        if any(_contains_mcp_reference(run.input_snapshot or {}, prefix) for run in active_runs):
            raise conflict("该 MCP 服务仍被排队或执行中的任务快照引用，请等待任务进入终态后再删除")
    elif resource_type == "knowledge_base":
        count = db.query(KnowledgeDocument.id).execution_options(include_deleted=True).filter(
            KnowledgeDocument.base_id == row.id,
        ).count()
        if count:
            raise conflict(f"知识库仍包含 {count} 个文档，请先逐个处理文档；不会级联删除")
    elif resource_type == "knowledge_document":
        queued = db.query(KnowledgeVersion.id).filter(
            KnowledgeVersion.document_id == row.id, KnowledgeVersion.status == "QUEUED",
        ).first()
        if queued:
            raise conflict("文档仍有排队中的版本解析任务，请等待解析完成后再删除")
        from app.orchestration.tasks.models import Task, TaskRun

        active_snapshots = db.query(TaskRun.input_snapshot).join(
            Task, Task.id == TaskRun.task_id,
        ).filter(
            Task.project_id == row.project_id,
            TaskRun.status.in_((
                "QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED",
                "PAUSE_REQUESTED", "CANCEL_REQUESTED", "RECONCILIATION_REQUIRED",
            )),
        ).all()
        referenced_versions: set[int] = set()
        for (snapshot,) in active_snapshots:
            agent = (snapshot or {}).get("agent_definition") or {}
            profiles = [agent, *(agent.get("child_agents") or [])]
            for profile in profiles:
                knowledge = profile.get("knowledge") or {}
                referenced_versions.update(
                    int(value) for value in knowledge.get("version_ids", [])
                    if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
                )
        if referenced_versions and db.query(KnowledgeVersion.id).filter(
            KnowledgeVersion.document_id == row.id,
            KnowledgeVersion.id.in_(referenced_versions),
        ).first():
            raise conflict("该知识文档仍被排队或执行中的任务知识快照引用，请等待任务进入终态后再删除")
    elif resource_type == "data_provider":
        if str(row.provider_type).startswith("DATABASE"):
            require_test_data_admin(db, actor)
        if db.query(FixtureStep.id).filter(FixtureStep.provider_id == row.id).first():
            raise conflict("Data Provider 仍被 Fixture 步骤引用，请先移除引用")
    elif resource_type == "test_data_asset":
        if db.query(DataPool.id).filter(DataPool.asset_id == row.id).first():
            raise conflict("测试数据仍被数据池引用，请先移除数据池关联")
    elif resource_type == "fixture":
        ref_count = int(db.query(TestCaseFixture.id).filter(TestCaseFixture.fixture_id == row.id).count())
        if ref_count:
            raise conflict(f"该 Fixture 正被 {ref_count} 个用例引用，请先在用例上移除引用")
        dep_count = int(
            db.query(FixtureDependency.id)
            .join(Fixture, Fixture.id == FixtureDependency.fixture_id)
            .filter(FixtureDependency.depends_on_fixture_id == row.id)
            .count()
        )
        if dep_count:
            raise conflict(f"该 Fixture 正被 {dep_count} 条依赖边引用，请先移除依赖")
    elif resource_type == "data_pool":
        if db.query(DataPoolItem.id).filter(DataPoolItem.pool_id == row.id).first():
            raise conflict("数据池仍有条目，请先逐条处理")
        if db.query(DataPoolLease.id).filter(
            DataPoolLease.status == "ACTIVE",
            DataPoolLease.item_id.in_(
                db.query(DataPoolItem.id).execution_options(include_deleted=True)
                .filter(DataPoolItem.pool_id == row.id)
            ),
        ).first():
            raise conflict("数据池存在活跃租约，无法删除")
    elif resource_type == "data_pool_item":
        if row.status == "OCCUPIED":
            raise conflict("条目处于 OCCUPIED 状态，无法删除")
        if db.query(DataPoolLease.id).filter(
            DataPoolLease.item_id == row.id, DataPoolLease.status == "ACTIVE",
        ).first():
            raise conflict("条目存在活跃租约，无法删除")
    elif resource_type == "target_database_connection":
        require_test_data_admin(db, actor)
        used = _connection_reference_count(db, row.project_id, row.id)
        if used:
            raise conflict(f"该连接正被 {used} 个 Provider 引用，请先移除引用")
    elif resource_type == "automation_integration":
        if db.query(AutomationProject.id).filter(AutomationProject.integration_config_id == row.id).first():
            raise conflict("接入配置仍被自动化项目使用")
    elif resource_type == "automation_project":
        if db.query(AutomationExecution.id).filter(
            AutomationExecution.automation_project_id == row.id,
            AutomationExecution.status.in_(("PENDING", "RUNNING")),
        ).first():
            raise conflict("自动化项目仍有排队或运行中的执行，请等待结束后再删除")
    elif resource_type == "model_configuration":
        if row.is_default:
            raise bad_request("默认模型不能删除，请先指定新的默认模型")
    elif resource_type == "security_scan_profile":
        if row.is_builtin:
            raise forbidden("平台内置扫描策略不可删除")
    elif resource_type == "security_scan_target":
        if db.query(SecurityScanJob.id).filter(
            SecurityScanJob.target_id == row.id,
            SecurityScanJob.status.in_(tuple(JOB_INFLIGHT_STATUSES)),
        ).first():
            raise conflict("该目标下有未结束的扫描任务，无法删除")
    elif resource_type == "notification_channel":
        if db.query(AutomationProject.id).filter(AutomationProject.notification_channel_id == row.id).first():
            raise conflict("通知渠道仍被自动化项目使用，请先解除绑定")
    elif resource_type == "project_member":
        project = db.get(Project, row.project_id)
        if project is not None and project.owner_id == row.user_id:
            raise bad_request("项目负责人不能移除；如需变更请使用负责人转移接口")
    elif resource_type == "organization_member":
        organization = (
            db.query(Organization).execution_options(include_deleted=True)
            .filter(Organization.id == row.organization_id).first()
        )
        if organization is not None and organization.deleted_at is None and organization.owner_id == row.user_id:
            raise forbidden("组织负责人不能移除")
    elif resource_type == "security_strategy":
        if row.builtin or row.project_id is None:
            raise forbidden("系统内置安全策略不可删除")
        if db.query(SecurityMutationRule.id).filter(
            SecurityMutationRule.strategy_id == row.id,
        ).first():
            raise conflict("安全策略仍有未单独删除的规则，请先处理规则")
    elif resource_type == "security_rule":
        strategy = db.query(SecurityStrategy).execution_options(include_deleted=True).filter_by(
            id=row.strategy_id,
        ).first()
        if strategy is None or strategy.builtin or strategy.project_id is None:
            raise forbidden("系统内置安全规则不可删除")
    elif resource_type == "environment":
        from app.agents.models.browser_authoring import WebAgentSession
        from app.features.test_data.models import DatabaseAccessPolicy, TargetDatabaseConnection
        from app.features.web_testing.models import WebAuthProfile

        if row.is_default:
            raise bad_request("默认环境不能删除，请先指定新的默认环境")
        if db.query(ProjectEnvironment.id).filter(ProjectEnvironment.environment_id == row.id).first():
            raise conflict("该环境仍被项目环境配置引用，请先逐个移除项目绑定")
        if db.query(TargetDatabaseConnection.id).filter(TargetDatabaseConnection.environment_id == row.id).first():
            raise conflict("该环境仍被数据库连接引用，请先移除连接配置")
        if db.query(DatabaseAccessPolicy.id).filter(DatabaseAccessPolicy.environment_id == row.id).first():
            raise conflict("该环境仍有关联的数据库访问策略，请先移除策略")
        if db.query(WebAuthProfile.id).filter(WebAuthProfile.environment_id == row.id).first():
            raise conflict("该环境仍有关联的 Web 认证配置，请先移除认证配置")
        if db.query(WebAgentSession.id).filter(WebAgentSession.environment_id == row.id).first():
            raise conflict("该环境仍有关联的浏览器探索会话，请先处理会话")
    elif resource_type == "mock_service":
        if db.query(TestCaseMock.id).filter(TestCaseMock.mock_service_id == row.id).first():
            raise conflict("Mock 服务仍被测试用例引用，请先移除用例 Mock 依赖")
        if db.query(MockEndpoint.id).execution_options(include_deleted=True).filter(
            MockEndpoint.mock_service_id == row.id,
        ).first():
            raise conflict("Mock 服务仍有接口，请先逐个处理接口")
    elif resource_type == "mock_endpoint":
        if db.query(TestCaseMock.id).filter(TestCaseMock.mock_endpoint_id == row.id).first():
            raise conflict("Mock 接口仍被测试用例引用，请先移除用例 Mock 依赖")
        if db.query(MockScenario.id).execution_options(include_deleted=True).filter(
            MockScenario.mock_endpoint_id == row.id,
        ).first():
            raise conflict("Mock 接口仍有场景，请先逐个处理场景")
    elif resource_type == "mock_scenario":
        if db.query(TestCaseMock.id).filter(TestCaseMock.mock_scenario_id == row.id).first():
            raise conflict("Mock 场景仍被测试用例引用，请先移除用例 Mock 依赖")
        if db.query(MockService.id).filter(MockService.default_scenario_id == row.id).first():
            raise conflict("Mock 场景仍被服务设为默认场景，请先调整默认配置")
    elif resource_type == "web_page":
        count = _web_page_reference_count(db, row.id, row.project_id)
        if count:
            raise conflict(f"该页面仍被 {count} 条 Web 测试步骤引用，请先调整或删除这些用例")
    elif resource_type == "test_case":
        running = (
            db.query(CaseExecution.id)
            .join(TestRun, TestRun.id == CaseExecution.test_run_id)
            .filter(
                CaseExecution.test_case_id == row.id,
                or_(CaseExecution.status == "RUNNING", TestRun.status == "RUNNING"),
            )
            .first()
        )
        if running:
            raise conflict("测试用例正被执行中的测试计划使用，完成任务后再删除")
    elif resource_type == "test_strategy":
        if db.query(TestPoint.id).execution_options(include_deleted=True).filter(
            TestPoint.strategy_id == row.id,
        ).first():
            raise conflict("测试策略仍被测试点引用，请先调整或删除测试点")
    elif resource_type == "test_point":
        if db.query(TestCase.id).filter(TestCase.test_point_id == row.id).first():
            raise conflict("测试点仍被测试用例引用，请先调整用例关联")
    elif resource_type == "test_scope":
        if row.is_system:
            raise bad_request("系统待整理节点不能删除")
        if db.query(TestScopeNode.id).filter(TestScopeNode.parent_id == row.id).first():
            raise conflict("该范围仍有子节点，请先移动子节点")
        if (
            db.query(TestCaseScope.id)
            .join(TestCase, TestCase.id == TestCaseScope.test_case_id)
            .filter(TestCaseScope.scope_node_id == row.id)
            .first()
        ):
            raise conflict("该范围仍挂有测试用例，请先移动用例")
    elif resource_type == "api_module":
        if row.is_default:
            raise bad_request("未分类模块不可删除")
        if db.query(ApiModule.id).filter(ApiModule.parent_id == row.id, ApiModule.deleted_at.is_(None)).first():
            raise conflict("该模块仍有子模块，请先移动子模块")
        if db.query(ApiInterface.id).filter(
            ApiInterface.module_id == row.id, ApiInterface.deleted_at.is_(None),
        ).first():
            raise conflict("该模块仍有接口，请先移动接口")
    elif resource_type == "api_interface":
        if db.query(TestCase.id).filter(TestCase.api_id == row.id).first():
            raise conflict("该接口仍被测试用例引用，请先调整用例关联")
        if db.query(ApiRelation.id).filter(
            or_(ApiRelation.source_api_id == row.id, ApiRelation.target_api_id == row.id),
            ApiRelation.deleted_at.is_(None),
        ).first():
            raise conflict("该接口仍有业务关联，请先删除或调整接口关联")
    elif resource_type == "business_domain":
        if db.query(BusinessFlow.id).filter(BusinessFlow.domain_id == row.id).first():
            raise conflict("业务域下仍有业务流程，请先移动或删除流程")
    elif resource_type == "business_flow":
        if db.query(BusinessAction.id).filter(BusinessAction.flow_id == row.id).first():
            raise conflict("业务流程下仍有动作，请先移动或删除动作")
        if db.query(BusinessRule.id).filter(BusinessRule.flow_id == row.id).first():
            raise conflict("业务流程仍有业务规则，请先调整规则归属")
        if db.query(BusinessVariableRef.id).filter(BusinessVariableRef.flow_id == row.id).first():
            raise conflict("业务流程仍有变量引用，请先删除或调整引用")
        if db.query(TestCase.id).filter(TestCase.business_flow_id == row.id).first():
            raise conflict("业务流程仍被测试用例引用，请先调整用例")
        if db.query(TestPoint.id).filter(TestPoint.business_flow_id == row.id).first():
            raise conflict("业务流程仍被测试点引用，请先调整测试点")
        if db.query(FlowExecution.id).filter(
            FlowExecution.flow_id == row.id,
            FlowExecution.status.in_(("PENDING", "RUNNING")),
        ).first():
            raise conflict("业务流程正被执行中的任务使用，等待执行完成后再删除")
    elif resource_type == "business_action":
        child_checks = (
            (BusinessRule, BusinessRule.action_id, "业务规则"),
            (BusinessPrecondition, BusinessPrecondition.action_id, "前置条件"),
            (BusinessVariable, BusinessVariable.action_id, "业务变量"),
            (BusinessState, BusinessState.action_id, "业务状态"),
            (BusinessBinding, BusinessBinding.action_id, "业务绑定"),
        )
        for model, foreign_key, label in child_checks:
            if db.query(model.id).filter(foreign_key == row.id).first():
                raise conflict(f"业务动作仍有{label}，请先单独处理")
        if db.query(BusinessVariableRef.id).filter(
            or_(BusinessVariableRef.source_action_id == row.id, BusinessVariableRef.target_action_id == row.id),
        ).first():
            raise conflict("业务动作仍参与变量引用，请先调整或删除引用")
        if db.query(TestCase.id).filter(TestCase.business_action_id == row.id).first():
            raise conflict("业务动作仍被测试用例引用，请先调整用例")
        if db.query(TestPoint.id).filter(TestPoint.business_action_id == row.id).first():
            raise conflict("业务动作仍被测试点引用，请先调整测试点")
        if (
            db.query(ActionExecution.id)
            .join(FlowExecution, FlowExecution.id == ActionExecution.flow_execution_id)
            .filter(
                ActionExecution.action_id == row.id,
                FlowExecution.status.in_(("PENDING", "RUNNING")),
            )
            .first()
        ):
            raise conflict("业务动作正被执行中的流程使用，等待执行完成后再删除")
    elif resource_type == "business_variable":
        if db.query(BusinessVariableRef.id).filter(
            or_(BusinessVariableRef.source_variable_id == row.id, BusinessVariableRef.target_variable_id == row.id),
        ).first():
            raise conflict("业务变量仍被变量引用使用，请先调整或删除引用")
    elif resource_type == "business_binding":
        if db.query(BusinessApiMapping.id).filter(BusinessApiMapping.binding_id == row.id).first():
            raise conflict("业务绑定仍有 API 映射，请先单独删除映射")
        if (
            db.query(ActionExecution.id)
            .join(FlowExecution, FlowExecution.id == ActionExecution.flow_execution_id)
            .filter(
                ActionExecution.binding_id == row.id,
                FlowExecution.status.in_(("PENDING", "RUNNING")),
            )
            .first()
        ):
            raise conflict("业务绑定正被执行中的流程使用，等待执行完成后再删除")
    elif resource_type == "test_suite":
        active_plan = (
            db.query(TestPlan.id)
            .join(TestPlanSuite, TestPlanSuite.plan_id == TestPlan.id)
            .filter(TestPlanSuite.suite_id == row.id, TestPlan.status == "ACTIVE")
            .first()
        )
        if active_plan:
            raise conflict("该套件仍被启用的测试计划引用，请先停用或调整计划")
        running = (
            db.query(TestRun.id)
            .join(TestPlanSuite, TestPlanSuite.plan_id == TestRun.plan_id)
            .filter(TestPlanSuite.suite_id == row.id, TestRun.status.in_(("PENDING", "RUNNING")))
            .first()
        )
        if running:
            raise conflict("该套件正被执行中的测试计划使用，等待执行完成后再删除")
    elif resource_type == "test_plan":
        if db.query(TestRun.id).filter(
            TestRun.plan_id == row.id, TestRun.status.in_(("PENDING", "RUNNING")),
        ).first():
            raise conflict("测试计划正处于执行中，完成运行后再删除")
    elif resource_type == "test_report" and row.status == "GENERATING":
        raise conflict("测试报告仍在生成中，完成生成后再删除")


def _unique_conflict(db: Session, resource_type: str, row: SoftDeleteBase) -> dict[str, Any] | None:
    query = None
    if resource_type == "user":
        query = db.query(User).filter(User.username == row.username)
    elif resource_type == "organization":
        query = db.query(Organization).filter(Organization.name == row.name)
    elif resource_type == "mock_service":
        query = db.query(MockService).filter(
            MockService.project_id == row.project_id, MockService.service_key == row.service_key,
        )
    elif resource_type == "mock_endpoint":
        query = db.query(MockEndpoint).filter(
            MockEndpoint.mock_service_id == row.mock_service_id,
            MockEndpoint.method == row.method, MockEndpoint.path == row.path,
        )
    elif resource_type == "mock_scenario":
        query = db.query(MockScenario).filter(
            MockScenario.mock_endpoint_id == row.mock_endpoint_id,
            MockScenario.scenario_key == row.scenario_key,
        )
    elif resource_type == "test_case":
        query = db.query(TestCase).filter(TestCase.project_id == row.project_id, TestCase.name == row.name)
    elif resource_type == "test_point":
        query = db.query(TestPoint).filter(TestPoint.project_id == row.project_id, TestPoint.name == row.name)
    elif resource_type == "api_module":
        query = db.query(ApiModule).filter(ApiModule.project_id == row.project_id, ApiModule.name == row.name)
    elif resource_type == "api_interface":
        query = db.query(ApiInterface).filter(
            ApiInterface.project_id == row.project_id,
            ApiInterface.method == row.method,
            ApiInterface.path == row.path,
        )
    elif resource_type == "api_relation":
        query = db.query(ApiRelation).filter(
            ApiRelation.source_api_id == row.source_api_id,
            ApiRelation.target_api_id == row.target_api_id,
            ApiRelation.relation_type == row.relation_type,
            ApiRelation.variable_name == row.variable_name,
        )
    elif resource_type == "test_scope":
        query = db.query(TestScopeNode).filter(
            TestScopeNode.project_id == row.project_id,
            TestScopeNode.direction == row.direction,
            TestScopeNode.parent_id == row.parent_id,
            TestScopeNode.name == row.name,
        )
    elif resource_type == "business_domain":
        query = db.query(BusinessDomain).filter(
            BusinessDomain.project_id == row.project_id, BusinessDomain.name == row.name,
        )
    elif resource_type == "business_flow":
        query = db.query(BusinessFlow).filter(
            BusinessFlow.domain_id == row.domain_id, BusinessFlow.name == row.name,
        )
    elif resource_type == "business_action":
        query = db.query(BusinessAction).filter(
            BusinessAction.flow_id == row.flow_id, BusinessAction.action_key == row.action_key,
        )
    elif resource_type == "business_variable":
        query = db.query(BusinessVariable).filter(
            BusinessVariable.action_id == row.action_id,
            BusinessVariable.direction == row.direction,
            BusinessVariable.name == row.name,
        )
    elif resource_type == "business_state":
        query = db.query(BusinessState).filter(
            BusinessState.action_id == row.action_id, BusinessState.entity == row.entity,
        )
    elif resource_type == "business_api_mapping":
        query = db.query(BusinessApiMapping).filter(
            BusinessApiMapping.binding_id == row.binding_id,
            BusinessApiMapping.direction == row.direction,
            BusinessApiMapping.business_variable == row.business_variable,
        )
    elif resource_type == "business_binding" and row.is_default:
        query = db.query(BusinessBinding).filter(
            BusinessBinding.action_id == row.action_id,
            BusinessBinding.binding_type == row.binding_type,
            BusinessBinding.is_default.is_(True),
        )
    elif resource_type == "test_suite":
        query = db.query(TestSuite).filter(TestSuite.project_id == row.project_id, TestSuite.name == row.name)
    elif resource_type == "test_plan":
        query = db.query(TestPlan).filter(TestPlan.project_id == row.project_id, TestPlan.name == row.name)
    elif resource_type == "web_page":
        query = db.query(PageObject).filter(PageObject.project_id == row.project_id, PageObject.name == row.name)
    elif resource_type == "test_strategy":
        query = db.query(TestStrategy).filter(
            TestStrategy.project_id == row.project_id, TestStrategy.name == row.name,
        )
    elif resource_type == "test_data_asset":
        query = db.query(TestDataAsset).filter(
            TestDataAsset.project_id == row.project_id, TestDataAsset.name == row.name,
        )
    elif resource_type == "data_provider":
        query = db.query(DataProvider).filter(
            DataProvider.project_id == row.project_id, DataProvider.name == row.name,
        )
    elif resource_type == "fixture":
        query = db.query(Fixture).filter(
            Fixture.project_id == row.project_id, Fixture.fixture_key == row.fixture_key,
        )
    elif resource_type == "data_pool":
        query = db.query(DataPool).filter(
            DataPool.project_id == row.project_id, DataPool.pool_key == row.pool_key,
        )
    elif resource_type == "target_database_connection":
        query = db.query(TargetDatabaseConnection).filter(
            TargetDatabaseConnection.project_id == row.project_id,
            TargetDatabaseConnection.environment_id == row.environment_id,
            TargetDatabaseConnection.name == row.name,
        )
    elif resource_type == "automation_integration":
        query = db.query(AutomationIntegrationConfig).filter(
            or_(
                (AutomationIntegrationConfig.project_id == row.project_id)
                & (AutomationIntegrationConfig.name == row.name),
                AutomationIntegrationConfig.callback_key == row.callback_key,
            ),
        )
    elif resource_type == "automation_project":
        query = db.query(AutomationProject).filter(
            AutomationProject.project_id == row.project_id, AutomationProject.name == row.name,
        )
    elif resource_type == "model_configuration":
        query = db.query(ModelConfiguration).filter(ModelConfiguration.domain_id == row.domain_id)
    elif resource_type == "project_member":
        query = db.query(ProjectMember).filter(
            ProjectMember.project_id == row.project_id, ProjectMember.user_id == row.user_id,
        )
    elif resource_type == "organization_member":
        query = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == row.organization_id,
            OrganizationMember.user_id == row.user_id,
        )
    elif resource_type == "project_outbound_target":
        query = db.query(ProjectOutboundTarget).filter(
            ProjectOutboundTarget.project_id == row.project_id,
            ProjectOutboundTarget.scheme == row.scheme,
            ProjectOutboundTarget.host == row.host,
            ProjectOutboundTarget.port == row.port,
        )
    elif resource_type == "test_case_data":
        query = db.query(TestCaseData).filter(
            TestCaseData.test_case_id == row.test_case_id, TestCaseData.name == row.name,
        )
    elif resource_type == "test_suite_case":
        query = db.query(TestSuiteCase).filter(
            TestSuiteCase.suite_id == row.suite_id, TestSuiteCase.test_case_id == row.test_case_id,
        )
    elif resource_type == "test_plan_suite":
        query = db.query(TestPlanSuite).filter(
            TestPlanSuite.plan_id == row.plan_id, TestPlanSuite.suite_id == row.suite_id,
        )
    elif resource_type == "security_scan_profile" and row.code:
        query = db.query(SecurityScanProfile).filter(SecurityScanProfile.code == row.code)
    elif resource_type == "security_strategy":
        query = db.query(SecurityStrategy).filter(
            SecurityStrategy.project_id == row.project_id,
            SecurityStrategy.strategy_key == row.strategy_key,
        )
    elif resource_type == "environment":
        query = db.query(Environment).filter(Environment.name == row.name)
    if query is None:
        return None
    match = query.filter(query.column_descriptions[0]["entity"].id != row.id).first()
    if match is None and resource_type == "fixture" and row.scope == "GLOBAL":
        match = (
            db.query(Fixture)
            .filter(Fixture.fixture_key == row.fixture_key, Fixture.scope == "GLOBAL", Fixture.id != row.id)
            .first()
        )
    if match is None and resource_type == "mock_scenario" and row.is_default:
        match = (
            db.query(MockScenario)
            .filter(MockScenario.mock_endpoint_id == row.mock_endpoint_id,
                    MockScenario.is_default.is_(True), MockScenario.id != row.id)
            .first()
        )
    if match is None:
        return None
    return {"resource_type": resource_type, "id": match.id, "display_name": _resource_name(match)}


def _dependency_restore_conflict(db: Session, resource_type: str, row: SoftDeleteBase) -> str | None:
    """Require direct dependencies to be active before restoring the original row."""
    def check_active(model: type[Any], dependency_id: int | None, label: str) -> str | None:
        if dependency_id is None:
            return None
        dependency = (
            db.query(model).execution_options(include_deleted=True)
            .filter(model.id == dependency_id).first()
        )
        if dependency is None:
            return f"关联的{label}已不存在，无法恢复原关联"
        if getattr(dependency, "deleted_at", None) is not None:
            return f"关联的{label}仍在回收站，请先恢复该依赖"
        return None

    if resource_type == "agent_session":
        if row.task_run_id is not None:
            return "任务运行关联的 Agent 会话属于执行证据，不能恢复为普通对话资源"
        if db.get(Project, row.project_id) is None:
            return "所属项目已移入回收站，无法恢复会话"
    elif resource_type == "project":
        if row.organization_id is not None and db.get(Organization, row.organization_id) is None:
            return "所属组织已不存在，无法恢复项目"
        owner = db.get(User, row.owner_id)
        if owner is None or not owner.is_active:
            return "项目负责人账号已删除或停用，请先恢复并启用负责人账号或转移负责人"
    elif resource_type in {"test_data_asset", "data_provider"}:
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复原始数据"
        if resource_type == "test_data_asset" and row.fixture_id is not None:
            fixture = db.get(Fixture, row.fixture_id)
            if fixture is None:
                return "登记该测试数据的 Fixture 已不存在，无法恢复原关联"
        if resource_type == "data_provider" and str(row.provider_type).startswith("DATABASE"):
            connection_id = (row.config_json or {}).get("connection_id")
            connection = db.get(TargetDatabaseConnection, connection_id) if connection_id is not None else None
            if connection is None or connection.project_id != row.project_id:
                return "关联的目标数据库连接已不存在或不属于该项目，无法恢复 Provider"
            if not connection.enabled:
                return "关联的目标数据库连接已停用，请先恢复连接配置后再恢复 Provider"
    elif resource_type == "fixture":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复 Fixture"
        for dependency in db.query(FixtureDependency).filter(FixtureDependency.fixture_id == row.id).all():
            if db.get(Fixture, dependency.depends_on_fixture_id) is None:
                return "依赖的 Fixture 已不存在或仍在回收站，请先恢复依赖"
    elif resource_type == "data_pool":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复数据池"
        if row.asset_id is not None:
            return check_active(TestDataAsset, row.asset_id, "测试数据资产")
    elif resource_type == "data_pool_item":
        return check_active(DataPool, row.pool_id, "数据池")
    elif resource_type == "target_database_connection":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复数据库连接"
        if db.get(Environment, row.environment_id) is None:
            return "绑定环境已不存在或仍在回收站，请先恢复环境"
    elif resource_type == "automation_integration":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复接入配置"
    elif resource_type == "automation_project":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复自动化项目"
        return check_active(AutomationIntegrationConfig, row.integration_config_id, "云效接入配置")
    elif resource_type in {
        "notification_channel", "web_auth_profile", "security_scan_target",
        "security_scan_auth_profile", "project_outbound_target", "project_member",
    }:
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复"
        if resource_type == "web_auth_profile" and db.get(Environment, row.environment_id) is None:
            return "绑定环境已不存在或仍在回收站，请先恢复环境"
        if resource_type == "security_scan_target" and row.environment_id is not None and db.get(Environment, row.environment_id) is None:
            return "绑定环境已不存在或仍在回收站，请先恢复环境"
        if resource_type == "project_member":
            user = db.get(User, row.user_id)
            if user is None or not user.is_active:
                return "成员账号已删除或停用，请先恢复并启用账号"
    elif resource_type == "security_scan_profile":
        if row.project_id is not None and db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复扫描策略"
    elif resource_type == "organization_member":
        if db.get(Organization, row.organization_id) is None:
            return "所属组织已不存在，无法恢复成员"
        user = db.get(User, row.user_id)
        if user is None or not user.is_active:
            return "成员账号已删除或停用，请先恢复并启用账号"
    elif resource_type == "notification":
        if db.get(User, row.user_id) is None:
            return "收件人账号已不存在，无法恢复通知"
    elif resource_type in {"test_step", "test_assertion", "test_case_precondition", "test_case_data"}:
        message = check_active(TestCase, row.test_case_id, "测试用例")
        if message:
            return message
        if resource_type == "test_assertion" and row.step_id is not None:
            return check_active(TestStep, row.step_id, "测试步骤")
    elif resource_type == "test_suite_case":
        message = check_active(TestSuite, row.suite_id, "测试套件")
        if message:
            return message
        return check_active(TestCase, row.test_case_id, "测试用例")
    elif resource_type == "test_plan_suite":
        message = check_active(TestPlan, row.plan_id, "测试计划")
        if message:
            return message
        return check_active(TestSuite, row.suite_id, "测试套件")
    elif resource_type == "security_strategy":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复安全策略"
    elif resource_type == "security_rule":
        message = check_active(SecurityStrategy, row.strategy_id, "安全策略")
        if message:
            return message
    elif resource_type == "mock_service":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复 Mock 服务"
    elif resource_type == "mock_endpoint":
        message = check_active(MockService, row.mock_service_id, "Mock 服务")
        if message:
            return message
    elif resource_type == "mock_scenario":
        message = check_active(MockEndpoint, row.mock_endpoint_id, "Mock 接口")
        if message:
            return message
    elif resource_type == "test_case":
        checks = (
            (TestPoint, getattr(row, "test_point_id", None), "测试点"),
            (ApiInterface, getattr(row, "api_id", None), "API 接口"),
            (BusinessFlow, getattr(row, "business_flow_id", None), "业务流程"),
            (BusinessAction, getattr(row, "business_action_id", None), "业务动作"),
        )
        for model, dependency_id, label in checks:
            if dependency_id is None:
                continue
            dependency = (
                db.query(model).execution_options(include_deleted=True)
                .filter(model.id == dependency_id).first()
            )
            if dependency is None:
                return f"关联的{label}已不存在，无法恢复原关联"
            if getattr(dependency, "deleted_at", None) is not None:
                return f"关联的{label}仍在回收站，请先恢复该依赖"
    elif resource_type == "test_point":
        for model, dependency_id, label in (
            (BusinessFlow, getattr(row, "business_flow_id", None), "业务流程"),
            (BusinessAction, getattr(row, "business_action_id", None), "业务动作"),
        ):
            message = check_active(model, dependency_id, label)
            if message:
                return message
    elif resource_type in {"test_report", "bug"}:
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复原始数据"
    elif resource_type == "business_domain":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复业务域"
    elif resource_type == "business_flow":
        return check_active(BusinessDomain, row.domain_id, "业务域")
    elif resource_type == "business_action":
        return check_active(BusinessFlow, row.flow_id, "业务流程")
    elif resource_type == "business_rule":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复业务规则"
        for model, dependency_id, label in (
            (BusinessFlow, row.flow_id, "业务流程"),
            (BusinessAction, row.action_id, "业务动作"),
        ):
            message = check_active(model, dependency_id, label)
            if message:
                return message
    elif resource_type in {"business_variable", "business_state", "business_precondition"}:
        return check_active(BusinessAction, row.action_id, "业务动作")
    elif resource_type == "business_binding":
        message = check_active(BusinessAction, row.action_id, "业务动作")
        if message:
            return message
        if row.binding_type == "API" and row.api_id is not None:
            return check_active(ApiInterface, row.api_id, "API 接口")
        if row.binding_type == "WEB":
            web_case_id = (row.config_json or {}).get("web_case_id")
            if web_case_id is not None:
                message = check_active(TestCase, web_case_id, "Web 测试用例")
                if message:
                    return message
                from app.features.web_testing.models import WebCase
                if db.get(WebCase, web_case_id) is None:
                    return "绑定的 Web 用例资源已不存在，无法恢复"
    elif resource_type == "business_api_mapping":
        return check_active(BusinessBinding, row.binding_id, "业务绑定")
    elif resource_type == "business_variable_ref":
        for model, dependency_id, label in (
            (BusinessFlow, row.flow_id, "业务流程"),
            (BusinessAction, row.source_action_id, "来源业务动作"),
            (BusinessAction, row.target_action_id, "目标业务动作"),
            (BusinessVariable, row.source_variable_id, "来源业务变量"),
            (BusinessVariable, row.target_variable_id, "目标业务变量"),
        ):
            message = check_active(model, dependency_id, label)
            if message:
                return message
    elif resource_type == "test_suite":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复测试套件"
    elif resource_type == "test_plan":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复测试计划"
        suite_ids = (
            db.query(TestPlanSuite.suite_id)
            .filter(TestPlanSuite.plan_id == row.id)
            .all()
        )
        for (suite_id,) in suite_ids:
            message = check_active(TestSuite, suite_id, "测试套件")
            if message:
                return message
    elif resource_type == "web_page" and db.get(Project, row.project_id) is None:
        return "所属项目已不存在，无法恢复页面对象"
    elif resource_type == "test_strategy" and db.get(Project, row.project_id) is None:
        return "所属项目已不存在，无法恢复测试策略"
    elif resource_type == "knowledge_base":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复知识库"
    elif resource_type == "knowledge_document":
        if db.get(Project, row.project_id) is None:
            return "所属项目已不存在，无法恢复知识文档"
        return check_active(KnowledgeBase, row.base_id, "知识库")
    elif resource_type == "agent_definition":
        skills = db.query(SkillDefinition).filter(SkillDefinition.key.in_(row.skill_keys or [])).all()
        if len(skills) != len(set(row.skill_keys or [])):
            return "该 Agent 关联的 Skill 已不存在或仍在回收站，请先恢复 Skill"
        if row.is_enabled and any(not skill.is_enabled for skill in skills):
            return "该 Agent 仍为启用状态，但关联 Skill 已停用；请先启用 Skill 再恢复 Agent"
        for child_id in row.child_agent_ids or []:
            message = check_active(AgentDefinition, child_id, "子 Agent")
            if message:
                return message
    elif resource_type == "skill_definition":
        from app.mcp.models import MCPServer

        for key in row.mcp_tool_keys_json or []:
            try:
                _, server_id, tool_name = str(key).split(":", 2)
                server = db.get(MCPServer, int(server_id))
            except (TypeError, ValueError):
                server = None
                tool_name = ""
            discovered = next(
                (item for item in (server.discovered_tools_json or []) if item.get("name") == tool_name), None,
            ) if server else None
            if (
                server is None or tool_name not in (server.approved_tools_json or [])
                or discovered is None or (discovered.get("annotations") or {}).get("readOnlyHint") is not True
            ):
                return "原关联 MCP 工具不存在或审批状态已变化，无法恢复 Skill 配置"
    elif resource_type == "test_scope" and row.parent_id is not None:
        parent = db.query(TestScopeNode).execution_options(include_deleted=True).filter_by(id=row.parent_id).first()
        if parent is not None and parent.deleted_at is not None:
            return "父范围仍在回收站，请先恢复父范围"
    elif resource_type == "api_module" and row.parent_id is not None:
        parent = db.query(ApiModule).execution_options(include_deleted=True).filter_by(id=row.parent_id).first()
        if parent is not None and parent.deleted_at is not None:
            return "父模块仍在回收站，请先恢复父模块"
    elif resource_type == "api_interface" and row.module_id is not None:
        module = db.query(ApiModule).execution_options(include_deleted=True).filter_by(id=row.module_id).first()
        if module is None:
            return "原所属 API 模块不存在，无法恢复原模块关联"
        if module.deleted_at is not None:
            return "原所属 API 模块仍在回收站，请先恢复模块"
    elif resource_type == "api_relation":
        for interface_id in (row.source_api_id, row.target_api_id):
            interface = (
                db.query(ApiInterface).execution_options(include_deleted=True)
                .filter_by(id=interface_id).first()
            )
            if interface is None or interface.deleted_at is not None:
                return "关联接口不存在或仍在回收站，请先恢复接口"
    return None


def _audit(
    db: Session, *, event_type: str, resource_type: str, resource_id: int,
    actor_id: int | None, project_id: int | None, organization_id: int | None,
    batch_id: str | None, reason: str | None, item_id: int | None = None,
    result: str = "SUCCEEDED", detail: dict[str, Any] | None = None,
) -> LifecycleAuditEvent:
    event = LifecycleAuditEvent(
        event_type=event_type, result=result, resource_type=resource_type,
        resource_id=str(resource_id), recycle_bin_item_id=item_id,
        project_id=project_id, organization_id=organization_id, actor_id=actor_id,
        deletion_batch_id=batch_id, reason=reason, detail=detail or {},
    )
    db.add(event)
    return event


def soft_delete_object(
    db: Session, resource_type: str, row: SoftDeleteBase, *, actor: User,
    reason: str | None = None, batch_id: str | None = None,
) -> RecycleBinItem:
    """Record the deletion and mark one resource without mutating its associations."""
    _assert_deletable(db, resource_type, row, actor)
    project_id = row.id if resource_type == "project" else _row_project_id(db, row)
    project = row if resource_type == "project" else (db.get(Project, project_id) if project_id is not None else None)
    batch_id = batch_id or str(uuid4())
    deleted_at = _now()
    row.deleted_at = deleted_at
    row.deleted_by = actor.id
    row.deletion_reason = (reason or "").strip()[:500] or None
    row.deletion_batch_id = batch_id
    if resource_type == "user":
        from app.core.security.auth import invalidate_user_tokens

        invalidate_user_tokens(db, row)
    item = RecycleBinItem(
        resource_type=resource_type, resource_id=str(row.id),
        display_name=_resource_name(row), project_id=project_id,
        organization_id=(row.id if resource_type == "organization" else
                         project.organization_id if project else getattr(row, "organization_id", None)),
        deleted_by=actor.id, deleted_by_name=actor.username,
        deleted_at=deleted_at, deletion_reason=row.deletion_reason,
        deletion_batch_id=batch_id, deletion_status="ACTIVE", metadata_json=_resource_meta(row),
    )
    db.add(item)
    db.flush()
    _audit(
        db, event_type="DELETE", resource_type=resource_type, resource_id=row.id,
        actor_id=actor.id, project_id=item.project_id, organization_id=item.organization_id,
        batch_id=batch_id, reason=item.deletion_reason, item_id=item.id,
        detail={"display_name": item.display_name},
    )
    return item


def clear_soft_delete(db: Session, resource_type: str, row: SoftDeleteBase, actor: User) -> None:
    """重新添加已删除成员时恢复原行，避免再插入一条重复关系。"""
    if row.deleted_at is None:
        return
    item = (
        db.query(RecycleBinItem)
        .filter(
            RecycleBinItem.resource_type == resource_type,
            RecycleBinItem.resource_id == str(row.id),
            RecycleBinItem.deletion_status == "ACTIVE",
        )
        .order_by(RecycleBinItem.id.desc())
        .first()
    )
    if item is not None:
        restore_recycle_item(db, item.id, actor)
        return
    row.deleted_at = None
    row.deleted_by = None
    row.deletion_reason = None
    row.deletion_batch_id = None


def _authorize_delete(db: Session, resource_type: str, row: SoftDeleteBase, actor: User, row_project_id: int | None) -> None:
    """按资源归属校验删除权限。平台级和组织级资源不能套用项目回收站规则。"""
    if resource_type == "notification":
        if row.user_id != actor.id and not is_platform_admin(actor):
            raise not_found("资源不存在")
        return
    if resource_type == "organization_member":
        role = organization_role(db, row.organization_id, actor)
        if not is_platform_admin(actor) and role not in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}:
            raise not_found("资源不存在")
        return
    if resource_type == "model_configuration":
        if not is_platform_admin(actor):
            raise forbidden("需要平台管理员权限")
        return
    if resource_type == "organization":
        if not is_platform_admin(actor):
            raise forbidden("需要平台管理员权限")
        return
    if resource_type == "project" and not has_project_role(
        project_role_for(db, row, actor), PROJECT_ROLE_OWNER,
    ):
        raise forbidden("只有项目负责人或平台管理员可以删除项目")
    _scope_access(db, row_project_id, actor, write=True)


def delete_resource(
    db: Session, resource_type: str, resource_id: int, *, actor: User,
    project_id: int | None = None, reason: str | None = None, batch_id: str | None = None,
) -> tuple[RecycleBinItem, bool]:
    """Idempotent single-resource operation used by legacy DELETE routes and bulk API."""
    if resource_type == "organization":
        raise bad_request("组织删除必须使用组织管理接口")
    model = _model(resource_type)
    row = (
        db.query(model).execution_options(include_deleted=True)
        .filter(model.id == resource_id).with_for_update().first()
    )
    if row is None:
        raise not_found("资源不存在")
    row_project_id = row.id if resource_type == "project" else _row_project_id(db, row)
    if project_id is not None and row_project_id != project_id:
        raise not_found("资源不存在")
    _authorize_delete(db, resource_type, row, actor, row_project_id)
    if resource_type != "project" and row_project_id is not None and db.get(Project, row_project_id) is None:
        raise conflict("所属项目已移入回收站，请先恢复项目后再操作其资产")
    if row.deleted_at is not None:
        existing = (
            db.query(RecycleBinItem)
            .filter(
                RecycleBinItem.resource_type == resource_type,
                RecycleBinItem.resource_id == str(resource_id),
                RecycleBinItem.deletion_status == "ACTIVE",
            )
            .order_by(RecycleBinItem.id.desc()).first()
        )
        if existing is None:
            raise conflict("资源已删除，但回收站记录缺失，请联系管理员")
        _audit(
            db, event_type="DELETE", resource_type=resource_type, resource_id=resource_id,
            actor_id=actor.id, project_id=existing.project_id, organization_id=existing.organization_id,
            batch_id=existing.deletion_batch_id, reason=reason, item_id=existing.id,
            detail={"already_deleted": True},
        )
        db.commit()
        return existing, True
    item = soft_delete_object(db, resource_type, row, actor=actor, reason=reason, batch_id=batch_id)
    db.commit()
    return item, False


def batch_delete(
    db: Session, resource_type: str, project_id: int | None, ids: list[int], *,
    actor: User, reason: str | None,
) -> dict[str, Any]:
    if resource_type == "organization":
        raise bad_request("组织删除必须使用组织管理接口")
    if resource_type in {"organization_member", "notification", "model_configuration"} and project_id is None:
        if resource_type == "model_configuration" and not is_platform_admin(actor):
            raise forbidden("需要平台管理员权限")
    elif resource_type != "project" or project_id is not None:
        _scope_access(db, project_id, actor, write=True)
    batch_id = str(uuid4())
    receipts: list[dict[str, Any]] = []
    for resource_id in ids:
        try:
            if project_id is None:
                model = _model(resource_type)
                scoped_row = (
                    db.query(model).execution_options(include_deleted=True)
                    .filter(model.id == resource_id).first()
                )
                if scoped_row is not None and _row_project_id(db, scoped_row) is not None:
                    raise not_found("资源不存在")
            item, already = delete_resource(
                db, resource_type, resource_id, actor=actor,
                project_id=project_id, reason=reason, batch_id=batch_id,
            )
            receipts.append({
                "id": resource_id, "succeeded": True,
                "recycle_bin_item_id": item.id, "already_done": already,
            })
        except HTTPException as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            message = detail.get("message") if detail else str(exc.detail)
            _audit(
                db, event_type="DELETE", resource_type=resource_type, resource_id=resource_id,
                actor_id=actor.id, project_id=project_id, organization_id=None,
                batch_id=batch_id, reason=reason, result="FAILED",
                detail={"status_code": exc.status_code, "error": message},
            )
            db.commit()
            receipts.append({
                "id": resource_id, "succeeded": False,
                "error_code": "ERR_CONFLICT" if exc.status_code == 409 else "ERR_DELETE_FAILED",
                "error": message,
                "meta": detail.get("meta") if detail else None,
            })
        except IntegrityError:
            db.rollback()
            _audit(
                db, event_type="DELETE", resource_type=resource_type, resource_id=resource_id,
                actor_id=actor.id, project_id=project_id, organization_id=None,
                batch_id=batch_id, reason=reason, result="FAILED",
                detail={"error": "资源状态已变化，请刷新后重试"},
            )
            db.commit()
            receipts.append({
                "id": resource_id, "succeeded": False,
                "error_code": "ERR_CONFLICT", "error": "资源状态已变化，请刷新后重试",
            })
    # The per-item records remain independent while sharing a correlation ID in request context.
    # Each item commits its own generated batch id so restore receipts remain individually clear.
    return {
        "succeeded": sum(1 for item in receipts if item["succeeded"]),
        "failed": sum(1 for item in receipts if not item["succeeded"]),
        "items": receipts,
    }


def _assert_item_access(db: Session, item: RecycleBinItem, actor: User, *, write: bool = False) -> None:
    if item.resource_type == "notification" and item.deleted_by == actor.id:
        return
    if item.resource_type == "organization_member":
        role = organization_role(db, item.organization_id, actor) if item.organization_id else None
        if not is_platform_admin(actor) and role not in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}:
            raise not_found("回收站记录不存在")
        return
    if item.resource_type == "model_configuration":
        if not is_platform_admin(actor):
            raise not_found("回收站记录不存在")
        return
    if item.resource_type == "organization":
        if not is_platform_admin(actor):
            raise not_found("回收站记录不存在")
        return
    _scope_access(db, item.project_id, actor, write=write)
    if item.resource_type == "project" and write and not is_platform_admin(actor):
        project = db.query(Project).execution_options(include_deleted=True).filter_by(
            id=int(item.resource_id),
        ).first()
        if project is None or not has_project_role(
            project_role_for(db, project, actor), PROJECT_ROLE_OWNER,
        ):
            raise not_found("回收站记录不存在")


def _item_conflict(db: Session, item: RecycleBinItem) -> str | None:
    if item.deletion_status != "ACTIVE":
        return None
    try:
        model = _model(item.resource_type)
    except HTTPException:
        return "资源类型当前不支持恢复"
    row = db.query(model).execution_options(include_deleted=True).filter(model.id == int(item.resource_id)).first()
    if row is None:
        return "原始业务记录不存在"
    conflict_row = _unique_conflict(db, item.resource_type, row)
    if conflict_row:
        return f"名称或接口键已被 {conflict_row['display_name']}（#{conflict_row['id']}）占用"
    return None


def _item_response(db: Session, item: RecycleBinItem) -> dict[str, Any]:
    return {
        "id": item.id, "resource_type": item.resource_type, "resource_id": item.resource_id,
        "display_name": item.display_name, "project_id": item.project_id,
        "organization_id": item.organization_id, "deleted_by": item.deleted_by,
        "deleted_by_name": item.deleted_by_name,
        "deleted_at": item.deleted_at, "deletion_reason": item.deletion_reason,
        "deletion_batch_id": item.deletion_batch_id, "deletion_status": item.deletion_status,
        "can_restore": item.deletion_status == "ACTIVE",
        "restore_conflict": _item_conflict(db, item),
        "last_restore_error": item.last_restore_error,
        "metadata": item.metadata_json or {},
    }


def _project_purge_references(db: Session, project_id: int) -> list[str]:
    """Count every FK row that a physical project purge could cascade-delete."""
    bind = db.get_bind()
    inspector = sa_inspect(bind)
    quote = bind.dialect.identifier_preparer.quote
    references: list[str] = []
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            target_columns = foreign_key.get("referred_columns") or []
            source_columns = foreign_key.get("constrained_columns") or []
            if foreign_key.get("referred_table") != "project" or "id" not in target_columns:
                continue
            source_column = source_columns[target_columns.index("id")]
            count = db.execute(text(
                f"SELECT count(*) FROM {quote(table_name)} WHERE {quote(source_column)} = :project_id"
            ), {"project_id": project_id}).scalar_one()
            if count:
                references.append(f"{table_name}: {count}")
    return references


def _user_purge_references(db: Session, user_id: int) -> list[str]:
    """Never cascade-delete user-owned assets or immutable attribution during a purge."""
    bind = db.get_bind()
    inspector = sa_inspect(bind)
    quote = bind.dialect.identifier_preparer.quote
    references: list[str] = []
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            target_columns = foreign_key.get("referred_columns") or []
            source_columns = foreign_key.get("constrained_columns") or []
            if foreign_key.get("referred_table") != "user" or "id" not in target_columns:
                continue
            source_column = source_columns[target_columns.index("id")]
            count = db.execute(text(
                f"SELECT count(*) FROM {quote(table_name)} WHERE {quote(source_column)} = :user_id"
            ), {"user_id": user_id}).scalar_one()
            if count:
                references.append(f"{table_name}.{source_column}: {count}")
    return references


def _agent_session_purge_references(db: Session, session_id: int) -> list[str]:
    """Block physical clearing while message, summary, or test trace rows reference a session."""
    bind = db.get_bind()
    inspector = sa_inspect(bind)
    quote = bind.dialect.identifier_preparer.quote
    references: list[str] = []
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            target_columns = foreign_key.get("referred_columns") or []
            source_columns = foreign_key.get("constrained_columns") or []
            if foreign_key.get("referred_table") != "agent_session" or "id" not in target_columns:
                continue
            source_column = source_columns[target_columns.index("id")]
            count = db.execute(text(
                f"SELECT count(*) FROM {quote(table_name)} WHERE {quote(source_column)} = :session_id"
            ), {"session_id": session_id}).scalar_one()
            if count:
                references.append(f"{table_name}.{source_column}: {count}")
    return references


def list_recycle_bin(
    db: Session, actor: User, *, project_id: int | None = None,
    organization_id: int | None = None, resource_type: str | None = None,
    deleted_by: int | None = None, date_from: datetime | None = None,
    date_to: datetime | None = None, keyword: str | None = None,
    page: int = 1, page_size: int = 50, sort: str = "deleted_at", order: str = "desc",
) -> dict[str, Any]:
    visible_projects: list[int] | None = None
    if project_id is not None:
        _scope_access(db, project_id, actor, write=False)
    elif not is_platform_admin(actor):
        visible_projects = accessible_project_ids(db, actor, include_deleted=True) or []
    if sort not in {"deleted_at", "display_name", "resource_type"} or order not in {"asc", "desc"}:
        raise bad_request("排序参数无效")
    query = db.query(RecycleBinItem).filter(RecycleBinItem.deletion_status == "ACTIVE")
    if project_id is not None:
        query = query.filter(RecycleBinItem.project_id == project_id)
    elif visible_projects is not None:
        query = query.filter(or_(
            RecycleBinItem.project_id.in_(visible_projects or [-1]),
            (RecycleBinItem.resource_type == "notification") & (RecycleBinItem.deleted_by == actor.id),
        ))
    if organization_id is not None:
        query = query.filter(RecycleBinItem.organization_id == organization_id)
    if resource_type:
        query = query.filter(RecycleBinItem.resource_type == resource_type)
    if deleted_by is not None:
        query = query.filter(RecycleBinItem.deleted_by == deleted_by)
    if date_from is not None:
        query = query.filter(RecycleBinItem.deleted_at >= date_from)
    if date_to is not None:
        query = query.filter(RecycleBinItem.deleted_at <= date_to)
    if keyword:
        query = query.filter(RecycleBinItem.display_name.ilike(f"%{keyword.strip()}%"))
    total = query.count()
    column = getattr(RecycleBinItem, sort)
    ordered = column.desc() if order == "desc" else column.asc()
    rows = query.order_by(ordered, RecycleBinItem.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_item_response(db, row) for row in rows], "total": total, "page": page, "page_size": page_size}


def get_recycle_item(db: Session, item_id: int, actor: User) -> dict[str, Any]:
    item = db.get(RecycleBinItem, item_id)
    if item is None:
        raise not_found("回收站记录不存在")
    _assert_item_access(db, item, actor)
    model = _model(item.resource_type)
    row = db.query(model).execution_options(include_deleted=True).filter(model.id == int(item.resource_id)).first()
    data = None
    if row is not None:
        data = {}
        for column in model.__table__.columns:
            value = getattr(row, column.name)
            if item.resource_type == "user" and column.name == "hashed_password":
                value = None
            elif item.resource_type == "mock_service" and column.name == "runtime_token_hash":
                value = None
            elif item.resource_type == "mcp_server" and column.name == "auth_secret_encrypted":
                value = None
            elif column.name in {
                "password_encrypted", "access_token_encrypted", "callback_secret_encrypted",
                "secret_encrypted", "credential_encrypted", "api_key_encrypted",
            }:
                value = None
            elif column.name in {
                "value_json", "payload_json", "config_json", "input_snapshot", "output_snapshot",
                "body_snapshot", "response_body_snapshot", "response_body", "response_template",
                "default_headers",
            }:
                value = SensitiveDataMasker.mask_body(value)
            data[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return {**_item_response(db, item), "resource_data": data}


def restore_recycle_item(db: Session, item_id: int, actor: User) -> dict[str, Any]:
    item = db.get(RecycleBinItem, item_id)
    if item is None:
        raise not_found("回收站记录不存在")
    _assert_item_access(db, item, actor, write=True)
    if item.deletion_status == "RESTORED":
        _audit(
            db, event_type="RESTORE", resource_type=item.resource_type,
            resource_id=int(item.resource_id), actor_id=actor.id,
            project_id=item.project_id, organization_id=item.organization_id,
            batch_id=item.deletion_batch_id, reason=item.deletion_reason,
            item_id=item.id, detail={"already_restored": True},
        )
        db.commit()
        return {"id": item.id, "succeeded": True, "already_done": True}
    if item.deletion_status != "ACTIVE":
        raise conflict("该数据已被永久清理，无法恢复")
    model = _model(item.resource_type)
    row = (
        db.query(model).execution_options(include_deleted=True)
        .filter(model.id == int(item.resource_id)).with_for_update().first()
    )
    if row is None:
        message = "原始业务记录不存在，回收站记录仍保留供管理员核查"
        item.last_restore_error = message
        _audit(db, event_type="RESTORE_FAILED", resource_type=item.resource_type,
               resource_id=int(item.resource_id), actor_id=actor.id, project_id=item.project_id,
               organization_id=item.organization_id, batch_id=item.deletion_batch_id,
               reason=item.deletion_reason, item_id=item.id, result="FAILED", detail={"error": message})
        db.commit()
        raise conflict(message)
    conflicting = _unique_conflict(db, item.resource_type, row)
    dependency_error = _dependency_restore_conflict(db, item.resource_type, row)
    if dependency_error:
        item.last_restore_error = dependency_error
        _audit(db, event_type="RESTORE_FAILED", resource_type=item.resource_type,
               resource_id=int(item.resource_id), actor_id=actor.id, project_id=item.project_id,
               organization_id=item.organization_id, batch_id=item.deletion_batch_id,
               reason=item.deletion_reason, item_id=item.id, result="FAILED",
               detail={"error": dependency_error})
        db.commit()
        raise conflict(dependency_error)
    if conflicting:
        message = f"恢复冲突：{conflicting['display_name']}（#{conflicting['id']}）占用了相同名称或接口键"
        item.last_restore_error = message
        _audit(db, event_type="RESTORE_FAILED", resource_type=item.resource_type,
               resource_id=int(item.resource_id), actor_id=actor.id, project_id=item.project_id,
               organization_id=item.organization_id, batch_id=item.deletion_batch_id,
               reason=item.deletion_reason, item_id=item.id, result="FAILED",
               detail={"error": message, "conflicting_resource": conflicting})
        db.commit()
        raise HTTPException(status_code=409, detail={"message": message, "meta": {"conflicting_resource": conflicting}})
    if row.deleted_at is None:
        raise conflict("原始记录已恢复，但回收站状态不一致；记录保留供管理员核查")
    try:
        row.deleted_at = None
        row.deleted_by = None
        row.deletion_reason = None
        row.deletion_batch_id = None
        if item.resource_type == "user":
            # Keep revocation monotonic so an old token cannot become valid on restore.
            row.token_version = int(row.token_version or 0) + 1
        item.deletion_status = "RESTORED"
        item.restored_by = actor.id
        item.restored_at = _now()
        item.last_restore_error = None
        _audit(db, event_type="RESTORE", resource_type=item.resource_type,
               resource_id=int(item.resource_id), actor_id=actor.id, project_id=item.project_id,
               organization_id=item.organization_id, batch_id=item.deletion_batch_id,
               reason=item.deletion_reason, item_id=item.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("恢复时发生并发唯一键冲突，请刷新回收站后重试") from exc
    return {"id": item.id, "succeeded": True, "already_done": False}


def batch_restore(db: Session, item_ids: list[int], actor: User) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    items = db.query(RecycleBinItem).filter(RecycleBinItem.id.in_(item_ids)).all() if item_ids else []
    by_item_id = {item.id: item for item in items}

    def restore_rank(item: RecycleBinItem) -> tuple[int, int]:
        ranks = {"organization": 0, "organization_member": 1, "security_strategy": 10,
                 "security_rule": 11, "api_module": 20, "api_interface": 30, "api_relation": 40}
        depth = 0
        if item.resource_type == "api_module":
            row = db.query(ApiModule).execution_options(include_deleted=True).filter_by(
                id=int(item.resource_id),
            ).first()
            parent_id = row.parent_id if row else None
            while parent_id is not None:
                depth += 1
                parent = db.query(ApiModule).execution_options(include_deleted=True).filter_by(
                    id=parent_id,
                ).first()
                parent_id = parent.parent_id if parent else None
        return ranks.get(item.resource_type, 15), depth

    ordered_ids = sorted(item_ids, key=lambda value: (
        restore_rank(by_item_id[value]) if value in by_item_id else (15, 0), item_ids.index(value),
    ))
    for item_id in ordered_ids:
        try:
            result = restore_recycle_item(db, item_id, actor)
            receipts.append({**result, "id": item_id})
        except HTTPException as exc:
            db.rollback()
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            audit_item = db.get(RecycleBinItem, item_id)
            # 409 conflicts are already audited by restore_recycle_item with conflict metadata.
            if exc.status_code != 409:
                _audit(
                    db, event_type="RESTORE", resource_type=audit_item.resource_type if audit_item else "recycle_bin_item",
                    resource_id=int(audit_item.resource_id) if audit_item else item_id,
                    actor_id=actor.id, project_id=audit_item.project_id if audit_item else None,
                    organization_id=audit_item.organization_id if audit_item else None,
                    batch_id=audit_item.deletion_batch_id if audit_item else None,
                    reason=audit_item.deletion_reason if audit_item else None, item_id=item_id,
                    result="FAILED", detail={"status_code": exc.status_code,
                                             "error": detail.get("message", exc.detail) if detail else str(exc.detail)},
                )
                db.commit()
            receipts.append({
                "id": item_id, "succeeded": False,
                "error_code": "ERR_CONFLICT" if exc.status_code == 409 else "ERR_RESTORE_FAILED",
                "error": detail.get("message", exc.detail) if detail else str(exc.detail),
                "meta": detail.get("meta") if detail else None,
            })
        except IntegrityError:
            db.rollback()
            receipts.append({"id": item_id, "succeeded": False,
                             "error_code": "ERR_CONFLICT", "error": "恢复时发生并发冲突，请刷新后重试"})
    return {
        "succeeded": sum(1 for item in receipts if item["succeeded"]),
        "failed": sum(1 for item in receipts if not item["succeeded"]),
        "items": receipts,
    }


def list_lifecycle_audit(db: Session, item_id: int, actor: User) -> list[dict[str, Any]]:
    item = db.get(RecycleBinItem, item_id)
    if item is None:
        raise not_found("回收站记录不存在")
    _assert_item_access(db, item, actor)
    rows = (
        db.query(LifecycleAuditEvent)
        .filter(LifecycleAuditEvent.recycle_bin_item_id == item_id)
        .order_by(LifecycleAuditEvent.created_at.asc(), LifecycleAuditEvent.id.asc()).all()
    )
    return [{
        "id": row.id, "event_type": row.event_type, "result": row.result,
        "resource_type": row.resource_type, "resource_id": row.resource_id,
        "project_id": row.project_id, "actor_id": row.actor_id,
        "deletion_batch_id": row.deletion_batch_id, "reason": row.reason,
        "detail": row.detail or {}, "created_at": row.created_at,
    } for row in rows]


def purge_preview(db: Session, item_id: int, actor: User) -> dict[str, Any]:
    item = db.get(RecycleBinItem, item_id)
    if item is None:
        raise not_found("回收站记录不存在")
    if not is_platform_admin(actor):
        raise forbidden("仅平台管理员可永久清理数据")
    row = db.query(_model(item.resource_type)).execution_options(include_deleted=True).filter_by(id=int(item.resource_id)).first()
    if item.deletion_status != "ACTIVE" or row is None:
        return {"item_id": item.id, "resource_type": item.resource_type, "resource_id": item.resource_id,
                "display_name": item.display_name, "allowed": False,
                "dependencies": ["记录已恢复或原始记录不存在"], "effects": []}
    dependencies: list[str] = []
    effects: list[str] = []
    if item.resource_type == "agent_session":
        references = _agent_session_purge_references(db, row.id)
        if references:
            dependencies.append("会话仍被消息、摘要或测试追溯数据引用，不能级联清理：" + ", ".join(references[:20]))
    elif item.resource_type == "user":
        references = _user_purge_references(db, row.id)
        if references:
            dependencies.append("账号仍被资源归属或操作留痕引用，禁止级联物理清理：" + ", ".join(references[:20]))
        audit_count = db.query(LifecycleAuditEvent.id).filter(
            LifecycleAuditEvent.actor_id == row.id,
        ).count()
        if audit_count:
            dependencies.append(f"不可篡改的生命周期审计仍记录该账号为操作人，共 {audit_count} 条")
    elif item.resource_type == "project":
        references = _project_purge_references(db, row.id)
        if references:
            dependencies.append("项目仍被外键资源或运行证据引用，禁止级联物理清理：" + ", ".join(references[:20]))
        recycle_references = db.query(RecycleBinItem.id).filter(
            RecycleBinItem.project_id == row.id,
            RecycleBinItem.resource_type != "project",
        ).count()
        if recycle_references:
            dependencies.append(f"该项目仍有 {recycle_references} 条其他回收站记录，需先逐项处理")
    elif item.resource_type == "organization":
        project_count = db.query(Project.id).execution_options(include_deleted=True).filter(
            Project.organization_id == row.id,
        ).count()
        member_items = db.query(RecycleBinItem.id).filter(
            RecycleBinItem.organization_id == row.id,
            RecycleBinItem.resource_type == "organization_member",
            RecycleBinItem.deletion_status == "ACTIVE",
        ).count()
        if project_count:
            dependencies.append(f"仍有 {project_count} 个（含回收站）项目关联该组织")
        if member_items:
            dependencies.append(f"仍有 {member_items} 条成员关系回收站记录，需先恢复或清理")
    elif item.resource_type == "mock_service":
        endpoint_count = db.query(MockEndpoint.id).execution_options(include_deleted=True).filter(
            MockEndpoint.mock_service_id == row.id,
        ).count()
        reference_count = db.query(TestCaseMock.id).filter(TestCaseMock.mock_service_id == row.id).count()
        history_count = db.query(MockExecution.id).filter(MockExecution.mock_service_id == row.id).count()
        if endpoint_count:
            dependencies.append(f"仍有 {endpoint_count} 个接口，不能级联清理")
        if reference_count:
            dependencies.append(f"仍被 {reference_count} 条测试用例依赖引用")
        if history_count:
            dependencies.append(f"保留的 Mock 调用历史有 {history_count} 条")
    elif item.resource_type == "mock_endpoint":
        scenario_count = db.query(MockScenario.id).execution_options(include_deleted=True).filter(
            MockScenario.mock_endpoint_id == row.id,
        ).count()
        reference_count = db.query(TestCaseMock.id).filter(TestCaseMock.mock_endpoint_id == row.id).count()
        history_count = db.query(MockExecution.id).filter(MockExecution.mock_endpoint_id == row.id).count()
        if scenario_count:
            dependencies.append(f"仍有 {scenario_count} 个场景，不能级联清理")
        if reference_count:
            dependencies.append(f"仍被 {reference_count} 条测试用例依赖引用")
        if history_count:
            dependencies.append(f"保留的 Mock 调用历史有 {history_count} 条")
    elif item.resource_type == "mock_scenario":
        reference_count = db.query(TestCaseMock.id).filter(TestCaseMock.mock_scenario_id == row.id).count()
        history_count = db.query(MockExecution.id).filter(MockExecution.mock_scenario_id == row.id).count()
        if reference_count:
            dependencies.append(f"仍被 {reference_count} 条测试用例依赖引用")
        if history_count:
            dependencies.append(f"保留的 Mock 调用历史有 {history_count} 条")
    elif item.resource_type == "test_data_asset":
        pool_count = db.query(DataPool.id).filter(DataPool.asset_id == row.id).count()
        if pool_count:
            dependencies.append(f"仍被 {pool_count} 个数据池引用")
    elif item.resource_type == "data_provider":
        step_count = db.query(FixtureStep.id).filter(FixtureStep.provider_id == row.id).count()
        execution_count = db.query(ProviderExecution.id).filter(ProviderExecution.provider_id == row.id).count()
        if step_count:
            dependencies.append(f"仍被 {step_count} 条 Fixture 步骤引用")
        if execution_count:
            dependencies.append(f"关联 {execution_count} 条 Provider 执行历史，执行证据受保护")
    elif item.resource_type == "fixture":
        case_count = db.query(TestCaseFixture.id).filter(TestCaseFixture.fixture_id == row.id).count()
        execution_count = db.query(FixtureExecution.id).filter(FixtureExecution.fixture_id == row.id).count()
        if case_count:
            dependencies.append(f"仍被 {case_count} 条用例引用")
        if execution_count:
            dependencies.append(f"保留的 Fixture 执行历史有 {execution_count} 条，执行证据受保护")
    elif item.resource_type == "data_pool":
        item_count = db.query(DataPoolItem.id).execution_options(include_deleted=True).filter(
            DataPoolItem.pool_id == row.id,
        ).count()
        lease_count = db.query(DataPoolLease.id).filter(
            DataPoolLease.item_id.in_(
                db.query(DataPoolItem.id).execution_options(include_deleted=True).filter(DataPoolItem.pool_id == row.id)
            ),
        ).count()
        if item_count:
            dependencies.append(f"仍有 {item_count} 条（含已删除）池条目，不能级联清理")
        if lease_count:
            dependencies.append(f"仍保留 {lease_count} 条租约记录，占用历史受保护")
    elif item.resource_type == "data_pool_item":
        lease_count = db.query(DataPoolLease.id).filter(DataPoolLease.item_id == row.id).count()
        if lease_count:
            dependencies.append(f"仍保留 {lease_count} 条租约记录，占用历史受保护")
    elif item.resource_type == "target_database_connection":
        if _connection_reference_count(db, row.project_id, row.id):
            dependencies.append("仍被活跃 Data Provider 引用")
    elif item.resource_type == "automation_integration":
        project_count = db.query(AutomationProject.id).execution_options(include_deleted=True).filter(
            AutomationProject.integration_config_id == row.id,
        ).count()
        if project_count:
            dependencies.append(f"仍被 {project_count} 个（含已删除）自动化项目引用")
    elif item.resource_type == "automation_project":
        execution_count = db.query(AutomationExecution.id).filter(
            AutomationExecution.automation_project_id == row.id,
        ).count()
        pipeline_count = db.query(AutomationPipeline.id).filter(
            AutomationPipeline.automation_project_id == row.id,
        ).count()
        if execution_count:
            dependencies.append(f"保留的自动化执行记录有 {execution_count} 条，执行证据受保护")
        if pipeline_count:
            dependencies.append(f"仍绑定 {pipeline_count} 条流水线，不能级联清理")
    elif item.resource_type == "notification_channel":
        record_count = db.query(NotificationRecord.id).filter(NotificationRecord.channel_id == row.id).count()
        if record_count:
            dependencies.append(f"仍保留 {record_count} 条发送记录，送达证据受保护")
    elif item.resource_type == "security_scan_target":
        job_count = db.query(SecurityScanJob.id).filter(SecurityScanJob.target_id == row.id).count()
        if job_count:
            dependencies.append(f"仍保留 {job_count} 条扫描任务，执行证据受保护")
    elif item.resource_type == "security_scan_profile":
        job_count = db.query(SecurityScanJob.id).filter(SecurityScanJob.scan_profile_id == row.id).count()
        if job_count:
            dependencies.append(f"仍保留 {job_count} 条扫描任务，执行证据受保护")
    elif item.resource_type == "security_strategy":
        rule_count = db.query(SecurityMutationRule.id).execution_options(include_deleted=True).filter(
            SecurityMutationRule.strategy_id == row.id,
        ).count()
        case_count = db.query(SecurityCase.id).filter(SecurityCase.strategy_id == row.id).count()
        finding_count = db.query(SecurityFinding.id).filter(SecurityFinding.strategy_id == row.id).count()
        if rule_count:
            dependencies.append(f"仍保留 {rule_count} 条（含已删除）变异规则记录，请先单独处理")
        if case_count:
            dependencies.append(f"仍被 {case_count} 条安全用例历史引用")
        if finding_count:
            dependencies.append(f"仍被 {finding_count} 条安全发现引用")
    elif item.resource_type == "security_rule":
        case_count = db.query(SecurityCase.id).filter(SecurityCase.rule_id == row.id).count()
        if case_count:
            dependencies.append(f"仍被 {case_count} 条安全用例历史引用")
    elif item.resource_type == "test_case":
        execution_count = db.query(CaseExecution.id).filter(CaseExecution.test_case_id == row.id).count()
        suite_link_count = db.query(TestSuiteCase.id).filter(TestSuiteCase.test_case_id == row.id).count()
        scope_link_count = db.query(TestCaseScope.id).filter(TestCaseScope.test_case_id == row.id).count()
        if execution_count:
            dependencies.append(f"仍关联 {execution_count} 条执行历史，执行证据受保护")
        if suite_link_count:
            effects.append(f"物理清理会移除 {suite_link_count} 条套件-用例关联；测试套件和其他用例保留")
        if scope_link_count:
            effects.append(f"物理清理会移除 {scope_link_count} 条测试范围关联；测试范围保留")
    elif item.resource_type == "test_point":
        count = db.query(TestCase.id).execution_options(include_deleted=True).filter(TestCase.test_point_id == row.id).count()
        if count:
            dependencies.append(f"仍被 {count} 个（含已删除）测试用例引用")
    elif item.resource_type == "test_strategy":
        count = db.query(TestPoint.id).execution_options(include_deleted=True).filter(
            TestPoint.strategy_id == row.id,
        ).count()
        if count:
            dependencies.append(f"仍被 {count} 个（含已删除）测试点引用")
    elif item.resource_type == "web_page":
        count = _web_page_reference_count(db, row.id, row.project_id)
        if count:
            dependencies.append(f"仍被 {count} 条 Web 测试步骤引用，不能永久清理")
    elif item.resource_type == "test_scope":
        child_count = db.query(TestScopeNode.id).execution_options(include_deleted=True).filter(TestScopeNode.parent_id == row.id).count()
        link_count = db.query(TestCaseScope.id).filter(TestCaseScope.scope_node_id == row.id).count()
        if child_count:
            dependencies.append(f"仍有 {child_count} 个子范围")
        if link_count:
            dependencies.append(f"仍有 {link_count} 个测试用例关联")
    elif item.resource_type == "api_module":
        child_count = db.query(ApiModule.id).execution_options(include_deleted=True).filter(ApiModule.parent_id == row.id).count()
        count = db.query(ApiInterface.id).execution_options(include_deleted=True).filter(ApiInterface.module_id == row.id).count()
        if child_count:
            dependencies.append(f"仍有 {child_count} 个子模块")
        if count:
            dependencies.append(f"仍有 {count} 个接口归属")
    elif item.resource_type == "api_interface":
        count = db.query(TestCase.id).execution_options(include_deleted=True).filter(TestCase.api_id == row.id).count()
        if count:
            dependencies.append(f"仍被 {count} 个（含已删除）测试用例引用")
        relation_count = db.query(ApiRelation.id).execution_options(include_deleted=True).filter(
            or_(ApiRelation.source_api_id == row.id, ApiRelation.target_api_id == row.id),
        ).count()
        if relation_count:
            dependencies.append(f"仍有关联到 {relation_count} 条接口关系")
        history_count = db.query(ApiChangeLog.id).filter(ApiChangeLog.interface_id == row.id).count()
        if history_count:
            dependencies.append(f"保留的接口变更历史有 {history_count} 条")
    elif item.resource_type == "business_domain":
        count = db.query(BusinessFlow.id).execution_options(include_deleted=True).filter(
            BusinessFlow.domain_id == row.id,
        ).count()
        if count:
            dependencies.append(f"仍有 {count} 条（含已删除）业务流程，不能级联清理")
    elif item.resource_type == "business_flow":
        for model, predicate, label in (
            (BusinessAction, BusinessAction.flow_id == row.id, "业务动作"),
            (BusinessRule, BusinessRule.flow_id == row.id, "业务规则"),
            (BusinessVariableRef, BusinessVariableRef.flow_id == row.id, "变量引用"),
        ):
            count = db.query(model.id).execution_options(include_deleted=True).filter(predicate).count()
            if count:
                dependencies.append(f"仍有 {count} 条（含已删除）{label}")
        execution_count = db.query(FlowExecution.id).filter(FlowExecution.flow_id == row.id).count()
        if execution_count:
            dependencies.append(f"保留的业务流程执行证据有 {execution_count} 条")
    elif item.resource_type == "business_action":
        for model, predicate, label in (
            (BusinessRule, BusinessRule.action_id == row.id, "业务规则"),
            (BusinessPrecondition, BusinessPrecondition.action_id == row.id, "前置条件"),
            (BusinessVariable, BusinessVariable.action_id == row.id, "业务变量"),
            (BusinessState, BusinessState.action_id == row.id, "状态定义"),
            (BusinessBinding, BusinessBinding.action_id == row.id, "业务绑定"),
            (BusinessVariableRef, or_(BusinessVariableRef.source_action_id == row.id,
                                      BusinessVariableRef.target_action_id == row.id), "变量引用"),
        ):
            count = db.query(model.id).execution_options(include_deleted=True).filter(predicate).count()
            if count:
                dependencies.append(f"仍有 {count} 条（含已删除）{label}")
        execution_count = db.query(ActionExecution.id).filter(ActionExecution.action_id == row.id).count()
        if execution_count:
            dependencies.append(f"保留的动作执行证据有 {execution_count} 条")
    elif item.resource_type == "business_variable":
        count = db.query(BusinessVariableRef.id).execution_options(include_deleted=True).filter(
            or_(BusinessVariableRef.source_variable_id == row.id,
                BusinessVariableRef.target_variable_id == row.id),
        ).count()
        if count:
            dependencies.append(f"仍被 {count} 条（含已删除）变量引用关联")
    elif item.resource_type == "business_binding":
        count = db.query(BusinessApiMapping.id).execution_options(include_deleted=True).filter(
            BusinessApiMapping.binding_id == row.id,
        ).count()
        if count:
            dependencies.append(f"仍有 {count} 条（含已删除）API 映射")
        execution_count = db.query(ActionExecution.id).filter(ActionExecution.binding_id == row.id).count()
        if execution_count:
            dependencies.append(f"保留的动作执行证据有 {execution_count} 条")
    elif item.resource_type == "test_suite":
        case_link_count = db.query(TestSuiteCase.id).filter(TestSuiteCase.suite_id == row.id).count()
        plan_link_count = db.query(TestPlanSuite.id).filter(TestPlanSuite.suite_id == row.id).count()
        if case_link_count:
            effects.append(f"物理清理会移除 {case_link_count} 条套件-用例关联；测试用例保留")
        if plan_link_count:
            effects.append(f"物理清理会移除 {plan_link_count} 条计划-套件关联；测试计划保留")
        historical_runs = (
            db.query(TestRun.id)
            .join(TestPlanSuite, TestPlanSuite.plan_id == TestRun.plan_id)
            .filter(TestPlanSuite.suite_id == row.id)
            .count()
        )
        if historical_runs:
            dependencies.append(f"套件关联到 {historical_runs} 条测试运行历史，运行证据受保护")
    elif item.resource_type == "test_plan":
        run_count = db.query(TestRun.id).filter(TestRun.plan_id == row.id).count()
        if run_count:
            dependencies.append(f"仍关联 {run_count} 条测试运行历史，运行证据及计划关联受保护")
        suite_count = db.query(TestPlanSuite.id).filter(TestPlanSuite.plan_id == row.id).count()
        if suite_count:
            effects.append(f"物理清理会移除 {suite_count} 条计划-套件关联；测试套件保留")
    elif item.resource_type == "knowledge_base":
        document_count = db.query(KnowledgeDocument.id).execution_options(include_deleted=True).filter(
            KnowledgeDocument.base_id == row.id,
        ).count()
        if document_count:
            dependencies.append(f"仍保留 {document_count} 个（含已删除）文档，不能级联清理")
    elif item.resource_type == "knowledge_document":
        version_count = db.query(KnowledgeVersion.id).filter(
            KnowledgeVersion.document_id == row.id,
        ).count()
        if version_count:
            dependencies.append(f"保留的知识版本有 {version_count} 个；源文件和检索证据受保护")
    elif item.resource_type == "agent_definition":
        revision_count = db.query(AgentDefinitionRevision.id).filter(
            AgentDefinitionRevision.agent_definition_id == row.id,
        ).count()
        from app.orchestration.tasks.models import Task
        task_count = db.query(Task.id).filter(Task.agent_definition_id == row.id).count()
        if revision_count:
            dependencies.append(f"不可变 Agent 修订记录有 {revision_count} 个，配置历史受保护")
        if task_count:
            dependencies.append(f"历史任务仍引用该 Agent 的原始 ID，共 {task_count} 条；任务证据受保护")
    elif item.resource_type == "skill_definition":
        revision_count = db.query(SkillDefinitionRevision.id).filter(
            SkillDefinitionRevision.skill_definition_id == row.id,
        ).count()
        usage_count = db.query(SkillUsageEvent.id).filter(
            SkillUsageEvent.skill_definition_id == row.id,
        ).count()
        if revision_count:
            dependencies.append(f"不可变 Skill 修订记录有 {revision_count} 个，内容历史受保护")
        if usage_count:
            dependencies.append(f"保留的任务 Skill 使用记录有 {usage_count} 条，执行证据受保护")
    elif item.resource_type == "mcp_server":
        from app.orchestration.tasks.models import TaskRun

        prefix = f"mcp:{row.id}:"
        agent_history = sum(
            1 for (snapshot,) in db.query(AgentDefinitionRevision.snapshot_json).all()
            if _contains_mcp_reference(snapshot or {}, prefix)
        )
        skill_history = sum(
            1 for (snapshot,) in db.query(SkillDefinitionRevision.snapshot_json).all()
            if _contains_mcp_reference(snapshot or {}, prefix)
        )
        task_history = sum(
            1 for (snapshot,) in db.query(TaskRun.input_snapshot).all()
            if _contains_mcp_reference(snapshot or {}, prefix)
        )
        if agent_history:
            dependencies.append(f"Agent 历史修订中仍有 {agent_history} 条 MCP 引用")
        if skill_history:
            dependencies.append(f"Skill 历史修订中仍有 {skill_history} 条 MCP 引用")
        if task_history:
            dependencies.append(f"运行快照/调用证据中仍有 {task_history} 条 MCP 引用")
    elif item.resource_type == "bug":
        source_count = db.query(DefectSourceLink.id).filter(DefectSourceLink.bug_id == row.id).count()
        if source_count:
            dependencies.append(f"仍关联 {source_count} 条缺陷来源追溯记录，来源证据受保护")
    elif item.resource_type == "test_suite":
        linked_plans = db.query(TestPlanSuite.id).filter(TestPlanSuite.suite_id == row.id).count()
        if linked_plans:
            dependencies.append(f"仍被 {linked_plans} 个测试计划引用")
        historical_runs = (
            db.query(TestRun.id)
            .join(TestPlanSuite, TestPlanSuite.plan_id == TestRun.plan_id)
            .filter(TestPlanSuite.suite_id == row.id)
            .count()
        )
        if historical_runs:
            dependencies.append(f"套件关联到 {historical_runs} 条测试运行历史，运行证据受保护")
    elif item.resource_type == "test_plan":
        run_count = db.query(TestRun.id).filter(TestRun.plan_id == row.id).count()
        if run_count:
            dependencies.append(f"仍关联 {run_count} 条测试运行历史，运行证据及计划关联受保护")
        suite_count = db.query(TestPlanSuite.id).filter(TestPlanSuite.plan_id == row.id).count()
        if suite_count:
            dependencies.append(f"永久清理会移除 {suite_count} 条计划-套件关联")
    try:
        _assert_deletable(db, item.resource_type, row, actor)
    except HTTPException as exc:
        dependencies.append(str(exc.detail))
    return {
        "item_id": item.id, "resource_type": item.resource_type,
        "resource_id": item.resource_id, "display_name": item.display_name,
        "allowed": not dependencies, "dependencies": dependencies, "effects": effects,
    }


def purge_recycle_item(db: Session, item_id: int, actor: User, *, confirmation: str, reason: str) -> dict[str, Any]:
    if not is_platform_admin(actor):
        raise forbidden("仅平台管理员可永久清理数据")
    if confirmation != PERMANENT_CONFIRMATION:
        raise bad_request(f"永久清理必须显式确认：{PERMANENT_CONFIRMATION}")
    preview = purge_preview(db, item_id, actor)
    if not preview["allowed"]:
        raise conflict("当前依赖检查不允许永久清理：" + "；".join(preview["dependencies"]))
    item = db.query(RecycleBinItem).filter_by(id=item_id).with_for_update().first()
    row = (
        db.query(_model(item.resource_type)).execution_options(include_deleted=True)
        .filter_by(id=int(item.resource_id)).with_for_update().first()
    )
    if item.deletion_status != "ACTIVE" or row.deleted_at is None:
        raise conflict("数据状态已变化，请刷新后重试")
    db.delete(row)
    item.deletion_status = "PURGED"
    item.last_restore_error = None
    _audit(db, event_type="PURGE", resource_type=item.resource_type,
           resource_id=int(item.resource_id), actor_id=actor.id, project_id=item.project_id,
           organization_id=item.organization_id, batch_id=item.deletion_batch_id,
           reason=reason, item_id=item.id, detail={"display_name": item.display_name})
    db.commit()
    return {"id": item.id, "succeeded": True, "deletion_status": "PURGED"}
