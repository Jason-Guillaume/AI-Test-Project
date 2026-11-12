"""在已启用 Agent 的授权范围内执行显式评测；不接受身份参数。"""
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition, AgentDefinitionRevision
from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.platform.projects.services.access_service import get_project_or_404
from app.tools.models import ToolDefinitionOverride
from app.tools.dispatcher import dispatch_tool
from app.tools.contracts import ToolCallContext
from app.tools.builtin.ai_evaluation.evaluation_tools import EVALUATION_INPUTS


def invoke_evaluation(db: Session, actor: User, agent_id: int, project_id: int, tool_key: str, arguments: dict) -> dict:
    get_project_or_404(db, project_id, actor)
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise not_found("Agent 配置不存在")
    if not agent.is_enabled or tool_key not in (agent.tool_keys or []):
        raise bad_request("Agent 未启用或未授权此工具")
    override = db.get(ToolDefinitionOverride, tool_key)
    if override is not None and not override.is_enabled:
        raise bad_request("工具已停用")
    schema = EVALUATION_INPUTS.get(tool_key)
    if schema is None:
        raise bad_request("此入口仅支持 ASR 与 AI 只读评测工具")
    try:
        parameters = schema.model_validate(arguments).model_dump()
    except ValidationError:
        raise bad_request("参数不符合工具契约，请检查字段、类型和长度限制") from None
    context = None
    if tool_key in {"asr.get_job_summary", "asr.get_comparison_summary"}:
        revision = db.query(AgentDefinitionRevision.id).filter_by(
            agent_definition_id=agent.id, version=agent.version,
        ).scalar()
        context = ToolCallContext(
            actor=actor, project_id=project_id, agent_definition_id=agent.id,
            agent_definition_revision_id=revision, db=db, trusted_arguments={"db": db},
        )
    result = dispatch_tool(tool_key, channel="fixed", context=context, **parameters)
    return {"agent_id": agent.id, "agent_version": agent.version, "project_id": project_id,
            "tool_key": tool_key, "result": result}
