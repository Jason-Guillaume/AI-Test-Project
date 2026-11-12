import { useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  DatePicker,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import {
  dataLifecycleApi,
  type LifecycleAuditEvent,
  type PurgePreview,
  type RecycleBinItem,
} from '@/features/data-lifecycle/api';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';

const RESOURCE_LABELS: Record<string, string> = {
  user: '用户账号',
  agent_session: 'Agent 会话',
  project: '项目',
  test_case: '测试用例',
  test_point: '测试点',
  test_scope: '测试范围',
  api_module: 'API 模块',
  api_interface: 'API 接口',
  api_relation: 'API 关联',
  business_domain: '业务域',
  business_flow: '业务流程',
  business_action: '业务动作',
  business_rule: '业务规则',
  business_variable: '业务变量',
  business_state: '业务状态',
  business_binding: '业务绑定',
  business_precondition: '业务前置条件',
  business_api_mapping: '业务 API 字段映射',
  business_variable_ref: '业务变量引用',
  test_suite: '测试套件',
  test_plan: '测试计划',
  test_report: '测试报告',
  bug: '测试缺陷',
  web_page: 'Web 页面对象',
  test_strategy: '测试策略',
  mock_service: 'Mock 服务',
  mock_endpoint: 'Mock 接口',
  mock_scenario: 'Mock 场景',
  test_data_asset: '测试数据资产',
  data_provider: '数据提供方',
  fixture: 'Fixture',
  data_pool: '数据池',
  data_pool_item: '数据池条目',
  target_database_connection: '被测库连接',
  automation_integration: '云效接入配置',
  automation_project: '自动化项目',
  notification_channel: '通知渠道',
  model_configuration: '模型配置',
  web_auth_profile: 'Web 认证配置',
  security_scan_target: '扫描目标',
  security_scan_profile: '扫描策略',
  security_scan_auth_profile: '扫描认证配置',
  notification: '站内通知',
  project_outbound_target: '出站目标',
  project_member: '项目成员',
  organization_member: '组织成员',
  test_step: '测试步骤',
  test_assertion: '测试断言',
  test_case_precondition: '用例前置条件',
  test_case_data: '用例数据',
  test_suite_case: '套件用例关联',
  test_plan_suite: '计划套件关联',
  security_strategy: '安全策略',
  security_rule: '安全变异规则',
  environment: '平台环境配置',
  knowledge_base: '项目知识库',
  knowledge_document: '知识文档',
  agent_definition: 'Agent 定义',
  skill_definition: 'Skill 定义',
  mcp_server: 'MCP 服务',
};

function RecycleBinContent({ adminMode, projectId }: { adminMode: boolean; projectId?: number | null }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [filterProjectId, setFilterProjectId] = useState<number | null>(null);
  const [resourceType, setResourceType] = useState<string>();
  const [deletedBy, setDeletedBy] = useState<number | null>(null);
  const [keyword, setKeyword] = useState('');
  const [dateRange, setDateRange] = useState<[string, string] | undefined>();
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [purge, setPurge] = useState<{ preview: PurgePreview; confirmation: string; reason: string } | null>(null);

  const scopedProjectId = adminMode ? filterProjectId ?? undefined : projectId ?? undefined;
  const enabled = true;
  const listQuery = useQuery({
    queryKey: ['recycle-bin', scopedProjectId, resourceType, deletedBy, keyword, dateRange, page],
    enabled,
    queryFn: () => dataLifecycleApi.list({
      project_id: scopedProjectId,
      resource_type: resourceType,
      deleted_by: deletedBy ?? undefined,
      keyword: keyword || undefined,
      date_from: dateRange?.[0],
      date_to: dateRange?.[1],
      page,
      page_size: 20,
      sort: 'deleted_at',
      order: 'desc',
    }),
  });
  const detailQuery = useQuery({
    queryKey: ['recycle-bin-detail', detailId],
    queryFn: () => dataLifecycleApi.detail(detailId!),
    enabled: detailId != null,
  });
  const auditQuery = useQuery({
    queryKey: ['recycle-bin-audit', detailId],
    queryFn: () => dataLifecycleApi.audit(detailId!),
    enabled: detailId != null,
  });

  const refreshLifecycle = () => {
    queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    queryClient.invalidateQueries({ queryKey: ['test-cases'] });
    queryClient.invalidateQueries({ queryKey: ['test-scope-cases'] });
    queryClient.invalidateQueries({ queryKey: ['test-scopes'] });
    queryClient.invalidateQueries({ queryKey: ['test-points'] });
    queryClient.invalidateQueries({ queryKey: ['test-strategies'] });
    queryClient.invalidateQueries({ queryKey: ['api'] });
    queryClient.invalidateQueries({ queryKey: ['business'] });
    queryClient.invalidateQueries({ queryKey: ['test-suites'] });
    queryClient.invalidateQueries({ queryKey: ['test-plans'] });
    queryClient.invalidateQueries({ queryKey: ['test-reports'] });
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    queryClient.invalidateQueries({ queryKey: ['project'] });
    queryClient.invalidateQueries({ queryKey: ['users'] });
    queryClient.invalidateQueries({ queryKey: ['agent', 'sessions'] });
    queryClient.invalidateQueries({ queryKey: ['agent-governance', 'mcp'] });
    queryClient.invalidateQueries({ queryKey: ['agent-governance', 'agents'] });
    queryClient.invalidateQueries({ queryKey: ['agent-governance', 'skills'] });
  };
  const { mutate: restoreManyMutation, mutateAsync: restoreManyAsync, isPending: isRestorePending } = useMutation({
    mutationFn: (ids: number[]) => ids.length === 1
      ? dataLifecycleApi.restore(ids[0]).then((item) => ({ succeeded: item.succeeded ? 1 : 0, failed: 0, items: [item] }))
      : dataLifecycleApi.restoreMany(ids),
    onSuccess: (receipt) => {
      setSelectedIds([]);
      refreshLifecycle();
      if (receipt.failed === 0) {
        message.success(`已恢复 ${receipt.succeeded} 条数据`);
      } else {
        message.warning(`恢复 ${receipt.succeeded} 条，失败 ${receipt.failed} 条`);
        modal.info({
          title: '恢复处理结果',
          width: 620,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              {receipt.items.filter((item) => !item.succeeded).map((item) => (
                <Alert key={item.id} type="error" showIcon message={`回收站记录 #${item.id}`} description={item.error ?? '恢复失败'} />
              ))}
            </Space>
          ),
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '恢复失败')),
  });
  const purgeMutation = useMutation({
    mutationFn: () => {
      if (!purge) throw new Error('没有待清理记录');
      return dataLifecycleApi.purge(purge.preview.item_id, purge.confirmation, purge.reason);
    },
    onSuccess: () => {
      message.success('数据已永久清理');
      setPurge(null);
      refreshLifecycle();
    },
    onError: (error) => message.error(getErrorMessage(error, '永久清理失败')),
  });

  const columns: TableColumnsType<RecycleBinItem> = useMemo(() => [
    {
      title: '数据名称', dataIndex: 'display_name', ellipsis: true,
      render: (value: string, row) => <Button type="link" style={{ padding: 0 }} onClick={() => setDetailId(row.id)}>{value || `#${row.resource_id}`}</Button>,
    },
    { title: '数据类型', dataIndex: 'resource_type', width: 120, render: (value: string) => RESOURCE_LABELS[value] ?? value },
    { title: '项目', dataIndex: 'project_id', width: 90, render: (value: number | null) => value ?? '平台级' },
    { title: '删除人', dataIndex: 'deleted_by_name', width: 120, render: (value: string | null, row) => value || (row.deleted_by ? `用户 #${row.deleted_by}` : '系统') },
    { title: '删除时间', dataIndex: 'deleted_at', width: 170, render: (value: string) => value.replace('T', ' ').slice(0, 19) },
    { title: '删除原因', dataIndex: 'deletion_reason', width: 180, ellipsis: true, render: (value: string | null) => value || '未填写' },
    { title: '原始 ID', dataIndex: 'resource_id', width: 90 },
    {
      title: '恢复冲突', dataIndex: 'restore_conflict', width: 220,
      render: (value: string | null) => value ? <Tag color="orange">{value}</Tag> : <Tag color="green">可恢复</Tag>,
    },
    { title: '保留状态', dataIndex: 'deletion_status', width: 110, render: () => <Tag>保留中 · 自动清理关闭</Tag> },
    {
      title: '操作', key: 'actions', width: adminMode ? 190 : 120, fixed: 'right',
      render: (_: unknown, row) => (
        <Space size={4}>
          <Button size="small" type="link" onClick={() => setDetailId(row.id)}>详情</Button>
          <Popconfirm title="恢复这条数据？" description={row.restore_conflict ?? '原业务关联将保留。'} onConfirm={() => restoreManyMutation([row.id])}>
            <Button size="small" type="link" loading={isRestorePending}>恢复</Button>
          </Popconfirm>
          {adminMode && <Button size="small" type="link" danger onClick={async () => {
            try {
              const preview = await dataLifecycleApi.purgePreview(row.id);
              setPurge({ preview, confirmation: '', reason: '' });
            } catch (error) { message.error(getErrorMessage(error, '无法读取清理影响范围')); }
          }}>永久清理</Button>}
        </Space>
      ),
    },
  ], [adminMode, message, restoreManyMutation, isRestorePending]);

  const rows = listQuery.data?.items ?? [];
  return (
    <PageContainer>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <div>
          <Typography.Title level={2} style={{ marginBottom: 4 }}>回收站</Typography.Title>
          <Typography.Text type="secondary">已删除的业务资源保留原始 ID 和关联关系；恢复时会检查项目权限、依赖及唯一键冲突。</Typography.Text>
        </div>
        {!adminMode && projectId == null && (
          <Alert type="info" showIcon message="显示有权访问的项目回收站记录" description="项目记录按你的项目成员和组织权限过滤；无权项目不会出现在结果中。" />
        )}
            <Space wrap>
              {adminMode && <InputNumber min={1} placeholder="项目 ID" value={filterProjectId} onChange={(value) => { setFilterProjectId(value); setPage(1); }} />}
              <Select
                allowClear placeholder="业务类型" style={{ width: 160 }} value={resourceType}
                onChange={(value) => { setResourceType(value); setPage(1); }}
                options={Object.entries(RESOURCE_LABELS).map(([value, label]) => ({ value, label }))}
              />
              <InputNumber min={1} placeholder="删除人 ID" value={deletedBy} onChange={(value) => { setDeletedBy(value); setPage(1); }} />
              <Input.Search allowClear placeholder="关键词搜索" style={{ width: 220 }} value={keyword} onChange={(event) => setKeyword(event.target.value)} onSearch={() => setPage(1)} />
              <DatePicker.RangePicker showTime onChange={(_, values) => {
                setDateRange(values[0] && values[1] ? [new Date(values[0]).toISOString(), new Date(values[1]).toISOString()] : undefined);
                setPage(1);
              }} />
              <Button onClick={() => { setResourceType(undefined); setDeletedBy(null); setKeyword(''); setDateRange(undefined); setPage(1); }}>重置筛选</Button>
            </Space>
            <Space>
              <Button type="primary" disabled={!selectedIds.length} loading={isRestorePending} onClick={() => modal.confirm({
                title: `恢复选中的 ${selectedIds.length} 条数据？`,
                content: '系统将逐条检查恢复权限、依赖和名称冲突；冲突项会保留在回收站。',
                onOk: () => restoreManyAsync(selectedIds),
              })}>批量恢复 ({selectedIds.length})</Button>
              <Button onClick={() => setSelectedIds([])} disabled={!selectedIds.length}>清空选择</Button>
            </Space>
            <Table<RecycleBinItem>
              rowKey="id"
              loading={listQuery.isFetching}
              dataSource={rows}
              columns={columns}
              rowSelection={{
                selectedRowKeys: selectedIds,
                preserveSelectedRowKeys: true,
                onChange: (keys) => setSelectedIds(keys.map(Number)),
              }}
              scroll={{ x: 1450 }}
              pagination={{
                current: page, pageSize: 20, total: listQuery.data?.total ?? 0,
                showSizeChanger: false, onChange: (nextPage) => setPage(nextPage),
              }}
            />
      </Space>

      <Drawer title="已删除数据详情" width={720} open={detailId != null} onClose={() => setDetailId(null)}>
        {detailQuery.data && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="数据名称">{detailQuery.data.display_name}</Descriptions.Item>
              <Descriptions.Item label="数据类型">{RESOURCE_LABELS[detailQuery.data.resource_type] ?? detailQuery.data.resource_type}</Descriptions.Item>
              <Descriptions.Item label="原始业务 ID">{detailQuery.data.resource_id}</Descriptions.Item>
              <Descriptions.Item label="所属项目">{detailQuery.data.project_id ?? '平台级'}</Descriptions.Item>
              <Descriptions.Item label="所属组织">{detailQuery.data.organization_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="删除人">{detailQuery.data.deleted_by_name ?? `用户 #${detailQuery.data.deleted_by ?? '-'}`}</Descriptions.Item>
              <Descriptions.Item label="删除时间">{detailQuery.data.deleted_at}</Descriptions.Item>
              <Descriptions.Item label="删除原因">{detailQuery.data.deletion_reason || '未填写'}</Descriptions.Item>
              <Descriptions.Item label="批次 ID">{detailQuery.data.deletion_batch_id}</Descriptions.Item>
              <Descriptions.Item label="恢复状态">{detailQuery.data.restore_conflict || '未发现冲突'}</Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5}>原始业务数据</Typography.Title>
            <pre style={{ maxHeight: 320, overflow: 'auto', padding: 12, background: '#f6f8fa', borderRadius: 6 }}>{JSON.stringify(detailQuery.data.resource_data, null, 2)}</pre>
            <Typography.Title level={5}>操作记录</Typography.Title>
            {auditQuery.data?.map((event: LifecycleAuditEvent) => (
              <Alert key={event.id} type={event.result === 'SUCCEEDED' ? 'info' : 'warning'} showIcon
                message={`${event.event_type} · ${event.created_at.replace('T', ' ')}`}
                description={`${event.reason || '无原因'} · 操作者 ${event.actor_id ?? '系统'}`} />
            ))}
          </Space>
        )}
      </Drawer>

      <Modal
        title="永久清理数据"
        open={purge != null}
        okText="永久清理"
        okButtonProps={{ danger: true, disabled: !purge?.preview.allowed || purge.confirmation !== 'PERMANENTLY_DELETE' || !purge.reason.trim() }}
        confirmLoading={purgeMutation.isPending}
        onCancel={() => setPurge(null)}
        onOk={() => purgeMutation.mutate()}
      >
        {purge && <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="error" showIcon message={`不可逆操作：${purge.preview.display_name}`} description="该操作将物理删除原始业务行；审计记录仍会保留。请核对依赖影响范围。" />
          {purge.preview.dependencies.length > 0 && <Alert type="warning" message="清理暂不可执行" description={purge.preview.dependencies.join('；')} />}
          {!!purge.preview.effects?.length && <Alert type="info" message="清理影响范围" description={purge.preview.effects.join('；')} />}
          <Input.TextArea rows={2} placeholder="填写清理原因" value={purge.reason} onChange={(event) => setPurge({ ...purge, reason: event.target.value })} />
          <Input placeholder="输入 PERMANENTLY_DELETE 确认" value={purge.confirmation} onChange={(event) => setPurge({ ...purge, confirmation: event.target.value })} />
        </Space>}
      </Modal>
    </PageContainer>
  );
}

export function ConsoleRecycleBinPage() {
  const { currentProjectId } = useConsoleScope();
  return <RecycleBinContent adminMode={false} projectId={currentProjectId} />;
}

export function AdminRecycleBinPage() {
  return <RecycleBinContent adminMode />;
}
