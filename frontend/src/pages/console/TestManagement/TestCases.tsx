// 用例管理中心。
// 三个测试方向各自一棵无限级范围树。维度只做筛选，不进入目录。
// 生成结果先进入审核抽屉，接受后才写入正式用例。AI 执行未开放时详情会明确标出。
import { useEffect, useMemo, useState } from 'react';
import {
  ApiOutlined,
  DesktopOutlined,
  FolderOutlined,
  InboxOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tree,
  Typography,
} from 'antd';
import type { DataNode, TreeProps } from 'antd/es/tree';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { GenerationWorkbench } from '@/pages/console/TestManagement/GenerationWorkbench';
import type { GenerationBatch, ScopeNode, TestCaseDetail } from '@/features/test-management/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';

const DIRECTIONS = [
  { value: 'API', label: 'API 接口测试' },
  { value: 'UI', label: 'UI 界面测试' },
  { value: 'AI', label: 'AI 专项测试' },
] as const;

const DIMENSIONS: { value: string; label: string }[] = [
  { value: 'ALL', label: '全部维度' },
  { value: 'FUNCTIONAL', label: '功能' },
  { value: 'BUSINESS', label: '业务' },
  { value: 'NEGATIVE', label: '负向' },
  { value: 'BOUNDARY', label: '边界' },
  { value: 'PERMISSION', label: '权限' },
  { value: 'SECURITY', label: '安全' },
  { value: 'EXCEPTION', label: '异常' },
];

const TARGET_BY_DIRECTION: Record<string, 'API' | 'WEB' | 'AI'> = { API: 'API', UI: 'WEB', AI: 'AI' };

/** 被测对象对应到页面上的三个方向。 */
function directionOfTarget(targetType: string): string {
  if (targetType === 'WEB') return 'UI';
  if (targetType === 'AI') return 'AI';
  return 'API';
}

/** 节点图标只区分导航类型，不把策略画成目录。 */
function nodeIcon(node: ScopeNode) {
  if (node.is_system || node.node_type === 'INBOX') return <InboxOutlined />;
  if (node.asset_type === 'API_INTERFACE' || node.asset_type === 'API_MODULE') return <ApiOutlined />;
  if (node.asset_type === 'WEB_PAGE') return <DesktopOutlined />;
  if (node.asset_type === 'AGENT') return <RobotOutlined />;
  return <FolderOutlined />;
}

/** 按名称过滤时保留命中节点的祖先，避免树被截断。 */
function filterNodes(nodes: ScopeNode[], keyword: string): ScopeNode[] {
  const text = keyword.trim().toLowerCase();
  if (!text) return nodes;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const keep = new Set<number>();
  for (const node of nodes) {
    if (!node.name.toLowerCase().includes(text)) continue;
    let cursor: ScopeNode | undefined = node;
    while (cursor) {
      keep.add(cursor.id);
      cursor = cursor.parent_id == null ? undefined : byId.get(cursor.parent_id);
    }
  }
  return nodes.filter((node) => keep.has(node.id));
}

/** 把扁平节点收成 antd Tree。 */
function toTreeData(nodes: ScopeNode[]): DataNode[] {
  const byParent = new Map<number | null, ScopeNode[]>();
  for (const node of nodes) {
    const list = byParent.get(node.parent_id) ?? [];
    list.push(node);
    byParent.set(node.parent_id, list);
  }
  const build = (parentId: number | null): DataNode[] => (byParent.get(parentId) ?? [])
    .sort((left, right) => left.sort_order - right.sort_order || left.id - right.id)
    .map((node) => ({
      key: String(node.id),
      icon: nodeIcon(node),
      title: `${node.name}  ${node.case_count} 用例 / ${node.point_count} 测试点`,
      children: build(node.id),
    }));
  return build(null);
}

