// 用例管理中心。
// 三个测试方向各自一棵无限级范围树。维度只做筛选，不进入目录。
// 生成结果先进入审核抽屉，接受后才写入正式用例。AI 执行未开放时详情会明确标出。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  Checkbox,
  Col,
  Descriptions,
  Dropdown,
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
import { CaseExcelImportModal } from '@/pages/console/TestManagement/CaseExcelImportModal';
import type { GenerationBatch, ScopeNode, TestCaseDetail } from '@/features/test-management/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { sequenceColumn } from '@/shared/lib/sequence';
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

/** 把扁平节点收成 antd Tree；系统待整理节点禁选复选框，仅保留点击浏览。 */
function toTreeData(nodes: ScopeNode[]): DataNode[] {
  const byParent = new Map<number | null, ScopeNode[]>();
  for (const node of nodes) {
    const list = byParent.get(node.parent_id) ?? [];
    list.push(node);
    byParent.set(node.parent_id, list);
  }
  const build = (parentId: number | null): DataNode[] => (byParent.get(parentId) ?? [])
    .sort((left, right) => left.sort_order - right.sort_order || left.id - right.id)
    .map((node) => {
      const isSystem = node.is_system || node.node_type === 'INBOX';
      return {
        key: String(node.id),
        icon: nodeIcon(node),
        disableCheckbox: isSystem,
        title: (
          <span
            className="scope-tree-title"
            title={isSystem ? `${node.name}（系统目录，不可删除） · ${node.case_count} 用例` : `${node.name} · ${node.case_count} 用例 / ${node.point_count} 测试点`}
          >
            <span className="scope-tree-name">{node.name}</span>
            <span className="scope-tree-count">{node.case_count} 用例</span>
          </span>
        ),
        children: build(node.id),
      };
    });
  return build(null);
}

/** 计算删除当前浏览目录后的回退目标：向上找同方向仍存在的最近父目录，否则回根视图。 */
function resolveFallbackScopeId(
  currentScopeId: number | undefined,
  deletedIds: Set<number>,
  nodesSnapshot: ScopeNode[],
): number | undefined {
  if (currentScopeId == null || !deletedIds.has(currentScopeId)) return currentScopeId;
  const byId = new Map(nodesSnapshot.map((node) => [node.id, node]));
  const visited = new Set<number>();
  let cursor = byId.get(currentScopeId)?.parent_id ?? null;
  while (cursor != null && !visited.has(cursor)) {
    visited.add(cursor);
    if (!deletedIds.has(cursor) && byId.has(cursor)) return cursor;
    cursor = byId.get(cursor)?.parent_id ?? null;
  }
  return undefined;
}

function QueryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return <Alert type="error" showIcon message="加载失败" description={getErrorMessage(error)} action={<Button onClick={onRetry}>重试</Button>} />;
}

