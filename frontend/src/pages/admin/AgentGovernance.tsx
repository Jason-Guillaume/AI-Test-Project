// 平台治理路由容器：保留 Agent、Skill、MCP、Tool 四类直接入口。
import { useLocation } from 'react-router-dom';
import { PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { AgentPane } from './AgentGovernance/AgentPane';
import { McpPane } from './AgentGovernance/McpPane';
import { SkillPane } from './AgentGovernance/SkillPane';
import { ToolsPane } from './AgentGovernance/ToolsPane';

export function AdminAgentGovernancePage(){
 const location=useLocation();
 const section=location.pathname.startsWith('/admin/mcp')?'mcp':location.pathname.startsWith('/admin/skills')?'skills':location.pathname.startsWith('/admin/tools')?'tools':'agents';
 const pages={agents:{title:'Agent 管理',pane:<AgentPane/>},mcp:{title:'MCP 管理',pane:<McpPane/>},skills:{title:'Skill 管理',pane:<SkillPane/>},tools:{title:'工具管理',pane:<ToolsPane/>}};
 return <PageContainer><PageHeader title={pages[section].title}/>{pages[section].pane}</PageContainer>;
}
