// 平台治理路由容器：保留 Agent、Skill、MCP、Tool 四类直接入口。
import { Tabs } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';
import { PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { AgentPane } from './AgentGovernance/AgentPane';
import { McpPane } from './AgentGovernance/McpPane';
import { SkillPane } from './AgentGovernance/SkillPane';
import { ToolsPane } from './AgentGovernance/ToolsPane';

const ROUTES={agents:'/admin/agents',mcp:'/admin/mcp',skills:'/admin/skills',tools:'/admin/tools'} as const;
export function AdminAgentGovernancePage(){
 const location=useLocation();const navigate=useNavigate();
 const activeKey=location.pathname.startsWith(ROUTES.mcp)?'mcp':location.pathname.startsWith(ROUTES.skills)?'skills':location.pathname.startsWith(ROUTES.tools)?'tools':'agents';
 return <PageContainer><PageHeader title="Agent 治理中心" subtitle="管理受控工作流、知识技能、MCP 接入与平台工具白名单"/><Tabs activeKey={activeKey} onChange={(key)=>navigate(ROUTES[key as keyof typeof ROUTES])} items={[{key:'agents',label:'Agent',children:<AgentPane/>},{key:'mcp',label:'MCP',children:<McpPane/>},{key:'skills',label:'Skill',children:<SkillPane/>},{key:'tools',label:'工具',children:<ToolsPane/>}]}/></PageContainer>;
}
