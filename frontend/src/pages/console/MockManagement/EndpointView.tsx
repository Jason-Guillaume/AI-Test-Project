import { collectPages } from '@/shared/api/pagination';
// Mock 接口详情页：场景列表 + 场景编辑（行为 / 响应 / 匹配规则 / 试跑）。
//
// 数据：
//   - GET       /mock-endpoints/{id}
//   - GET/POST  /mock-endpoints/{id}/scenarios
//   - GET/PATCH/DELETE /mock-scenarios/{id}
//   - POST      /mock-scenarios/{id}/(set-default|duplicate)
//
// 匹配顺序：① Context Override → ② 按优先级从高到低、id 升序逐条评估匹配规则，
//   「没有配置匹配规则」的场景直接算命中 → ③ 全部未命中才落到默认场景。
// 所以默认场景的优先级高低不起作用，② 跑完才轮到 ③；想让默认兜底，
// 必须给每个非默认场景至少一条匹配规则（或停用它们）。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Flex,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
  PlusOutlined,
  StarOutlined,
} from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { getErrorMessage } from '@/shared/api/client';
import { mockManagementApi } from '@/features/mocking/api/mockManagement';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import type { MockScenario } from '@/features/mocking/contracts';

import { ScenarioEditor } from './ScenarioEditor';
import { behaviorColor, behaviorLabel, MOCK_KEY_PATTERN, statusCodeColor } from './constants';

