// 测试资产主工作区：树选择、revision 编辑与各类资产明细。
import { collectArrayPages } from '@/shared/api/pagination';
import { PreconditionsTab, DataTab } from './TestAssetEditTabs';
import { TestAssetDialogs, type StrategyFormValues, type PointFormValues, type CaseFormValues } from './TestAssetDialogs';
import { FixturesTab, StepsTab, AssertionsTab } from './TestAssetExecutionTabs';
// 测试资产页（用户视角）。
// 左右布局：左侧 策略→测试点→用例 三级树；右侧选中用例的聚合详情编辑器
// （基本信息 + 前置条件 / 测试数据 / 步骤 / 断言 四 Tab，子实体就地 CRUD）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// §26：用例编辑携带 revision 乐观锁；并发冲突返回 409，前端提示「当前测试用例已被其他用户修改」并重载详情。
// 返回形态：listStrategies/listPoints/listCases/getCaseDetail 及子实体列表均为裸数组/对象（无分页信封）。
import { useEffect, useMemo, useRef, useState } from 'react';
import { App, Alert, Button, Card, Col, Descriptions, Form, Row, Space, Tabs, Tag, Tree, Typography } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TaskSourceLinks } from '@/features/tasks/components/TaskSourceLinks';
import type { TestCaseCreate, TestCaseUpdate, TestPointCreate, TestStrategyCreate } from '@/features/test-management/contracts';

const STATUS_COLOR: Record<string, string> = {
  DRAFT: 'blue',
  ACTIVE: 'green',
  DEPRECATED: 'default',
};

/** 左侧树节点（结构兼容 antd Tree 的 DataNode，后者字段全可选）。 */
interface TreeNode {
  key: string;
  title: string;
  children?: TreeNode[];
  isLeaf?: boolean;
}

