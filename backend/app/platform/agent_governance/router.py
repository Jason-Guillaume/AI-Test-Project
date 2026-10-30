"""平台级 Agent、MCP、Skill 与内置工具治理接口（仅平台管理员）。"""

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.agents import services as agent_services
from app.agents.workflows.catalog import WORKFLOW_TEMPLATES
from app.agents.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionResponse,
    AgentDefinitionUpdate,
    DefinitionVersionResponse,
)
from app.mcp import services as mcp_services
from app.mcp.schemas import (
    MCPApprovalUpdate,
    MCPServerCreate,
    MCPServerResponse,
    MCPServerUpdate,
)
from app.skills import services as skill_services
from app.skills.schemas import (
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)
from app.tools.schemas import (
    ToolDefinitionUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import require_platform_admin
from app.core.database.session import get_db
from app.platform.agent_governance.services import usage_query_service

router = APIRouter(prefix="/agent-governance", tags=["Agent 治理"])


@router.get("/workflows")
def list_workflows(actor: User = Depends(require_platform_admin)):
    """列出可配置的内置 LangGraph 工作流模板，不接受任意图代码。"""
    return [{"key": key, **value} for key, value in WORKFLOW_TEMPLATES.items()]


@router.get("/tools")
def list_tools(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """展示代码内注册的安全工具白名单。"""
    return agent_services.list_builtin_tools(db)


@router.put("/tools/{tool_key}")
def update_tool(tool_key: str, body: ToolDefinitionUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新内置工具的说明和 Agent 授权。"""
    return agent_services.update_builtin_tool(db, tool_key, body, actor.id)


@router.post("/tools/{tool_key}/restore-defaults")
def restore_tool_defaults(tool_key: str, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """恢复内置工具默认描述和启用状态。"""
    return agent_services.restore_builtin_tool_defaults(db, tool_key, actor.id)


@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出`agents`。"""
    return agent_services.list_agents(db)


@router.post("/agents", response_model=AgentDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_agent(body: AgentDefinitionCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """创建智能体。"""
    return agent_services.create_agent(db, body, actor.id)


@router.patch("/agents/{agent_id}", response_model=AgentDefinitionResponse)
def update_agent(agent_id: int, body: AgentDefinitionUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新智能体。"""
    return agent_services.update_agent(db, agent_id, body, actor.id)


@router.get("/agents/{agent_id}/versions", response_model=list[DefinitionVersionResponse])
def agent_versions(agent_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出智能体定义的历史版本。"""
    return agent_services.agent_versions(db, agent_id)


@router.post("/agents/{agent_id}/versions/{version}/restore", response_model=AgentDefinitionResponse)
def restore_agent_version(agent_id: int, version: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """把指定历史配置恢复为一个新的 Agent 版本。"""
    return agent_services.restore_agent_version(db, agent_id, version, actor.id)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除智能体。"""
    agent_services.delete_agent(db, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/skills", response_model=list[SkillResponse])
def list_skills(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出`skills`。"""
    return skill_services.list_skills(db)


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill(body: SkillCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """创建`skill`。"""
    return skill_services.create_skill(db, body, actor.id)


@router.post("/skills/import-zip", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def import_skill_zip(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    """导入包含 SKILL.md 的文本型 ZIP。"""
    archive_bytes = await file.read(2_000_001)
    if len(archive_bytes) > 2_000_000:
        from app.core.http.errors import bad_request

        raise bad_request("Skill ZIP 必须小于 2 MB")
    return skill_services.import_skill_zip(db, archive_bytes, file.filename or "skill.zip", actor.id, name=name)


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
def update_skill(skill_id: int, body: SkillUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新`skill`。"""
    return agent_services.update_skill(db, skill_id, body, actor.id)


@router.get("/skills/{skill_id}/versions", response_model=list[DefinitionVersionResponse])
def skill_versions(skill_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出技能定义的历史版本。"""
    return skill_services.skill_versions(db, skill_id)


@router.post("/skills/{skill_id}/versions/{version}/restore", response_model=SkillResponse)
def restore_skill_version(skill_id: int, version: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """把指定历史 Skill 内容恢复为一个新版本。"""
    return agent_services.restore_skill_version(db, skill_id, version, actor.id)


@router.get("/skills/{skill_id}/usage")
def skill_usage(skill_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """查看 Skill 被任务引用的统计。"""
    return usage_query_service.skill_usage(db, skill_id)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(skill_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除`skill`。"""
    agent_services.delete_skill(db, skill_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mcp-servers", response_model=list[MCPServerResponse])
def list_mcp_servers(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出MCP`servers`。"""
    return mcp_services.list_mcp_servers(db)


@router.post("/mcp-servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
def create_mcp_server(body: MCPServerCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """创建MCP服务端。"""
    return mcp_services.create_mcp_server(db, body, actor.id)


@router.patch("/mcp-servers/{server_id}", response_model=MCPServerResponse)
def update_mcp_server(server_id: int, body: MCPServerUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新MCP服务端。"""
    return mcp_services.update_mcp_server(db, server_id, body, actor.id)


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mcp_server(server_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除MCP服务端。"""
    agent_services.delete_mcp_server(db, server_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mcp-servers/{server_id}/discover", response_model=MCPServerResponse)
def discover_mcp_tools(server_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """读取 MCP 服务公开的工具清单。"""
    return mcp_services.discover_mcp_tools(db, server_id, actor.id)


@router.put("/mcp-servers/{server_id}/approved-tools", response_model=MCPServerResponse)
def update_mcp_approvals(server_id: int, body: MCPApprovalUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新MCP`approvals`。"""
    return mcp_services.update_mcp_approvals(db, server_id, body, actor.id)
