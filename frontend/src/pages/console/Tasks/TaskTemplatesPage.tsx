import { useState } from 'react';
import { App, Button, Flex, Input, List, Space, Tag, Typography } from 'antd';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { TaskTemplate } from '@/features/tasks/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';

export function ConsoleTaskTemplatesPage() {
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message, modal } = App.useApp();
  const [keyword, setKeyword] = useState('');
  const query = useQuery({
    queryKey: ['task-templates', currentProjectId, keyword, true],
    queryFn: () => tasksApi.templates(currentProjectId!, { keyword, include_inactive: true }),
    enabled: currentProjectId != null,
  });
  const toggleMutation = useMutation({
    mutationFn: (template: TaskTemplate) => tasksApi.setTemplateActive(template.id, template.version, !template.is_active),
    onSuccess: async () => {
      message.success('模板状态已更新');
      await queryClient.invalidateQueries({ queryKey: ['task-templates', currentProjectId] });
    },
    onError: (error) => message.error(getErrorMessage(error, '模板状态更新失败，请刷新后重试')),
  });

  return (
    <PageContainer>
      <PageHeader title="任务模板" subtitle="模板只保存项目配置引用；使用时仍会重新检查资产、环境和权限。" extra={<Link to="/console/tasks?create=1"><Button type="primary">从当前配置创建模板或任务</Button></Link>} />
      <Input.Search value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索模板名称或说明" allowClear style={{ maxWidth: 420, marginBottom: 16 }} />
      {currentProjectId == null ? <Typography.Text type="secondary">请先选择项目以查看共享模板。</Typography.Text> : query.isPending ? <LoadingState /> : query.isError ? <ErrorState error={query.error} onRetry={query.refetch} /> : (
        <List
          bordered
          locale={{ emptyText: '此项目还没有任务模板' }}
          dataSource={query.data}
          renderItem={(template) => (
            <List.Item actions={[
              <Button key="edit" type="link" onClick={() => navigate(`/console/tasks?templateId=${template.id}&templateMode=edit&projectId=${template.project_id}`)}>编辑</Button>,
              <Button
                key="toggle"
                type="link"
                danger={template.is_active}
                loading={toggleMutation.isPending}
                onClick={() => modal.confirm({
                  title: template.is_active ? '停用此模板？' : '重新启用此模板？',
                  content: template.is_active ? '已有任务快照不受影响；停用后新任务不能选择它。' : '重新启用后，创建任务时可以再次使用此配置。',
                  onOk: () => toggleMutation.mutateAsync(template),
                })}
              >{template.is_active ? '停用' : '启用'}</Button>,
            ]}>
              <List.Item.Meta
                title={<Flex gap={8} align="center" wrap="wrap"><span>{template.name}</span><Tag color={template.is_active ? 'green' : 'default'}>{template.is_active ? `启用 · v${template.version}` : `已停用 · v${template.version}`}</Tag></Flex>}
                description={<Space direction="vertical" size={2}><span>{template.description || '暂无说明'}</span><Typography.Text type="secondary">类型：{template.config.target_type ?? template.config.task_mode ?? 'API'} · 范围：{template.config.case_ids?.length ?? template.config.security_assessment?.api_ids?.length ?? 0} 项</Typography.Text></Space>}
              />
            </List.Item>
          )}
        />
      )}
    </PageContainer>
  );
}