/** 用例管理中心页面。 */
export function ConsoleTestCasesPage() {
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [searchParams] = useSearchParams();
  const requestedCaseId = Number(searchParams.get('caseId'));
  const requestedProjectId = Number(searchParams.get('projectId'));
  const [direction, setDirection] = useState('API');
  const [dimension, setDimension] = useState('ALL');
  const [keyword, setKeyword] = useState('');
  const [treeKeyword, setTreeKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [selectedNodeId, setSelectedNodeId] = useState<number>();
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([]);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [nodeModal, setNodeModal] = useState<{ mode: 'create' | 'edit'; parentId?: number | null; node?: ScopeNode } | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [batch, setBatch] = useState<GenerationBatch | null>(null);

  const treeQuery = useQuery({
    queryKey: ['test-scopes', currentProjectId, direction],
    queryFn: () => testManagementApi.listScopes(currentProjectId!, direction),
    enabled: currentProjectId != null,
  });
  const statsQuery = useQuery({
    queryKey: ['test-scope-stats', currentProjectId, direction],
    queryFn: () => testManagementApi.scopeStats(currentProjectId!, direction),
    enabled: currentProjectId != null,
  });
  const nodeQuery = useQuery({
    queryKey: ['test-scope', selectedNodeId],
    queryFn: () => testManagementApi.getScope(selectedNodeId!),
    enabled: selectedNodeId != null,
  });
  const casesQuery = useQuery({
    queryKey: ['test-scope-cases', currentProjectId, selectedNodeId, dimension, keyword, page],
    queryFn: () => testManagementApi.listScopeCases(currentProjectId!, {
      scope_node_id: selectedNodeId,
      include_descendants: true,
      case_type: dimension === 'ALL' ? undefined : dimension,
      keyword: keyword || undefined,
      page,
      page_size: 10,
      sort: 'updated_at',
      order: 'desc',
    }),
    enabled: currentProjectId != null && selectedNodeId != null,
  });
  const detailQuery = useQuery({
    queryKey: ['test-case-detail', detailId],
    queryFn: () => testManagementApi.getCaseDetail(detailId!),
    enabled: detailId != null,
  });
  const requestedCaseQuery = useQuery({
    queryKey: ['test-case-brief', requestedCaseId],
    queryFn: () => testManagementApi.getCase(requestedCaseId),
    enabled: Number.isSafeInteger(requestedCaseId) && requestedCaseId > 0,
  });
  const agentsQuery = useQuery({
    queryKey: ['case-generation-agents', currentProjectId],
    queryFn: () => testManagementApi.listGenerationAgents(currentProjectId!),
    enabled: currentProjectId != null && generateOpen,
  });

  const nodes = useMemo(() => treeQuery.data?.items ?? [], [treeQuery.data?.items]);
  const visible = useMemo(() => filterNodes(nodes, treeKeyword), [nodes, treeKeyword]);
  const treeData = useMemo(() => toTreeData(visible), [visible]);

  useEffect(() => {
    setSelectedNodeId(undefined);
    setPage(1);
    setSelectedCaseIds([]);
  }, [direction, currentProjectId]);

  useEffect(() => {
    if (selectedNodeId != null || nodes.length === 0) return;
    const inbox = nodes.find((node) => node.is_system);
    if (inbox) setSelectedNodeId(inbox.id);
  }, [nodes, selectedNodeId]);

  useEffect(() => {
    const brief = requestedCaseQuery.data;
    if (!brief) return;
    setDirection(directionOfTarget(brief.target_type));
    setDetailId(brief.id);
  }, [requestedCaseQuery.data]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['test-scopes'] });
    queryClient.invalidateQueries({ queryKey: ['test-scope-stats'] });
    queryClient.invalidateQueries({ queryKey: ['test-scope-cases'] });
    queryClient.invalidateQueries({ queryKey: ['test-scope'] });
    queryClient.invalidateQueries({ queryKey: ['test-case-detail'] });
  };

  const createNode = useMutation({
    mutationFn: (values: { name: string; description?: string; node_type: 'FOLDER' | 'ASSET_LINK'; asset_type?: string; asset_id?: number }) => {
      if (nodeModal?.mode === 'edit' && nodeModal.node) {
        return testManagementApi.updateScope(nodeModal.node.id, { name: values.name, description: values.description });
      }
      return testManagementApi.createScope(currentProjectId!, {
        direction,
        parent_id: nodeModal?.parentId,
        node_type: values.node_type,
        name: values.name,
        description: values.description,
        asset_type: values.node_type === 'ASSET_LINK' ? values.asset_type : undefined,
        asset_id: values.node_type === 'ASSET_LINK' ? values.asset_id : undefined,
      });
    },
    onSuccess: () => { message.success('范围已保存'); setNodeModal(null); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '保存范围失败')),
  });
  const moveCases = useMutation({
    mutationFn: (scopeNodeId: number) => testManagementApi.moveScopeCases(currentProjectId!, { case_ids: selectedCaseIds, scope_node_id: scopeNodeId }),
    onSuccess: () => { message.success('用例已移动'); setMoveOpen(false); setSelectedCaseIds([]); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '移动失败')),
  });
  const archiveCases = useMutation({
    mutationFn: () => testManagementApi.archiveScopeCases(currentProjectId!, { case_ids: selectedCaseIds }),
    onSuccess: () => { message.success('用例已归档'); setSelectedCaseIds([]); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '归档失败')),
  });
  const deleteCases = useMutation({
    mutationFn: () => dataLifecycleApi.deleteMany('test_case', currentProjectId!, selectedCaseIds),
    onSuccess: (receipt) => {
      setSelectedCaseIds([]);
      refresh();
      if (receipt.failed > 0) {
        modal.info({
          title: `批量删除完成：成功 ${receipt.succeeded} 条，失败 ${receipt.failed} 条`,
          width: 620,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              {receipt.items.filter((item) => !item.succeeded).map((item) => (
                <Alert key={item.id} type="error" showIcon message={`用例 #${item.id}`} description={item.error ?? '删除失败'} />
              ))}
            </Space>
          ),
          onOk: () => navigate('/console/recycle-bin'),
        });
      } else {
        modal.success({
          title: `已将 ${receipt.succeeded} 条用例移入回收站`,
          content: '原始用例 ID、步骤、断言、数据和套件引用均保留。',
          okText: '查看回收站',
          onOk: () => navigate('/console/recycle-bin'),
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
  });
  const createCase = useMutation({
    mutationFn: (values: { name: string; priority: 'P0' | 'P1' | 'P2' | 'P3'; case_type: string }) => testManagementApi.createCase(currentProjectId!, {
      name: values.name,
      priority: values.priority,
      case_type: values.case_type as 'FUNCTIONAL',
      target_type: TARGET_BY_DIRECTION[direction],
    }).then(async (created) => {
      if (selectedNodeId != null) {
        await testManagementApi.moveScopeCases(currentProjectId!, { case_ids: [created.id], scope_node_id: selectedNodeId });
      }
      return created;
    }),
    onSuccess: () => { message.success('用例已创建'); setCreateOpen(false); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '创建用例失败')),
  });

  const onDrop: TreeProps['onDrop'] = (info) => {
    const dragId = Number(info.dragNode.key);
    const drag = nodes.find((node) => node.id === dragId);
    if (!drag || drag.is_system) {
      message.warning('待整理节点不能移动');
      return;
    }
    const dropId = Number(info.node.key);
    const drop = nodes.find((node) => node.id === dropId);
    if (!drop) return;
    const parentId = info.dropToGap ? drop.parent_id : drop.id;
    testManagementApi.moveScope(dragId, { parent_id: parentId, sort_order: drop.sort_order })
      .then(() => refresh())
      .catch((error) => message.error(getErrorMessage(error, '调整目录失败')));
  };

  if (currentProjectId == null) {
    return <PageContainer><EmptyState description="请先在顶部选择一个项目" /></PageContainer>;
  }
  if (requestedProjectId > 0 && requestedProjectId !== currentProjectId) {
    return <PageContainer><EmptyState description={`此链接指向项目 #${requestedProjectId}，请先在顶部切换项目`} /></PageContainer>;
  }

  const stats = statsQuery.data;
  const selected = nodeQuery.data;

  return (
    <PageContainer>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Segmented
          value={direction}
          onChange={(value) => setDirection(String(value))}
          options={DIRECTIONS.map((item) => ({ value: item.value, label: item.label }))}
        />
        <Space wrap>
          <Tag>用例 {stats?.case_count ?? 0}</Tag>
          <Tag>范围 {stats?.scope_count ?? 0}</Tag>
          <Tag>测试点 {stats?.point_count ?? 0}</Tag>
          <Tag>P0 {stats?.priority_counts.P0 ?? 0}</Tag>
          <Tag>P1 {stats?.priority_counts.P1 ?? 0}</Tag>
          <Tag>P2 {stats?.priority_counts.P2 ?? 0}</Tag>
          <Tag>P3 {stats?.priority_counts.P3 ?? 0}</Tag>
          <Select
            value={dimension}
            style={{ width: 140 }}
            options={DIMENSIONS}
            onChange={(value) => { setDimension(value); setPage(1); }}
          />
        </Space>
      </Space>
      <Row gutter={16} style={{ marginTop: 12 }} wrap={false}>
        <Col flex="320px">
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 8, height: 'calc(100vh - 250px)', minHeight: 420, display: 'flex', flexDirection: 'column' }}>
            <Space style={{ marginBottom: 8 }}>
              <Button size="small" type="primary" onClick={() => setNodeModal({ mode: 'create', parentId: null })}>新建目录</Button>
              <Button size="small" disabled={selectedNodeId == null} onClick={() => setNodeModal({ mode: 'create', parentId: selectedNodeId })}>子目录</Button>
            </Space>
            <Input.Search allowClear placeholder="搜索范围" onSearch={setTreeKeyword} style={{ marginBottom: 8 }} />
            <div style={{ overflow: 'auto', flex: 1 }}>
              {treeQuery.isPending ? <LoadingState /> : treeQuery.isError ? <ErrorState error={treeQuery.error} onRetry={treeQuery.refetch} /> : (
                <Tree
                  showIcon
                  blockNode
                  draggable
                  selectedKeys={selectedNodeId == null ? [] : [String(selectedNodeId)]}
                  treeData={treeData}
                  onSelect={(keys) => setSelectedNodeId(keys[0] == null ? undefined : Number(keys[0]))}
                  onDrop={onDrop}
                />
              )}
            </div>
          </div>
        </Col>
        <Col flex="1 1 0" style={{ minWidth: 0 }}>
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16, height: 'calc(100vh - 250px)', minHeight: 420, overflow: 'auto' }}>
            {!selected ? <EmptyState description="请选择左侧范围" /> : (
              <>
                <Space style={{ marginBottom: 8 }} wrap>
                  <Typography.Title level={4} style={{ margin: 0 }}>{selected.name}</Typography.Title>
                  <Button size="small" disabled={selected.is_system} onClick={() => setNodeModal({ mode: 'edit', node: selected })}>编辑</Button>
                  <Button size="small" danger disabled={selected.is_system} onClick={() => modal.confirm({
                    title: '删除这个范围？',
                    content: '范围下有子节点或测试用例时需要先移动。删除只会移除当前目录入口，原有数据关联保留在回收站记录中。',
                    onOk: () => testManagementApi.removeScope(selected.id).then(() => { message.success('已删除'); setSelectedNodeId(undefined); refresh(); }).catch((error) => message.error(getErrorMessage(error, '删除失败'))),
                  })}>删除</Button>
                  <Button size="small" onClick={() => setCreateOpen(true)}>手工用例</Button>
                  <Button size="small" type="primary" onClick={() => setGenerateOpen(true)}>生成草稿</Button>
                </Space>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  {selected.path.map((item) => item.name).join(' / ') || selected.name}
                </Typography.Paragraph>
                <Typography.Paragraph>
                  {selected.description || '没有补充说明'}
                  {selected.asset_type ? ` · 关联 ${selected.asset_type} #${selected.asset_id}` : ''}
                </Typography.Paragraph>
                {selected.children.length > 0 ? (
                  <Space wrap style={{ marginBottom: 12 }}>
                    {selected.children.map((child) => (
                      <Tag key={child.id} style={{ cursor: 'pointer' }} onClick={() => setSelectedNodeId(child.id)}>
                        {child.name} {child.case_count}
                      </Tag>
                    ))}
                  </Space>
                ) : null}
                <Space style={{ marginBottom: 8 }}>
                  <Input.Search allowClear placeholder="搜索用例" onSearch={(value) => { setKeyword(value); setPage(1); }} style={{ width: 220 }} />
                  <Button disabled={selectedCaseIds.length === 0} onClick={() => setMoveOpen(true)}>批量移动</Button>
                  <Button disabled={selectedCaseIds.length === 0} onClick={() => archiveCases.mutate()}>批量归档</Button>
                  <Button danger loading={deleteCases.isPending} disabled={selectedCaseIds.length === 0} onClick={() => modal.confirm({
                    title: `删除选中的 ${selectedCaseIds.length} 条测试用例？`,
                    content: '用例将软删除并进入当前项目回收站。正在执行的用例会逐条拒绝，其他用例可部分成功。',
                    okText: `删除 ${selectedCaseIds.length} 条`,
                    okButtonProps: { danger: true },
                    onOk: () => deleteCases.mutateAsync(),
                  })}>批量删除</Button>
                </Space>
                <Table
                  size="small"
                  rowKey="id"
                  loading={casesQuery.isFetching}
                  dataSource={casesQuery.data?.items ?? []}
                  rowSelection={{ selectedRowKeys: selectedCaseIds, preserveSelectedRowKeys: true, onChange: (keys) => setSelectedCaseIds(keys.map(Number)) }}
                  pagination={{ current: page, pageSize: 10, total: casesQuery.data?.total ?? 0, onChange: setPage, showSizeChanger: false }}
                  onRow={(row) => ({ onClick: () => setDetailId(row.id) })}
                  columns={[
                    { title: '编号', dataIndex: 'id', width: 72 },
                    { title: '用例名称', dataIndex: 'name', ellipsis: true },
                    { title: '优先级', dataIndex: 'priority', width: 80 },
                    { title: '维度', dataIndex: 'case_type', width: 100, render: (value: string) => DIMENSIONS.find((item) => item.value === value)?.label ?? value },
                    { title: '状态', dataIndex: 'status', width: 110 },
                    { title: '来源', dataIndex: 'source_type', width: 80, render: (value: string) => value === 'AI' ? 'AI' : '人工' },
                    { title: '测试点', dataIndex: 'test_point_name', width: 140, render: (value: string | null) => value || '-' },
                    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: (value: string) => value?.replace('T', ' ').slice(0, 16) },
                  ]}
                />
              </>
            )}
          </div>
        </Col>
      </Row>
      <NodeModal open={nodeModal != null} initial={nodeModal} onCancel={() => setNodeModal(null)} onSubmit={(values) => createNode.mutate(values)} />
      <Modal title="移动到范围" open={moveOpen} onCancel={() => setMoveOpen(false)} footer={null} destroyOnClose>
        <Select
          showSearch
          style={{ width: '100%' }}
          placeholder="选择目标范围"
          options={nodes.map((node) => ({ value: node.id, label: node.name }))}
          onChange={(value) => moveCases.mutate(value)}
        />
      </Modal>
      <CreateCaseModal open={createOpen} onCancel={() => setCreateOpen(false)} onSubmit={(values) => createCase.mutate(values)} />
      <GenerationDrawer
        open={generateOpen}
        projectId={currentProjectId}
        direction={direction}
        scopeNodeId={selectedNodeId}
        agents={agentsQuery.data ?? []}
        batch={batch}
        onClose={() => setGenerateOpen(false)}
        onBatch={setBatch}
        onChanged={refresh}
      />
      <CaseDetailDrawer detail={detailQuery.data} loading={detailQuery.isFetching} open={detailId != null} onClose={() => setDetailId(null)} />
    </PageContainer>
  );
}

