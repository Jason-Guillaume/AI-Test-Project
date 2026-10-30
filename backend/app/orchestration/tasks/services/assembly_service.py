"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import Task, TaskRun
from app.core.models.configuration import ModelConfiguration
from app.agents.models import AgentDefinition
from app.mcp.models import MCPServer
from app.skills.models import SkillDefinition
from app.core.models.identity import OrganizationMember, User
from app.core.models.project import Project
from app.core.http.errors import bad_request, forbidden, not_found
from app.core.security.roles import is_platform_admin
from app.orchestration.tasks.services.access import TaskAccessService


def list_available_agents(db: Session, project_id: int, *, actor: User, target_type: str,
) -> list[dict[str, Any]]:
    """列出当前任务可以完整执行的 Agent；不给普通用户暴露内部提示词与 Skill 正文。"""
    project = TaskAccessService.get_project_for_write(db, project_id, actor)
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

    required_tools = required_agent_tools(target_type)
    enabled_skill_keys = {
        key for (key,) in db.query(SkillDefinition.key).filter(SkillDefinition.is_enabled.is_(True)).all()
    }
    rows = db.query(AgentDefinition).filter(AgentDefinition.is_enabled.is_(True)).order_by(
        AgentDefinition.name.asc(), AgentDefinition.id.asc(),
    ).all()
    options: list[dict[str, Any]] = []
    for row in rows:
        if not agent_workflow_matches(row.workflow_template, target_type):
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


def required_agent_tools(target_type: str) -> set[str]:
    """处理`required`智能体工具相关数据。"""
    if target_type == "SECURITY":
        return set(TASK_AGENT_SECURITY_TOOLS)
    required = set(TASK_AGENT_BASE_TOOLS)
    if target_type == "API":
        required.update(TASK_AGENT_API_TOOLS)
    return required


def agent_workflow_matches(workflow: str, target_type: str) -> bool:
    """处理智能体工作流`matches`相关数据。"""
    compatible = {
        "API": {"api_test", "reporting"},
        "WEB": {"web_ui", "reporting"},
        "SECURITY": {"security"},
    }
    return workflow in compatible.get(target_type, set())


def resolve_agent_profile(db: Session, *, project_id: int, agent_definition_id: int | None,
    actor: User, target_type: str,
) -> dict[str, Any] | None:
    """委托 Agent 组装器解析配置，保留任务服务的既有调用契约。"""
    from app.agents.assembly.builder import build_agent_profile

    return build_agent_profile(
        db, project_id=project_id, agent_definition_id=agent_definition_id, actor=actor,
        target_type=target_type, workflow_matches=agent_workflow_matches,
        required_tool_keys=required_agent_tools,
        resolve_authorized_model=lambda session, project, user, *, requested_model_id=None: (
            resolve_authorized_model(session, project, user, requested_model_id=requested_model_id)
        ),
        model_snapshot=model_snapshot,
    )


def role_tools_for_agent(role: str, baseline: list[str], snapshot: dict[str, Any] | None) -> list[str]:
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


def resolve_authorized_model(
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


def model_snapshot(model: ModelConfiguration | None) -> dict[str, Any]:
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