/** Mock 接口（Endpoint）详情页：场景列表。 */
export function ConsoleMockEndpointPage() {
  const { endpointId } = useParams<{ endpointId: string }>();
  const id = Number(endpointId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message: msg, modal } = App.useApp();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<MockScenario | null>(null);
  // 复制场景：后端要求显式给出新的 scenario_key（同接口唯一），故弹框让用户确认。
  const [dupRow, setDupRow] = useState<MockScenario | null>(null);
  const [dupKey, setDupKey] = useState('');
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<number[]>([]);

  const endpointQuery = useQuery({
    queryKey: ['mock-endpoint', id],
    queryFn: () => mockManagementApi.getEndpoint(id),
    enabled: Number.isFinite(id),
  });
  const endpoint = endpointQuery.data;

  const scenariosQuery = useQuery({
    queryKey: ['mock-scenarios', id],
    queryFn: () => collectPages((page) => mockManagementApi.listScenarios(id, { page, page_size: 200 })),
    enabled: Number.isFinite(id),
  });
  const scenarios = scenariosQuery.data?.items ?? [];

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['mock-scenarios', id] });

  const setDefaultMutation = useMutation({
    mutationFn: (targetId: number) => mockManagementApi.setDefault(targetId),
    onSuccess: () => {
      invalidate();
      msg.success('已设为默认场景（其余场景的默认标记已自动取消）');
    },
    onError: (e) => msg.error(getErrorMessage(e, '设置默认场景失败')),
  });

  const duplicateMutation = useMutation({
    mutationFn: ({ target, key }: { target: number; key: string }) =>
      mockManagementApi.duplicate(target, key),
    onSuccess: (created) => {
      invalidate();
      setDupRow(null);
      msg.success(`已复制为「${created.name}」`);
    },
    onError: (e) => msg.error(getErrorMessage(e, '复制场景失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (targetId: number) => mockManagementApi.removeScenario(targetId),
    onSuccess: () => {
      invalidate();
      msg.success('场景已移入回收站；调用历史保留');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除场景失败')),
  });

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: number[]) => dataLifecycleApi.deleteMany('mock_scenario', endpoint!.project_id, ids),
    onSuccess: async (receipt) => {
      setSelectedScenarioIds([]);
      invalidate();
      await queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      const failures = receipt.items.filter((item) => !item.succeeded);
      modal.info({
        title: `批量删除完成：成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
        width: 620,
        content: failures.length ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            {failures.map((item) => (
              <Alert key={item.id} type="error" showIcon message={`Mock 场景 #${item.id}`} description={item.error ?? '删除失败'} />
            ))}
          </Space>
        ) : '成功项已移入回收站。',
        okText: '查看回收站',
        onOk: () => navigate('/console/recycle-bin'),
      });
    },
    onError: (error) => msg.error(getErrorMessage(error, '批量删除 Mock 场景失败')),
  });

  if (endpointQuery.isLoading) return <LoadingState />;
  if (!endpoint) {
    return (
      <PageContainer>
        <EmptyState description="Mock 接口不存在或已被删除" />
      </PageContainer>
    );
  }

  const columns: TableColumnsType<MockScenario> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '场景',
      dataIndex: 'name',
      width: 220,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{row.name}</Typography.Text>
          <Tag color="geekblue">{row.scenario_key}</Tag>
        </Space>
      ),
    },
    {
      title: '行为',
      dataIndex: 'behavior_type',
      width: 130,
      render: (v: string) => <Tag color={behaviorColor(v)}>{behaviorLabel(v)}</Tag>,
    },
    {
      title: '状态码',
      dataIndex: 'status_code',
      width: 90,
      render: (v: number) => <Tag color={statusCodeColor(v)}>{v}</Tag>,
    },
    {
      title: '延迟',
      dataIndex: 'delay_ms',
      width: 100,
      render: (v: number | null) => (v ? `${v}ms` : '-'),
    },
    {
      title: '匹配规则',
      dataIndex: 'matchers',
      width: 110,
      render: (matchers: MockScenario['matchers']) => {
        if (!matchers.length) return <Tag color="orange">无（总是命中）</Tag>;
        const enabled = matchers.filter((m) => m.enabled).length;
        return <Tooltip title={matchers.map((m) => `${m.source}.${m.field} ${m.operator}`).join('\n')}><Tag>{enabled}/{matchers.length}</Tag></Tooltip>;
      },
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green" icon={<StarOutlined />}>默认</Tag> : '-'),
    },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '调用次数',
      dataIndex: 'call_count',
      width: 100,
      render: (v: number) => (v ? v : '-'),
    },
    {
      title: '操作',
      width: 280,
      fixed: 'right',
      render: (_, row) => (
        <Space size="small" wrap>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditing(row);
              setEditorOpen(true);
            }}
          >
            编辑 / 试跑
          </Button>
          <Button
            size="small"
            icon={<StarOutlined />}
            disabled={row.is_default}
            loading={setDefaultMutation.isPending}
            onClick={() => setDefaultMutation.mutate(row.id)}
          >
            设默认
          </Button>
          <Button
            size="small"
            icon={<CopyOutlined />}
            loading={duplicateMutation.isPending}
            onClick={() => {
              setDupKey(`${row.scenario_key}_COPY`);
              setDupRow(row);
            }}
          >
            复制
          </Button>
          <Popconfirm
            title="确认删除该场景？"
            description="被用例引用或作为服务默认场景时会拒绝删除；执行历史保留。"
            onConfirm={() => deleteMutation.mutate(row.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }} wrap="wrap" gap="middle">
        <Flex align="center" gap="middle" wrap="wrap">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/console/mock-management/services/${endpoint.mock_service_id}`)}>
            返回
          </Button>
          <Typography.Title level={5} style={{ margin: 0 }}>
            {endpoint.name}
          </Typography.Title>
          <Tag color="blue">{endpoint.method}</Tag>
          <Typography.Text code>{endpoint.path}</Typography.Text>
          {endpoint.api_id ? <Tag>关联接口 #{endpoint.api_id}</Tag> : null}
          {endpoint.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}
        </Flex>
        <Space wrap>
          <Link to="/console/recycle-bin">
            <Button>回收站</Button>
          </Link>
          <Link to="/console/mock-management/executions">
            <Button icon={<HistoryOutlined />}>调用记录</Button>
          </Link>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null);
              setEditorOpen(true);
            }}
          >
            新建场景
          </Button>
        </Space>
      </Flex>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="匹配顺序"
        description="检查顺序：先按优先级从高到低、id 从小到大的顺序评估匹配规则，命中的场景立即返回；没有配置匹配规则的场景总是命中，且与它的优先级无关。只有全部未命中时才落到默认场景——因此想让默认场景兜底，必须给每个非默认场景至少一条匹配规则（或停用它们）。"
      />

      {scenariosQuery.isLoading ? (
        <LoadingState />
      ) : scenariosQuery.isError ? (
        <ErrorState error={scenariosQuery.error} onRetry={scenariosQuery.refetch} />
      ) : scenarios.length === 0 ? (
        <EmptyState description="该接口还没有场景，点「新建场景」配置第一条依赖行为" />
      ) : (
        <Table<MockScenario>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={scenarios}
          rowSelection={{
            selectedRowKeys: selectedScenarioIds,
            onChange: (keys) => setSelectedScenarioIds(keys.map(Number)),
          }}
          scroll={{ x: 1500 }}
          pagination={false}
        />
      )}

      {selectedScenarioIds.length > 0 && (
        <Flex justify="space-between" align="center" style={{ marginTop: 12 }}>
          <Typography.Text>已选择 {selectedScenarioIds.length} 个 Mock 场景</Typography.Text>
          <Button
            danger
            icon={<DeleteOutlined />}
            loading={batchDeleteMutation.isPending}
            onClick={() => {
              const ids = [...selectedScenarioIds];
              modal.confirm({
                title: `确认删除选中的 ${ids.length} 个 Mock 场景？`,
                content: '被用例引用或作为服务默认场景的记录会逐条拒绝；成功项可从回收站恢复。',
                okText: '删除并移入回收站',
                okType: 'danger',
                cancelText: '取消',
                onOk: () => batchDeleteMutation.mutateAsync(ids),
              });
            }}
          >
            批量删除
          </Button>
        </Flex>
      )}

      <ScenarioEditor
        endpointId={id}
        open={editorOpen}
        editing={editing}
        onClose={() => {
          setEditorOpen(false);
          setEditing(null);
        }}
        onSaved={invalidate}
      />

      <Modal
        title={`复制场景「${dupRow?.name ?? ''}」`}
        open={dupRow != null}
        onCancel={() => setDupRow(null)}
        confirmLoading={duplicateMutation.isPending}
        onOk={() => {
          const key = dupKey.trim();
          if (!MOCK_KEY_PATTERN.test(key)) {
            msg.error('场景唯一键须为首字母大写的字母 / 数字 / 下划线（≤100）');
            return;
          }
          if (dupRow) duplicateMutation.mutate({ target: dupRow.id, key });
        }}
      >
        <Input
          value={dupKey}
          onChange={(e) => setDupKey(e.target.value)}
          placeholder="如：STOCK_EMPTY_COPY"
          maxLength={100}
          autoFocus
          onPressEnter={() => {
            const key = dupKey.trim();
            if (!dupRow || !MOCK_KEY_PATTERN.test(key)) return;
            duplicateMutation.mutate({ target: dupRow.id, key });
          }}
        />
      </Modal>
    </PageContainer>
  );
}