/** 新建或编辑范围节点。资产链接只保存已有资产 ID。 */
function NodeModal({ open, initial, onCancel, onSubmit }: {
  open: boolean;
  initial: { mode: 'create' | 'edit'; node?: ScopeNode } | null;
  onCancel: () => void;
  onSubmit: (values: { name: string; description?: string; node_type: 'FOLDER' | 'ASSET_LINK'; asset_type?: string; asset_id?: number }) => void;
}) {
  const [form] = Form.useForm();
  return (
    <Modal title={initial?.mode === 'edit' ? '编辑范围' : '新建范围'} open={open} onCancel={onCancel} onOk={() => form.validateFields().then(onSubmit)} destroyOnClose>
      <Form form={form} layout="vertical" initialValues={{ node_type: 'FOLDER', name: initial?.node?.name, description: initial?.node?.description }}>
        <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, max: 200 }]}><Input /></Form.Item>
        <Form.Item name="description" label="说明"><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
        {initial?.mode === 'create' ? (
          <>
            <Form.Item name="node_type" label="类型"><Select options={[{ value: 'FOLDER', label: '目录' }, { value: 'ASSET_LINK', label: '资产链接' }]} /></Form.Item>
            <Form.Item name="asset_type" label="资产类型"><Select allowClear options={['API_MODULE', 'API_INTERFACE', 'BUSINESS_DOMAIN', 'BUSINESS_FLOW', 'BUSINESS_ACTION', 'WEB_PAGE', 'AGENT'].map((value) => ({ value, label: value }))} /></Form.Item>
            <Form.Item name="asset_id" label="资产 ID"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          </>
        ) : null}
      </Form>
    </Modal>
  );
}