/** 用例管理中心页面。 */
export function ConsoleTestCasesPage() {
  const navigate = useNavigate();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId: globalProjectId, setProjectId } = useConsoleScope();
  const [searchParams, setSearchParams] = useSearchParams();
  const positive = (name: string) => { const value = Number(searchParams.get(name)); return Number.isSafeInteger(value) && value > 0 ? value : undefined; };
  const requestedCaseId = positive('caseId');
  const requestedProjectId = positive('projectId');
  const currentProjectId = requestedProjectId ?? globalProjectId;
  const direction = ['API', 'UI', 'AI'].includes(searchParams.get('direction') ?? '') ? searchParams.get('direction')! : 'API';
  const dimension = searchParams.get('dimension') ?? 'ALL';
  const keyword = searchParams.get('keyword') ?? '';
  const priority = searchParams.get('priority') ?? undefined;
  const caseStatus = searchParams.get('status') ?? undefined;
  const sort = searchParams.get('sort') ?? 'updated_at';
  const order = searchParams.get('order') ?? 'desc';
  const page = positive('page') ?? 1;
  const pageSize = [10, 25, 50].includes(positive('page_size') ?? 0) ? positive('page_size')! : 10;
  const selectedNodeId = positive('scope');
  const detailId = requestedCaseId ?? null;
  const selectionKey = JSON.stringify([currentProjectId, direction, selectedNodeId, keyword, priority, caseStatus, dimension, sort, order]);
  const [selection, setSelection] = useState<{ key: string; ids: number[] }>({ key: selectionKey, ids: [] });
  const selectedCaseIds = selection.key === selectionKey ? selection.ids : [];
  const setSelectedCaseIds = useCallback((ids: number[]) => setSelection({ key: selectionKey, ids }), [selectionKey]);
  useEffect(() => { setSelection({ key: selectionKey, ids: [] }); }, [selectionKey]);
  // 范围目录勾选按「项目 + 测试方向」隔离；切换项目或方向时自动清空，避免跨上下文误删。
  const scopeSelectionKey = JSON.stringify([currentProjectId, direction]);
  const [scopeSelection, setScopeSelection] = useState<{ key: string; ids: number[] }>({ key: scopeSelectionKey, ids: [] });
  const selectedScopeIds = scopeSelection.key === scopeSelectionKey ? scopeSelection.ids : [];
  const setSelectedScopeIds = useCallback((ids: number[]) => setScopeSelection({ key: scopeSelectionKey, ids }), [scopeSelectionKey]);
  useEffect(() => { setScopeSelection({ key: scopeSelectionKey, ids: [] }); }, [scopeSelectionKey]);
  const scopeContextRef = useRef({ key: scopeSelectionKey, selectedNodeId });
  useEffect(() => { scopeContextRef.current = { key: scopeSelectionKey, selectedNodeId }; }, [scopeSelectionKey, selectedNodeId]);
  const [treeKeyword, setTreeKeyword] = useState('');
  const [onlyWithCases, setOnlyWithCases] = useState(false);
  const [targetScopeId, setTargetScopeId] = useState<number>();
  const [targetAction, setTargetAction] = useState<'create' | 'import' | 'generate'>();
  const changeParams = (values: Record<string, string | number | undefined>, reset = true) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(values).forEach(([key, value]) => value == null || value === '' ? next.delete(key) : next.set(key, String(value)));
    if (currentProjectId != null && !next.has('projectId')) next.set('projectId', String(currentProjectId));
    if (reset) { next.delete('page'); setSelectedCaseIds([]); }
    setSearchParams(next);
  };
  const previousGlobalProject = useRef(globalProjectId);
  const globalChange = useRef(false);
  useEffect(() => {
    if (previousGlobalProject.current !== globalProjectId) {
      previousGlobalProject.current = globalProjectId;
      globalChange.current = true;
      const next = new URLSearchParams();
      if (globalProjectId != null) next.set('projectId', String(globalProjectId));
      setSelectedCaseIds([]);
      setSelectedScopeIds([]);
      setSearchParams(next);
    }
  }, [globalProjectId, setSearchParams, setSelectedCaseIds, setSelectedScopeIds]);
  useEffect(() => {
    if (globalChange.current) { globalChange.current = false; return; }
    if (requestedProjectId && requestedProjectId !== globalProjectId) {
      previousGlobalProject.current = requestedProjectId;
      setProjectId(requestedProjectId);
    }
  }, [requestedProjectId, globalProjectId, setProjectId]);
  useEffect(() => {
    if (requestedProjectId == null && globalProjectId != null) {
      const next = new URLSearchParams(searchParams);
      next.set('projectId', String(globalProjectId));
      setSearchParams(next, { replace: true });
    }
  }, [requestedProjectId, globalProjectId, searchParams, setSearchParams]);
  const [nodeModal, setNodeModal] = useState<{ mode: 'create' | 'edit'; parentId?: number | null; node?: ScopeNode } | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [importExcelOpen, setImportExcelOpen] = useState(false);
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
  const casesQuery = useQuery({
    queryKey: ['test-scope-cases', currentProjectId, direction, selectedNodeId, dimension, keyword, priority, caseStatus, page, pageSize, sort, order],
    queryFn: () => testManagementApi.listScopeCases(currentProjectId!, {
      direction,
      scope_node_id: selectedNodeId,
      include_descendants: true,
      priority, status: caseStatus,
      case_type: dimension === 'ALL' ? undefined : dimension,
      keyword: keyword || undefined,
      page,
      page_size: pageSize,
      sort, order,
    }),
    enabled: currentProjectId != null,
  });
  const detailQuery = useQuery({
    queryKey: ['test-case-detail', detailId],
    queryFn: () => testManagementApi.getCaseDetail(detailId!),
    enabled: detailId != null,
  });
  const requestedCaseQuery = useQuery({
    queryKey: ['test-case-brief', requestedCaseId],
    queryFn: () => testManagementApi.getCase(requestedCaseId!),
    enabled: requestedCaseId != null,
  });
  const agentsQuery = useQuery({
    queryKey: ['case-generation-agents', currentProjectId],
    queryFn: () => testManagementApi.listGenerationAgents(currentProjectId!),
    enabled: currentProjectId != null && generateOpen,
  });

  const nodes = useMemo(() => treeQuery.data?.items ?? [], [treeQuery.data?.items]);
  const visible = useMemo(() => { const named = filterNodes(nodes, treeKeyword); return onlyWithCases ? named.filter((node) => node.case_count > 0) : named; }, [nodes, treeKeyword, onlyWithCases]);
  const treeData = useMemo(() => toTreeData(visible), [visible]);
  const checkableVisibleScopeIds = useMemo(
    () => visible.filter((node) => !node.is_system && node.node_type !== 'INBOX').map((node) => node.id),
    [visible],
  );
  const visibleSelectedScopeCount = checkableVisibleScopeIds.filter((id) => selectedScopeIds.includes(id)).length;
  const allVisibleScopesSelected = checkableVisibleScopeIds.length > 0 && visibleSelectedScopeCount === checkableVisibleScopeIds.length;
  const indeterminateVisibleScopes = visibleSelectedScopeCount > 0 && visibleSelectedScopeCount < checkableVisibleScopeIds.length;
  const isScopeTreeFiltered = Boolean(treeKeyword.trim() || onlyWithCases);

  useEffect(() => {
    const brief = requestedCaseQuery.data;
    if (!brief || searchParams.has('direction')) return;
    const next = new URLSearchParams(searchParams); next.set('direction', directionOfTarget(brief.target_type)); setSearchParams(next, { replace: true });
  }, [requestedCaseQuery.data, searchParams, setSearchParams]);

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
  const deleteScopes = useMutation({
    mutationFn: (payload: { projectId: number; ids: number[]; contextKey: string; nodesSnapshot: ScopeNode[] }) =>
      dataLifecycleApi.deleteMany('test_scope', payload.projectId, payload.ids),
    onSuccess: (receipt, variables) => {
      refresh();
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      // 防止切换项目或测试方向后，旧请求的回执覆盖新上下文的勾选与当前浏览目录。
      if (scopeContextRef.current.key !== variables.contextKey) return;
      const succeededIds = new Set(receipt.items.filter((item) => item.succeeded).map((item) => item.id));
      const failedIds = receipt.items.filter((item) => !item.succeeded).map((item) => item.id);
      const nameById = new Map(variables.nodesSnapshot.map((node) => [node.id, node.name]));
      setSelectedScopeIds(failedIds);
      const activeScopeId = scopeContextRef.current.selectedNodeId;
      if (activeScopeId != null && succeededIds.has(activeScopeId)) {
        const fallbackScopeId = resolveFallbackScopeId(activeScopeId, succeededIds, variables.nodesSnapshot);
        changeParams({ scope: fallbackScopeId }, false);
      }
      if (receipt.failed > 0) {
        const firstReason = receipt.items.find((item) => !item.succeeded)?.error ?? '存在依赖保护';
        message.warning(
          receipt.succeeded === 0
            ? `未能删除所选的 ${receipt.failed} 个目录：${firstReason}`
            : `已删除 ${receipt.succeeded} 个目录，${receipt.failed} 个因依赖被保留`,
        );
        window.setTimeout(() => {
          modal.info({
            title: `批量删除目录完成：成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
            width: 620,
            content: (
              <div style={{ maxHeight: 360, overflowY: 'auto', paddingRight: 4 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  {receipt.items.filter((item) => !item.succeeded).map((item) => (
                    <Alert
                      key={item.id}
                      type="error"
                      showIcon
                      message={nameById.get(item.id) ?? `目录 #${item.id}`}
                      description={item.error ?? '删除失败'}
                    />
                  ))}
                </Space>
              </div>
            ),
            okText: '关闭',
          });
        }, 0);
      } else {
        window.setTimeout(() => {
          modal.success({
            title: `已将 ${receipt.succeeded} 个目录移入回收站`,
            content: '成功删除的目录可在回收站按原层级恢复。',
            okText: '查看回收站',
            onOk: () => navigate('/console/recycle-bin'),
          });
        }, 0);
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除目录失败')),
  });
  const requestBatchDeleteScopes = () => {
    if (!currentProjectId || selectedScopeIds.length === 0 || deleteScopes.isPending) return;
    const ids = [...selectedScopeIds];
    const nodesSnapshot = [...nodes];
    const nameById = new Map(nodesSnapshot.map((node) => [node.id, node.name]));
    const previewNames = ids.slice(0, 5).map((id) => nameById.get(id) ?? `#${id}`).join('、');
    const summaryLabel = ids.length > 5 ? `${previewNames} 等 ${ids.length} 个目录` : previewNames;
    modal.confirm({
      title: `删除选中的 ${ids.length} 个测试目录？`,
      content: (
        <Space direction="vertical" size={6}>
          <Typography.Text>待删除目录：{summaryLabel}</Typography.Text>
          <Typography.Text type="secondary">
            只删除明确勾选的目录，父子同选时会先处理子目录；仍含未选子目录或关联用例的目录将被保留，失败项会保持勾选并说明原因。成功项会移入当前项目回收站，可随时恢复。
          </Typography.Text>
        </Space>
      ),
      okText: `删除 ${ids.length} 个目录`,
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => deleteScopes.mutateAsync({
        projectId: currentProjectId,
        ids,
        contextKey: scopeSelectionKey,
        nodesSnapshot,
      }),
    });
  };
  const createCase = useMutation({
    mutationFn: (values: { name: string; priority: 'P0' | 'P1' | 'P2' | 'P3'; case_type: string }) => testManagementApi.createCase(currentProjectId!, {
      name: values.name,
      priority: values.priority,
      case_type: values.case_type as 'FUNCTIONAL',
      target_type: TARGET_BY_DIRECTION[direction],
      scope_node_id: targetScopeId,
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
  const stats = statsQuery.data;
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const path: ScopeNode[] = [];
  let cursor = selectedNode;
  while (cursor && !path.some((item) => item.id === cursor!.id)) { path.unshift(cursor); cursor = nodes.find((node) => node.id === cursor!.parent_id); }
  const selected = selectedNode ? { ...selectedNode, path, children: nodes.filter((node) => node.parent_id === selectedNode.id) } : undefined;
  const launch = (action: 'create' | 'import' | 'generate') => {
    if (selectedNodeId == null) { setTargetScopeId(undefined); setTargetAction(action); return; }
    setTargetScopeId(selectedNodeId);
    if (action === 'create') setCreateOpen(true); else if (action === 'import') setImportExcelOpen(true); else setGenerateOpen(true);
  };
  const clearFilters = () => changeParams({ keyword: undefined, priority: undefined, status: undefined, dimension: undefined });

  return (
    <PageContainer>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Segmented
          value={direction}
          onChange={(value) => changeParams({ direction: String(value), projectId: currentProjectId, scope: undefined, caseId: undefined })}
          options={DIRECTIONS.map((item) => ({ value: item.value, label: item.label }))}
        />
        <Space wrap>
          {statsQuery.isError ? <Button size="small" onClick={() => statsQuery.refetch()}>统计加载失败，重试</Button> : <><Tag>方向总数 {statsQuery.isPending ? '…' : stats?.case_count}</Tag><Tag>范围 {statsQuery.isPending ? '…' : stats?.scope_count}</Tag>{['P0', 'P1', 'P2', 'P3'].map((p) => <Button size="small" key={p} type={priority === p ? 'primary' : 'default'} onClick={() => changeParams({ priority: priority === p ? undefined : p })}>{p} {statsQuery.isPending ? '…' : stats?.priority_counts[p] ?? 0}</Button>)}</>}
          <Tag>筛选命中 {casesQuery.isPending ? '…' : casesQuery.isError ? '—' : casesQuery.data?.total}</Tag>
          <Select value={dimension} aria-label="维度筛选" style={{ width: 140 }} options={DIMENSIONS} onChange={(value) => changeParams({ dimension: value === 'ALL' ? undefined : value })} />
          <Select allowClear value={priority} aria-label="优先级筛选" placeholder="全部优先级" style={{ width: 130 }} options={['P0','P1','P2','P3'].map((value) => ({value, label: value}))} onChange={(value) => changeParams({priority: value})} />
          <Select allowClear value={caseStatus} aria-label="状态筛选" placeholder="全部状态" style={{ width: 130 }} options={['DRAFT','ACTIVE','DEPRECATED'].map((value) => ({value, label: value}))} onChange={(value) => changeParams({status: value})} />
          <Select aria-label="排序" value={`${sort}:${order}`} style={{ width: 170 }} options={[{value:'updated_at:desc',label:'最近更新'}, {value:'name:asc',label:'名称升序'}, {value:'priority:asc',label:'优先级升序'}]} onChange={(value) => { const [nextSort, nextOrder] = value.split(':'); changeParams({ sort: nextSort, order: nextOrder }); }} />
        </Space>
      </Space>
      <Row gutter={[16, 16]} style={{ marginTop: 12 }}>
        <Col xs={24} xl={8} style={{ minWidth: 0 }}>
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 8, height: 'calc(100vh - 250px)', minHeight: 420, display: 'flex', flexDirection: 'column' }}>
            <Space wrap style={{ marginBottom: 8 }}>
              <Button size="small" type="primary" onClick={() => setNodeModal({ mode: 'create', parentId: null })}>新建目录</Button>
              <Button size="small" disabled={selectedNodeId == null} onClick={() => setNodeModal({ mode: 'create', parentId: selectedNodeId })}>子目录</Button>
            </Space>
            <Button type={selectedNodeId == null ? 'primary' : 'default'} onClick={() => changeParams({ scope: undefined })}>全部用例</Button>
            <Checkbox checked={onlyWithCases} onChange={(event) => setOnlyWithCases(event.target.checked)}>仅看有用例的目录</Checkbox>
            <Input.Search
              allowClear
              value={treeKeyword}
              placeholder="搜索范围"
              onChange={(event) => setTreeKeyword(event.target.value)}
              onSearch={setTreeKeyword}
              style={{ marginBottom: 8 }}
            />
            <div className="scope-tree-bulk-bar">
              <Checkbox
                checked={allVisibleScopesSelected}
                indeterminate={indeterminateVisibleScopes}
                disabled={checkableVisibleScopeIds.length === 0 || deleteScopes.isPending}
                onChange={(event) => {
                  if (event.target.checked) {
                    setSelectedScopeIds([...new Set([...selectedScopeIds, ...checkableVisibleScopeIds])]);
                  } else {
                    const visibleSet = new Set(checkableVisibleScopeIds);
                    setSelectedScopeIds(selectedScopeIds.filter((id) => !visibleSet.has(id)));
                  }
                }}
              >
                {isScopeTreeFiltered ? '全选筛选结果' : '全选可见目录'}（{checkableVisibleScopeIds.length}）
              </Checkbox>
              <Space size={4} wrap>
                <Typography.Text type="secondary">已选 {selectedScopeIds.length} 个</Typography.Text>
                <Button
                  size="small"
                  type="link"
                  disabled={selectedScopeIds.length === 0 || deleteScopes.isPending}
                  onClick={() => setSelectedScopeIds([])}
                >
                  清空
                </Button>
                <Button
                  size="small"
                  danger
                  disabled={selectedScopeIds.length === 0 || deleteScopes.isPending}
                  loading={deleteScopes.isPending}
                  onClick={requestBatchDeleteScopes}
                >
                  删除目录
                </Button>
              </Space>
            </div>
            <div style={{ overflow: 'auto', flex: 1 }}>
              {treeQuery.isPending ? <LoadingState /> : treeQuery.isError ? <QueryError error={treeQuery.error} onRetry={treeQuery.refetch} /> : (
                <Tree
                  className="scope-tree"
                  showIcon
                  blockNode
                  checkable
                  checkStrictly
                  draggable
                  checkedKeys={{ checked: selectedScopeIds.map(String), halfChecked: [] }}
                  selectedKeys={selectedNodeId == null ? [] : [String(selectedNodeId)]}
                  treeData={treeData}
                  onCheck={(checkedKeys) => {
                    // 仅更新当前可见节点集合中的勾选态，保留当前搜索或筛选范围之外的已选目录。
                    const raw = Array.isArray(checkedKeys) ? checkedKeys : checkedKeys.checked;
                    const checkableSet = new Set(checkableVisibleScopeIds);
                    const visibleSet = new Set(visible.map((node) => node.id));
                    const nextVisible = raw.map(Number).filter((id) => checkableSet.has(id));
                    const preserved = selectedScopeIds.filter((id) => !visibleSet.has(id));
                    setSelectedScopeIds([...new Set([...preserved, ...nextVisible])]);
                  }}
                  onSelect={(keys) => changeParams({ scope: keys[0] == null ? undefined : Number(keys[0]) })}
                  onDrop={onDrop}
                />
              )}
            </div>
          </div>
        </Col>
        <Col xs={24} xl={16} style={{ minWidth: 0 }}>
          <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16, height: 'calc(100vh - 250px)', minHeight: 420, overflow: 'auto' }}>
            {treeQuery.isError && selectedNodeId != null ? <QueryError error={treeQuery.error} onRetry={treeQuery.refetch} /> : (
              <>
                <div className="scope-detail-head">
                  <Typography.Title level={4}>{selected?.name ?? '全部用例'} · {selected ? selected.case_count : stats?.case_count ?? '…'} 条</Typography.Title>
                  <Space wrap size={8}>
                  {selected && <Dropdown trigger={['click']} menu={{ items: [{key: 'edit', label: '编辑目录', disabled: selected.is_system}, {key: 'delete', label: '删除目录', danger: true, disabled: selected.is_system}], onClick: ({key}) => { if (key === 'edit') setNodeModal({ mode: 'edit', node: selected }); else modal.confirm({ title: '删除这个范围？', content: '范围下有子节点或测试用例时需要先移动。', onOk: () => testManagementApi.removeScope(selected.id).then(() => { message.success('已删除'); changeParams({ scope: undefined }); refresh(); }).catch((error) => message.error(getErrorMessage(error, '删除失败')))}); } }}><Button size="small">目录管理</Button></Dropdown>}
                  <Button size="small" onClick={() => launch('create')}>手工用例</Button><Button size="small" onClick={() => launch('import')}>导入 Excel</Button><Button size="small" type="primary" onClick={() => launch('generate')}>生成草稿</Button>
                  </Space>
                </div>
                {selected && path.length > 1 && <Typography.Paragraph type="secondary">{path.map((item) => item.name).join(' / ')}</Typography.Paragraph>}
                {selected?.description && <Typography.Paragraph>{selected.description}</Typography.Paragraph>}
                {selected?.asset_type && <Typography.Paragraph type="secondary">关联资产：{selected.name}（{selected.asset_type}）</Typography.Paragraph>}
                {!!selected?.children.length && <Space wrap style={{ marginBottom: 12 }}>{selected.children.map((child) => <Button key={child.id} size="small" onClick={() => changeParams({ scope: child.id })}>{child.name} · {child.case_count}</Button>)}</Space>}
                <Space wrap style={{ marginBottom: 8 }}>
                  <Input.Search key={keyword} defaultValue={keyword} allowClear placeholder={selected ? '搜索当前目录及子目录' : `搜索全部 ${direction} 用例`} onSearch={(value) => changeParams({ keyword: value })} style={{ width: 240 }} />
                  <Typography.Text>已选 {selectedCaseIds.length} 条</Typography.Text>
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
                {casesQuery.isError ? <QueryError error={casesQuery.error} onRetry={casesQuery.refetch} /> : <Table
                  size="small"
                  scroll={{ x: 1080 }}
                  rowKey="id"
                  loading={casesQuery.isFetching}
                  dataSource={casesQuery.data?.items ?? []}
                  rowSelection={{ selectedRowKeys: selectedCaseIds, preserveSelectedRowKeys: true, onChange: (keys) => setSelectedCaseIds(keys.map(Number)) }}
                  pagination={{ current: page, pageSize, total: casesQuery.data?.total ?? 0, showSizeChanger: true, pageSizeOptions: [10, 25, 50], onChange: (nextPage, size) => changeParams({ page: nextPage, page_size: size, projectId: currentProjectId }, false) }}
                  locale={{ emptyText: casesQuery.isPending ? '正在加载用例…' : <Space direction="vertical"><span>{keyword || priority || caseStatus || dimension !== 'ALL' ? '当前筛选无结果' : '此范围暂无用例'}</span>{keyword || priority || caseStatus || dimension !== 'ALL' ? <Button onClick={clearFilters}>清除筛选</Button> : <Space><Button onClick={() => changeParams({scope: undefined})}>查看当前方向全部用例</Button><Button onClick={() => launch('create')}>新建用例</Button></Space>}</Space> }}
                  columns={[
                    sequenceColumn<{ id: number }>({ page, pageSize }),
                    { title: '用例名称', dataIndex: 'name', ellipsis: true, render: (name: string, row: {id: number}) => <Button type="link" style={{ maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', display: 'block', textAlign: 'left', paddingInline: 0 }} title={name} onClick={() => changeParams({caseId: row.id, projectId: currentProjectId}, false)}>{name}</Button> },
                    { title: '优先级', dataIndex: 'priority', width: 80 },
                    { title: '维度', dataIndex: 'case_type', width: 100, render: (value: string) => DIMENSIONS.find((item) => item.value === value)?.label ?? value },
                    { title: '状态', dataIndex: 'status', width: 110 },
                    { title: '来源', dataIndex: 'source_type', width: 80, render: (value: string) => value === 'AI' ? 'AI' : '人工' },
                    { title: '测试点', dataIndex: 'test_point_name', width: '16%', ellipsis: true, render: (value: string | null) => value || '-' },
                    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: (value: string) => value?.replace('T', ' ').slice(0, 16) },
                  ]}
                />}
              </>
            )}
          </div>
        </Col>
      </Row>
      <Modal title="选择目标目录" open={!!targetAction} onCancel={() => setTargetAction(undefined)} okText="继续" onOk={() => { if (targetScopeId == null) { message.error('请选择目标目录'); return; } const action = targetAction; setTargetAction(undefined); if (action === 'create') setCreateOpen(true); else if (action === 'import') setImportExcelOpen(true); else if (action === 'generate') setGenerateOpen(true); }}><Select aria-label="目标目录" placeholder="选择目标目录" showSearch optionFilterProp="label" style={{width:'100%'}} value={targetScopeId} options={nodes.map((node) => ({value: node.id, label: node.name}))} onChange={setTargetScopeId} /></Modal>
      <NodeModal open={nodeModal != null} initial={nodeModal} onCancel={() => setNodeModal(null)} onSubmit={(values) => createNode.mutate(values)} />
      <Modal title="移动到范围" open={moveOpen} onCancel={() => setMoveOpen(false)} footer={null} destroyOnHidden>
        <Select
          showSearch
          style={{ width: '100%' }}
          placeholder="选择目标范围"
          options={nodes.map((node) => ({ value: node.id, label: node.name }))}
          onChange={(value) => moveCases.mutate(value)}
        />
      </Modal>
      <CreateCaseModal open={createOpen} onCancel={() => setCreateOpen(false)} onSubmit={(values) => createCase.mutate(values)} />
      <CaseExcelImportModal
        open={importExcelOpen}
        projectId={currentProjectId}
        direction={direction}
        scopeNodeId={targetScopeId ?? null}
        scopeNode={nodes.find((node) => node.id === targetScopeId) ?? null}
        onCancel={() => setImportExcelOpen(false)}
        onSuccess={() => { setImportExcelOpen(false); setSelectedCaseIds([]); refresh(); }}
      />
      <GenerationDrawer
        open={generateOpen}
        projectId={currentProjectId}
        direction={direction}
        scopeNodeId={targetScopeId}
        agents={agentsQuery.data ?? []}
        batch={batch}
        onClose={() => setGenerateOpen(false)}
        onBatch={setBatch}
        onChanged={refresh}
      />
      <CaseDetailDrawer detail={detailQuery.data} loading={detailQuery.isFetching} error={detailQuery.isError} onRetry={() => detailQuery.refetch()} open={detailId != null} onClose={() => changeParams({caseId: undefined}, false)} />
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
    <Modal title={initial?.mode === 'edit' ? '编辑范围' : '新建范围'} open={open} onCancel={onCancel} onOk={() => form.validateFields().then(onSubmit)} destroyOnHidden>
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
    <Modal title="手工用例" open={open} onCancel={onCancel} onOk={() => form.validateFields().then(onSubmit)} destroyOnHidden>
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
function CaseDetailDrawer({ detail, loading, error, onRetry, open, onClose }: { detail?: TestCaseDetail; loading: boolean; error: boolean; onRetry: () => void; open: boolean; onClose: () => void }) {
  return (
    <Drawer title={detail?.name ?? '用例详情'} open={open} width={760} onClose={onClose}>
      {loading && !detail ? <LoadingState /> : error ? <Alert type="error" message="详情加载失败" action={<Button onClick={onRetry}>重试</Button>} /> : !detail ? <EmptyState description="没有用例详情" /> : (
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