/** 测试资产页。 */
export function TestAssetWorkspace() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedCaseId = Number(searchParams.get('caseId'));
  const requestedProjectId = Number(searchParams.get('projectId'));
  const restoredCase = useRef('');

  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<number | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [selectedKey, setSelectedKey] = useState<string>();

  const [strategyOpen, setStrategyOpen] = useState(false);
  const [pointOpen, setPointOpen] = useState(false);
  const [caseOpen, setCaseOpen] = useState(false);
  const [caseEditOpen, setCaseEditOpen] = useState(false);
  const [strategyForm] = Form.useForm<StrategyFormValues>();
  const [pointForm] = Form.useForm<PointFormValues>();
  const [caseForm] = Form.useForm<CaseFormValues>();
  const [caseEditForm] = Form.useForm<CaseFormValues>();

  const strategiesQuery = useQuery({
    queryKey: ['test-strategies', currentProjectId],
    queryFn: () => collectArrayPages((page) => testManagementApi.listStrategies(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: currentProjectId != null,
  });
  const pointsQuery = useQuery({
    queryKey: ['test-points', currentProjectId],
    queryFn: () => collectArrayPages((page) => testManagementApi.listPoints(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: currentProjectId != null,
  });
  const casesQuery = useQuery({
    queryKey: ['test-cases', currentProjectId],
    queryFn: () => collectArrayPages((page) => testManagementApi.listCases(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: currentProjectId != null,
  });
  const detailQuery = useQuery({
    queryKey: ['test-case-detail', selectedCaseId],
    queryFn: () => testManagementApi.getCaseDetail(selectedCaseId!),
    enabled: selectedCaseId != null,
  });

  const strategies = useMemo(() => strategiesQuery.data ?? [], [strategiesQuery.data]);
  const points = useMemo(() => pointsQuery.data ?? [], [pointsQuery.data]);
  const cases = useMemo(() => casesQuery.data ?? [], [casesQuery.data]);
  const detail = detailQuery.data;

  useEffect(() => {
    if (!Number.isSafeInteger(requestedCaseId) || requestedCaseId <= 0) {
      restoredCase.current = '';
      return;
    }
    if (!currentProjectId || (requestedProjectId > 0 && requestedProjectId !== currentProjectId) || !casesQuery.isSuccess || !pointsQuery.isSuccess) return;
    const restoreKey = `${currentProjectId}:${requestedCaseId}`;
    if (restoredCase.current === restoreKey) return;
    const selected = casesQuery.data.find((item) => item.id === requestedCaseId);
    if (!selected) return;
    const point = pointsQuery.data.find((item) => item.id === selected.test_point_id);
    setSelectedCaseId(selected.id);
    setSelectedPointId(selected.test_point_id ?? null);
    setSelectedStrategyId(point?.strategy_id ?? null);
    setSelectedKey(`c:${selected.id}`);
    restoredCase.current = restoreKey;
  }, [casesQuery.data, casesQuery.isSuccess, currentProjectId, pointsQuery.data, pointsQuery.isSuccess, requestedCaseId, requestedProjectId]);

  const treeData = useMemo<TreeNode[]>(() => {
    const buildPoints = (parentId: number | null) =>
      points
        .filter((p) => (p.strategy_id ?? null) === parentId)
        .map((p) => ({
          key: `p:${p.id}`,
          title: p.name,
          children: cases
            .filter((c) => c.test_point_id === p.id)
            .map((c) => ({ key: `c:${c.id}`, title: c.name, isLeaf: true })),
        }));
    const nodes: TreeNode[] = strategies.map((s) => ({
      key: `s:${s.id}`,
      title: s.name,
      children: buildPoints(s.id),
    }));
    const ungrouped = buildPoints(null);
    if (ungrouped.length > 0) {
      nodes.push({ key: 's:0', title: '未归属策略', children: ungrouped });
    }
    return nodes;
  }, [strategies, points, cases]);

  const onSelect = (keys: React.Key[]) => {
    const key = keys[0] as string | undefined;
    if (!key) return;
    setSelectedKey(key);
    const [type, idStr] = key.split(':');
    const id = Number(idStr);
    if (type === 's') {
      setSelectedStrategyId(id || null);
      setSelectedPointId(null);
      setSelectedCaseId(null);
    } else if (type === 'p') {
      setSelectedPointId(id);
      const p = points.find((x) => x.id === id);
      setSelectedStrategyId(p?.strategy_id ?? null);
      setSelectedCaseId(null);
    } else if (type === 'c') {
      setSelectedCaseId(id);
      const c = cases.find((x) => x.id === id);
      const pid = c?.test_point_id ?? null;
      setSelectedPointId(pid);
      const p = points.find((x) => x.id === pid);
      setSelectedStrategyId(p?.strategy_id ?? null);
    }
  };

  // ---- 创建策略 / 点 / 用例 ----
  const createStrategyMut = useMutation({
    mutationFn: (body: TestStrategyCreate) => testManagementApi.createStrategy(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('测试策略已创建');
      queryClient.invalidateQueries({ queryKey: ['test-strategies'] });
      setStrategyOpen(false);
      setSelectedStrategyId(data.id);
      setSelectedKey(`s:${data.id}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
  const createPointMut = useMutation({
    mutationFn: (body: TestPointCreate) => testManagementApi.createPoint(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('测试点已创建');
      queryClient.invalidateQueries({ queryKey: ['test-points'] });
      setPointOpen(false);
      setSelectedPointId(data.id);
      setSelectedKey(`p:${data.id}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
  const createCaseMut = useMutation({
    mutationFn: (body: TestCaseCreate) => testManagementApi.createCase(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('测试用例已创建');
      queryClient.invalidateQueries({ queryKey: ['test-cases'] });
      setCaseOpen(false);
      setSelectedCaseId(data.id);
      setSelectedKey(`c:${data.id}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  // ---- 编辑用例基本信息（§26 乐观锁）----
  const updateCaseMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestCaseUpdate }) =>
      testManagementApi.updateCase(id, body),
    onSuccess: () => {
      message.success('用例已更新');
      queryClient.invalidateQueries({ queryKey: ['test-cases'] });
      queryClient.invalidateQueries({ queryKey: ['test-case-detail', selectedCaseId] });
      setCaseEditOpen(false);
    },
    onError: (e) => {
      // §26：并发冲突 → 后端返回 409「当前测试用例已被其他用户修改，请刷新后重试」。
      message.error(getErrorMessage(e, '更新失败'));
      queryClient.invalidateQueries({ queryKey: ['test-case-detail', selectedCaseId] });
    },
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const openCaseEdit = () => {
    if (!detail) return;
    caseEditForm.setFieldsValue({
      name: detail.name,
      priority: detail.priority as CaseFormValues['priority'],
      case_type: detail.case_type as CaseFormValues['case_type'],
      target_type: detail.target_type as CaseFormValues['target_type'],
      status: detail.status as CaseFormValues['status'],
      enabled: detail.enabled,
      description: detail.description ?? undefined,
    });
    setCaseEditOpen(true);
  };

  const submitCaseEdit = async () => {
    if (!detail) return;
    const values = await caseEditForm.validateFields();
    // §26：携带当前 revision；不匹配时后端返回 409。
    await updateCaseMut.mutateAsync({
      id: detail.id,
      body: {
        name: values.name,
        priority: values.priority,
        case_type: values.case_type,
        target_type: values.target_type,
        status: values.status,
        enabled: values.enabled,
        description: values.description || null,
        revision: detail.revision,
      },
    });
  };

  if (requestedProjectId > 0 && requestedProjectId !== currentProjectId) return <PageContainer><Alert type="warning" showIcon message={`此链接指向项目 #${requestedProjectId}，请先在顶部切换项目`} /></PageContainer>;

  const onCreateStrategy = async () => { const v = await strategyForm.validateFields(); await createStrategyMut.mutateAsync({ name:v.name, category:v.category, enabled:v.enabled, description:v.description || null }); };
  const onCreatePoint = async () => { const v = await pointForm.validateFields(); await createPointMut.mutateAsync({ name:v.name, priority:v.priority, target_type:v.target_type, status:v.status, strategy_id:selectedStrategyId || null, description:v.description || null }); };
  const onCreateCase = async () => { const v = await caseForm.validateFields(); await createCaseMut.mutateAsync({ name:v.name, priority:v.priority, case_type:v.case_type, target_type:v.target_type, status:v.status, enabled:v.enabled, test_point_id:selectedPointId, description:v.description || null }); };

  return (
    <PageContainer>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="测试资产与专业工作区"
        description={<Space wrap>在此管理测试策略、测试点和用例；Web 页面对象与安全策略可在对应工作区维护。<Button size="small" onClick={() => navigate('/console/web-ui')}>Web UI 工作区</Button><Button size="small" onClick={() => navigate('/console/security-testing')}>安全测试工作区</Button></Space>}
      />
      <Row gutter={16} className="resource-split">
        {/* 左侧树 */}
        <Col className="resource-split__sidebar">
          <div
            className="resource-split__panel"
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 8,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }} wrap>
              <span style={{ fontWeight: 600 }}>策略 / 点 / 用例</span>
              <Button size="small" icon={<PlusOutlined />} onClick={() => { strategyForm.resetFields(); strategyForm.setFieldsValue({ category: 'FUNCTIONAL', enabled: true }); setStrategyOpen(true); }}>
                新建策略
              </Button>
            </Space>
            <Space size={4} style={{ marginBottom: 8 }}>
              <Button size="small" type="primary" disabled={selectedStrategyId == null} onClick={() => { pointForm.resetFields(); pointForm.setFieldsValue({ priority: 'P1', target_type: 'API', status: 'DRAFT' }); setPointOpen(true); }}>
                新建测试点
              </Button>
              <Button size="small" disabled={selectedPointId == null} onClick={() => { caseForm.resetFields(); caseForm.setFieldsValue({ priority: 'P1', case_type: 'FUNCTIONAL', target_type: 'API', status: 'DRAFT', enabled: true }); setCaseOpen(true); }}>
                新建用例
              </Button>
            </Space>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {strategiesQuery.isLoading || pointsQuery.isLoading || casesQuery.isLoading ? (
                <LoadingState />
              ) : strategiesQuery.isError || pointsQuery.isError || casesQuery.isError ? (
                <div role="alert">测试资产加载失败 <Button onClick={() => { void strategiesQuery.refetch(); void pointsQuery.refetch(); void casesQuery.refetch(); }}>重试</Button></div>
              ) : treeData.length === 0 ? (
                <EmptyState description="暂无策略，请新建" />
              ) : (
                <Tree
                  treeData={treeData}
                  selectedKeys={selectedKey ? [selectedKey] : []}
                  onSelect={onSelect}
                  blockNode
                />
              )}
            </div>
          </div>
        </Col>

        {/* 右侧用例详情编辑器 */}
        <Col className="resource-split__detail">
          <div
            className="resource-split__panel"
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 16,
              overflow: 'auto',
            }}
          >
            {selectedCaseId == null ? (
              <EmptyState description="请在左侧选择一个测试用例，或新建一个用例" />
            ) : detailQuery.isLoading ? (
              <LoadingState />
            ) : !detail ? (
              <EmptyState description="用例不存在或无访问权限" />
            ) : (
              <>
                <Card
                  size="small"
                  title={<Space><Typography.Text strong>{detail.name}</Typography.Text><Tag>rev {detail.revision}</Tag></Space>}
                  extra={(
                    <Space>
                      {detail.target_type === 'API' && detail.status === 'ACTIVE' && detail.enabled && (
                        <Button
                          size="small"
                          onClick={() => navigate(`/console/tasks?create=1&projectId=${currentProjectId}&caseId=${detail.id}`)}
                        >
                          用此用例创建任务
                        </Button>
                      )}
                      {detail.target_type === 'WEB' ? <Button size="small" onClick={() => navigate(`/console/web-ui?caseId=${detail.id}`)}>打开 Web 用例</Button> : <Button size="small" icon={<EditOutlined />} onClick={openCaseEdit}>编辑用例</Button>}
                    </Space>
                  )}
                  style={{ marginBottom: 12 }}
                >
                  <TaskSourceLinks resourceType="TEST_CASE" resourceId={detail.id} />
                  <Descriptions size="small" column={3}>
                    <Descriptions.Item label="优先级"><Tag>{detail.priority}</Tag></Descriptions.Item>
                    <Descriptions.Item label="类型">{detail.case_type}</Descriptions.Item>
                    <Descriptions.Item label="被测对象">{detail.target_type}</Descriptions.Item>
                    <Descriptions.Item label="状态"><Tag color={STATUS_COLOR[detail.status] ?? 'default'}>{detail.status}</Tag></Descriptions.Item>
                    <Descriptions.Item label="启用">{detail.enabled ? <Tag color="green">是</Tag> : <Tag>否</Tag>}</Descriptions.Item>
                    <Descriptions.Item label="测试点">{detail.test_point_id ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="描述" span={3}>{detail.description || '-'}</Descriptions.Item>
                  </Descriptions>
                </Card>

                {detail.target_type === 'WEB' ? <Alert type="info" showIcon message="Web 步骤在 Web UI 工作区维护，请使用上方入口查看和编辑。" /> : <Tabs
                  items={[
                    { key: 'preconditions', label: '前置条件', children: <PreconditionsTab caseId={detail.id} items={detail.preconditions} /> },
                    { key: 'data', label: '测试数据', children: <DataTab caseId={detail.id} items={detail.test_data} fixtures={detail.fixtures} /> },
                    { key: 'fixtures', label: '所需 Fixture', children: <FixturesTab caseId={detail.id} items={detail.fixtures} /> },
                    { key: 'steps', label: '步骤', children: <StepsTab caseId={detail.id} items={detail.steps} /> },
                    { key: 'assertions', label: '断言', children: <AssertionsTab caseId={detail.id} items={detail.assertions} /> },
                  ]}
                />}
              </>
            )}
          </div>
        </Col>
      </Row>

      <TestAssetDialogs
        strategyOpen={strategyOpen} setStrategyOpen={setStrategyOpen} pointOpen={pointOpen} setPointOpen={setPointOpen}
        caseOpen={caseOpen} setCaseOpen={setCaseOpen} caseEditOpen={caseEditOpen} setCaseEditOpen={setCaseEditOpen}
        strategyForm={strategyForm} pointForm={pointForm} caseForm={caseForm} caseEditForm={caseEditForm}
        creatingStrategy={createStrategyMut.isPending} creatingPoint={createPointMut.isPending} creatingCase={createCaseMut.isPending}
        updatingCase={updateCaseMut.isPending} onCreateStrategy={onCreateStrategy} onCreatePoint={onCreatePoint}
        onCreateCase={onCreateCase} onUpdateCase={submitCaseEdit}
      />
    </PageContainer>
  );
}

