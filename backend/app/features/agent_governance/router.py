"""平台级 Agent、MCP、Skill 与内置工具治理接口（仅平台管理员）。"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.features.agent_governance import services
from app.features.agent_governance.catalog import WORKFLOW_TEMPLATES
from app.features.agent_governance.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionResponse,
    AgentDefinitionUpdate,
    DefinitionVersionResponse,
    MCPApprovalUpdate,
    MCPServerCreate,
    MCPServerResponse,
    MCPServerUpdate,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
)
from app.models.identity import User
from app.shared.auth import require_platform_admin
from app.shared.database import get_db

router = APIRouter(prefix="/agent-governance", tags=["Agent 治理"])


@router.get("/workflows")
def list_workflows(actor: User = Depends(require_platform_admin)):
    """列出可配置的内置 LangGraph 工作流模板，不接受任意图代码。"""
    return [{"key": key, **value} for key, value in WORKFLOW_TEMPLATES.items()]


@router.get("/tools")
def list_tools(actor: User = Depends(require_platform_admin)):
    """展示代码内注册的安全工具白名单。"""
    return services.list_builtin_tools()


@router.get("/agents", response_model=list[AgentDefinitionResponse])
def list_agents(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出`agents`。"""
    return services.list_agents(db)


@router.post("/agents", response_model=AgentDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_agent(body: AgentDefinitionCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """创建智能体。"""
    return services.create_agent(db, body, actor.id)


@router.patch("/agents/{agent_id}", response_model=AgentDefinitionResponse)
def update_agent(agent_id: int, body: AgentDefinitionUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新智能体。"""
    return services.update_agent(db, agent_id, body, actor.id)


@router.get("/agents/{agent_id}/versions", response_model=list[DefinitionVersionResponse])
def agent_versions(agent_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出智能体定义的历史版本。"""
    return services.agent_versions(db, agent_id)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除智能体。"""
    services.delete_agent(db, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/skills", response_model=list[SkillResponse])
def list_skills(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出`skills`。"""
    return services.list_skills(db)


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill(body: SkillCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """创建`skill`。"""
    return services.create_skill(db, body, actor.id)


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
def update_skill(skill_id: int, body: SkillUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新`skill`。"""
    return services.update_skill(db, skill_id, body, actor.id)


@router.get("/skills/{skill_id}/versions", response_model=list[DefinitionVersionResponse])
def skill_versions(skill_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出技能定义的历史版本。"""
    return services.skill_versions(db, skill_id)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(skill_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除`skill`。"""
    services.delete_skill(db, skill_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mcp-servers", response_model=list[MCPServerResponse])
def list_mcp_servers(db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """列出MCP`servers`。"""
    return services.list_mcp_servers(db)


@router.post("/mcp-servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
def create_mcp_server(body: MCPServerCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """创建MCP服务端。"""
    return services.create_mcp_server(db, body, actor.id)


@router.patch("/mcp-servers/{server_id}", response_model=MCPServerResponse)
def update_mcp_server(server_id: int, body: MCPServerUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新MCP服务端。"""
    return services.update_mcp_server(db, server_id, body, actor.id)


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mcp_server(server_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除MCP服务端。"""
    services.delete_mcp_server(db, server_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mcp-servers/{server_id}/discover", response_model=MCPServerResponse)
def discover_mcp_tools(server_id: int, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """读取 MCP 服务公开的工具清单。"""
    return services.discover_mcp_tools(db, server_id, actor.id)


@router.put("/mcp-servers/{server_id}/approved-tools", response_model=MCPServerResponse)
def update_mcp_approvals(server_id: int, body: MCPApprovalUpdate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """更新MCP`approvals`。"""
    return services.update_mcp_approvals(db, server_id, body, actor.id)