/** 手工编写一条用例，并挂到当前选中的范围。 */
function CreateCaseModal({ open, onCancel, onSubmit }: {
  open: boolean;
  onCancel: () => void;
  onSubmit: (values: { name: string; priority: 'P0' | 'P1' | 'P2' | 'P3'; case_type: string }) => void;
}) {
  const [form] = Form.useForm();
  return (
    <Modal title="手工用例" open={open} onCancel={onCancel} onOk={() => form.validateFields().then(onSubmit)} destroyOnClose>
      <Form form={form} layout="vertical" initialValues={{ priority: 'P1', case_type: 'FUNCTIONAL' }}>
        <Form.Item name="name" label="用例名称" rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
        <Form.Item name="priority" label="优先级"><Select options={['P0', 'P1', 'P2', 'P3'].map((value) => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="case_type" label="测试维度"><Select options={DIMENSIONS.filter((item) => item.value !== 'ALL')} /></Form.Item>
      </Form>
    </Modal>
  );
}

/** 调用已有主子 Agent 生成草稿，并在审核工作台里逐条或批量处理。 */
function GenerationDrawer({ open, projectId, direction, scopeNodeId, agents, batch, onClose, onBatch, onChanged }: {
  open: boolean;
  projectId: number;
  direction: string;
  scopeNodeId?: number;
  agents: { id: number; name: string; version: number; modules: string[] }[];
  batch: GenerationBatch | null;
  onClose: () => void;
  onBatch: (batch: GenerationBatch | null) => void;
  onChanged: () => void;
}) {
  return (
    <Drawer title="生成草稿审核" open={open} width={860} onClose={onClose}>
      {open ? (
        <GenerationWorkbench
          projectId={projectId}
          direction={direction}
          scopeNodeId={scopeNodeId}
          agents={agents}
          batch={batch}
          onBatch={onBatch}
          onChanged={onChanged}
        />
      ) : null}
    </Drawer>
  );
}

/** 用例详情。AI 未接入执行时只展示维护信息和明确的未开放说明。 */
function CaseDetailDrawer({ detail, loading, open, onClose }: { detail?: TestCaseDetail; loading: boolean; open: boolean; onClose: () => void }) {
  return (
    <Drawer title={detail?.name ?? '用例详情'} open={open} width={760} onClose={onClose}>
      {loading && !detail ? <LoadingState /> : !detail ? <EmptyState description="没有用例详情" /> : (
        <>
          {detail.executor_ready === false ? <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={detail.executor_note || '执行能力尚未开放'} /> : null}
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="编号">{detail.id}</Descriptions.Item>
            <Descriptions.Item label="方向">{detail.direction || directionOfTarget(detail.target_type)}</Descriptions.Item>
            <Descriptions.Item label="优先级">{detail.priority}</Descriptions.Item>
            <Descriptions.Item label="维度">{DIMENSIONS.find((item) => item.value === detail.case_type)?.label ?? detail.case_type}</Descriptions.Item>
            <Descriptions.Item label="状态">{detail.status}</Descriptions.Item>
            <Descriptions.Item label="来源">{detail.source_type === 'AI' ? 'AI' : '人工'}</Descriptions.Item>
            <Descriptions.Item label="目录" span={2}>{detail.scope_paths?.[0]?.path.map((item) => item.name).join(' / ') || '未归类'}</Descriptions.Item>
            <Descriptions.Item label="被测对象" span={2}>{detail.target_type}{detail.api_id ? ` · 接口 #${detail.api_id}` : ''}{(detail.assets ?? []).map((asset) => ` · ${asset.asset_type} #${asset.asset_id}`).join('')}</Descriptions.Item>
          </Descriptions>
          {detail.generation ? (
            <Descriptions bordered size="small" column={1} style={{ marginTop: 12 }} title="生成来源">
              <Descriptions.Item label="主 Agent">{detail.generation.supervisor_name} #{detail.generation.supervisor_agent_id} v{detail.generation.supervisor_version}</Descriptions.Item>
              <Descriptions.Item label="子 Agent">{detail.generation.child_name} #{detail.generation.child_agent_id} v{detail.generation.child_version} · {detail.generation.module}</Descriptions.Item>
              <Descriptions.Item label="模型">{detail.generation.model_name || '-'} #{detail.generation.model_config_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="Skill">{detail.generation.skill_versions.map((item) => `${item.key}@${item.version}`).join('、') || '无'}</Descriptions.Item>
              <Descriptions.Item label="审核">{detail.generation.review_status} · 批次 #{detail.generation.batch_id}</Descriptions.Item>
              <Descriptions.Item label="审阅">{detail.generation.review_summary || '-'}</Descriptions.Item>
            </Descriptions>
          ) : null}
          <Section title="前置条件" rows={detail.preconditions.map((item) => item.expected_value || item.target || item.type)} />
          <Section title="测试数据" rows={detail.test_data.map((item) => `${item.name}: ${item.value || ''}`)} />
          <Section title="步骤" rows={detail.steps.map((item) => item.name)} />
          <Section title="断言" rows={detail.assertions.map((item) => `${item.assertion_type} ${item.expected_value || ''}`)} />
          <Section title="Fixture" rows={detail.fixtures.map((item) => String(item.fixture_id))} />
          <Typography.Title level={5}>执行历史</Typography.Title>
          {(detail.recent_executions ?? []).length === 0 ? <Typography.Text type="secondary">还没有执行记录</Typography.Text> : detail.recent_executions?.map((item) => (
            <div key={item.id}>{item.status} · {item.executor_type || '-'} · {item.error_code || '无错误码'}</div>
          ))}
        </>
      )}
    </Drawer>
  );
}

/** 详情里的一段文本列表。 */
function Section({ title, rows }: { title: string; rows: string[] }) {
  return (
    <section style={{ marginTop: 16 }}>
      <Typography.Title level={5}>{title}</Typography.Title>
      {rows.length === 0 ? <Typography.Text type="secondary">无</Typography.Text> : rows.map((row, index) => <div key={index}>{index + 1}. {row}</div>)}
    </section>
  );
}
