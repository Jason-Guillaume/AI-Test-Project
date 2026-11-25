import { Alert, Card, Empty, Select, Space, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import type { AgentDefinition, ToolDependency } from '@/features/agent-governance/contracts';
import { projectsApi } from '@/features/projects/api/projects';
import { collectPages } from '@/shared/api/pagination';
import { DetailDrawer } from '@/shared/ui/DetailDrawer';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';

export function ToolSourceTags({ path }: { path: ToolDependency }) {
  return <Space wrap size={[4, 4]}>
    {path.direct && <Tag>直接绑定</Tag>}
    {path.skills.map((skill) => <Tag key={skill.key}>经 Skill {skill.name} · v{skill.version}{!skill.is_enabled && ' · 停用'}</Tag>)}
    <Tag color={path.available ? 'green' : 'orange'}>{path.parent_paths?.length ? '独立运行 · ' : ''}{path.available ? '当前可用' : '已配置 · 当前不可用'}</Tag>
    {path.parent_paths?.map((parent) => <Tag key={parent.id} color={parent.available ? 'green' : 'orange'}>
      经 {parent.name} · {parent.available ? '当前可用' : '当前不可用'}
    </Tag>)}
  </Space>;
}

export function EffectiveConfigurationDrawer({ agent, parent, onClose }: {
  agent: AgentDefinition; parent?: AgentDefinition; onClose: () => void;
}) {
  const [selection, setSelection] = useState<number>();
  const projects = useQuery({ queryKey: ['projects', 'effective-configuration'],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })) });
  const projectId = selection ?? projects.data?.items[0]?.id;
  const preview = useQuery({ queryKey: ['agent-governance', 'effective-config', agent.id, parent?.id, projectId],
    queryFn: () => agentGovernanceApi.effectiveConfig(agent.id, projectId!, parent?.id), enabled: projectId != null });
  const config = preview.data;
  return <DetailDrawer title={`${agent.name} · 有效配置`} open onClose={onClose} width={720}>
    <Space direction="vertical" style={{ width: '100%', minWidth: 0 }}>
      {parent && <Typography.Text type="secondary">{parent.name} → {agent.name}</Typography.Text>}
      <Select aria-label="有效配置项目" value={projectId} showSearch optionFilterProp="label" style={{ width: '100%' }}
        loading={projects.isLoading} placeholder="选择项目" options={projects.data?.items.map((item) => ({ value: item.id, label: item.name }))}
        onChange={setSelection} />
      {projects.isError && <ErrorState error={projects.error} onRetry={projects.refetch} />}
      {!projects.isLoading && !projects.isError && projectId == null && <Empty description="暂无可选项目" />}
      {preview.isLoading && <LoadingState />}
      {preview.isError && <ErrorState error={preview.error} onRetry={preview.refetch} />}
      {config && <>
        {config.warnings.map((warning, index) => <Alert key={`${index}:${warning}`} type="warning" showIcon message={warning} />)}
        <Card size="small" title="运行模型">
          {config.model ? <Space wrap><Typography.Text strong>{config.model.label} · {config.model.name}</Typography.Text>
            <Tag>{{ agent: 'Agent 固定', parent: '继承主 Agent', default: '项目可用默认模型' }[config.model.source]}</Tag></Space> : '未知'}
        </Card>
        <Card size="small" title="知识范围">
          {config.knowledge ? <Space direction="vertical">
            <Typography.Text>{config.knowledge.access_mode === 'AGENT_SCOPED' ? '限定 Agent 范围' : '共享项目知识'} · 配置修订 {config.knowledge.revision}</Typography.Text>
            <Typography.Text type="secondary">{config.knowledge.version_ids.length} 个可见文档版本</Typography.Text>
            <Space wrap size={[4, 4]}>{config.knowledge.version_ids.map((version) => <Tag key={version}>版本 ID {version}</Tag>)}</Space>
          </Space> : '未知'}
        </Card>
        <Card size="small" title="Skill 文件">
          {config.skills.length ? config.skills.map((skill) => <div key={skill.key} style={{ marginBottom: 8 }}>
            <Typography.Text strong>{skill.name} · v{skill.version}</Typography.Text>{!skill.is_enabled && <Tag>停用</Tag>}
            <Space wrap style={{ display: 'flex' }}>{skill.files.map((path) => <Typography.Text code key={path}>{path}</Typography.Text>)}</Space>
          </div>) : <Typography.Text type="secondary">未配置 Skill</Typography.Text>}
        </Card>
        <Card size="small" title="工具及来源">
          {config.tools.length ? config.tools.map((tool) => <Space key={tool.key} direction="vertical" style={{ display: 'flex', marginBottom: 8, overflowWrap: 'anywhere' }}>
            <Typography.Text strong>{tool.key}</Typography.Text><ToolSourceTags path={tool} />
          </Space>) : <Typography.Text type="secondary">未配置工具</Typography.Text>}
        </Card>
      </>}
    </Space>
  </DetailDrawer>;
}
