// 接口管理页（用户视角）。
// 左右布局：左侧模块树（模块+接口），右侧接口详情 6 Tab。
// 顶部工具条：搜索/方法/状态过滤 + 重置 + 新建接口 + 导入 + 导入记录。
// 窄屏隐藏固定侧栏，通过「切换目录」抽屉浏览模块，选中后回到接口列表/详情。
//
// 权限（服务端为准，前端隐藏只是辅助）：
//   - 读 = 项目可见（viewer+）；写 = 项目成员（member+）；调试 = 平台管理员。
//   - 跨项目越权按 404 返回，前端不展示。
//
// Mock 服务由独立的 Mock 管理工作区提供。
import { useCallback, useEffect, useState } from 'react';
import { App, Button, Col, Drawer, Form, Grid, Input, Modal, Row, Select, Space, Tag, Typography } from 'antd';
import { MenuOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi, type ApiModuleDeleteResult } from '@/features/api-catalog/api/apiCatalog';
import { getErrorMessage } from '@/shared/api/client';
import { sequenceColumn } from '@/shared/lib/sequence';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { API_STATUS_OPTIONS, METHOD_OPTIONS } from './constants';
import { ApiToolbar } from './ApiToolbar';
import { ModuleTree, type UnclassifiedSelectionState } from './ModuleTree';
import { ModuleApiList, type ModulePageMeta } from './ModuleApiList';
import { ApiDetail } from './ApiDetail';
import { ImportDialog } from './ImportDialog';
import './ApiCatalog.css';
import type { ApiImportRecord, ApiInterfaceCreate, ApiModule, ApiStatus } from '@/features/api-catalog/contracts';


interface CreateFormValues {
  name: string;
  method: string;
  path: string;
  module_id?: number | null;
  description?: string;
  auth_type?: string;
  content_type?: string;
  status?: ApiStatus;
}

/**
 * 接口管理页。
 *
 * 依赖当前项目作用域：未选项目时整页空态。切换项目由 useConsoleScope 失效 ['api-catalog']。
 */
export function ConsoleApiCatalogPage() {
  const { currentProjectId } = useConsoleScope();
  return <ApiCatalogWorkspace key={currentProjectId ?? 'none'} />;
}

function ApiCatalogWorkspace() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const screens = Grid.useBreakpoint();
  const isNarrow = screens.lg === false;

  const [keyword, setKeyword] = useState('');
  const [method, setMethod] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<ApiStatus | undefined>(undefined);
  const [selectedApiId, setSelectedApiId] = useState<number | null>(null);
  const [selectedModuleId, setSelectedModuleId] = useState<number | null>(null);
  // 模块与接口两类选择互斥，统一由页面持有，便于切换时集中确认。
  const [selectedModuleIds, setSelectedModuleIds] = useState<number[]>([]);
  const [selectedApiIds, setSelectedApiIds] = useState<number[]>([]);
  const [pageMeta, setPageMeta] = useState<ModulePageMeta>({ loading: false, ids: [] });
  const [pendingUnclassifiedSelect, setPendingUnclassifiedSelect] = useState(false);
  const [dirOpen, setDirOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [recordsOpen, setRecordsOpen] = useState(false);
  const [createForm] = Form.useForm<CreateFormValues>();

  // 页面级模块查询：供 ApiDetail(OverviewTab 移动模块) 与 ImportDialog 复用。
  const modulesQuery = useQuery({
    queryKey: ['api-catalog', currentProjectId, 'modules'],
    queryFn: () => apiCatalogApi.listModules(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const modules: ApiModule[] = modulesQuery.data ?? [];
  const defaultModule = modules.find((module) => module.is_default) ?? null;
  const selectedModule = modules.find((module) => module.id === selectedModuleId) ?? null;

  // 切换模块或筛选后先清空当前页元信息，等列表重新加载后再回填。
  useEffect(() => {
    setPageMeta({ loading: selectedModuleId != null, ids: [] });
  }, [selectedModuleId, keyword, method, status]);

  const handlePageMeta = useCallback((meta: ModulePageMeta) => setPageMeta(meta), []);

  // 未分类复选框：未打开时先打开列表，加载完成后再勾选当前筛选下的本页接口。
  useEffect(() => {
    if (!pendingUnclassifiedSelect) return;
    if (defaultModule == null || selectedModuleId !== defaultModule.id) return;
    if (pageMeta.loading) return;
    setPendingUnclassifiedSelect(false);
    if (pageMeta.ids.length) {
      setSelectedApiIds((ids) => [...new Set([...ids, ...pageMeta.ids])]);
    }
  }, [pendingUnclassifiedSelect, defaultModule, selectedModuleId, pageMeta]);

  useEffect(() => {
    if (
      selectedModuleId != null &&
      modulesQuery.data &&
      !modulesQuery.data.some((module) => module.id === selectedModuleId)
    ) {
      setSelectedModuleId(null);
    }
  }, [modulesQuery.data, selectedModuleId]);

  const createMutation = useMutation({
    mutationFn: (body: ApiInterfaceCreate) =>
      apiCatalogApi.createApi(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('接口已创建');
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
      setCreateOpen(false);
      setSelectedApiId(data.id);
      setSelectedModuleId(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const requestModuleSelection = useCallback((nextIds: number[]) => {
    const adding = nextIds.length > selectedModuleIds.length;
    const apply = () => setSelectedModuleIds(nextIds);
    if (!adding || selectedApiIds.length === 0) {
      apply();
      return;
    }
    modal.confirm({
      title: '切换为选择模块？',
      content: `已选择 ${selectedApiIds.length} 个接口，继续会清空这些接口勾选。`,
      okText: '继续',
      cancelText: '取消',
      onOk: () => {
        setSelectedApiIds([]);
        apply();
      },
    });
  }, [modal, selectedApiIds.length, selectedModuleIds.length]);

  const requestApiSelection = useCallback((nextIds: number[]) => {
    const adding = nextIds.length > selectedApiIds.length;
    const apply = () => setSelectedApiIds(nextIds);
    if (!adding || selectedModuleIds.length === 0) {
      apply();
      return;
    }
    modal.confirm({
      title: '切换为选择接口？',
      content: `已选择 ${selectedModuleIds.length} 个模块，继续会清空这些模块勾选。`,
      okText: '继续',
      cancelText: '取消',
      onOk: () => {
        setSelectedModuleIds([]);
        apply();
      },
    });
  }, [modal, selectedApiIds.length, selectedModuleIds.length]);

  const toggleUnclassified = useCallback(() => {
    if (defaultModule == null) return;
    const apply = () => {
      if (selectedModuleId !== defaultModule.id) {
        // 先打开未分类列表；当前页数据到达后由上面的 effect 完成本页勾选。
        setPendingUnclassifiedSelect(true);
        setSelectedModuleId(defaultModule.id);
        setSelectedApiId(null);
        return;
      }
      if (pageMeta.loading || pageMeta.ids.length === 0) return;
      const pageIds = pageMeta.ids;
      const allSelected = pageIds.every((id) => selectedApiIds.includes(id));
      setSelectedApiIds(allSelected
        ? selectedApiIds.filter((id) => !pageIds.includes(id))
        : [...new Set([...selectedApiIds, ...pageIds])]);
    };
    if (selectedModuleIds.length > 0) {
      modal.confirm({
        title: '切换为选择接口？',
        content: `已选择 ${selectedModuleIds.length} 个模块，继续会清空这些模块勾选。`,
        okText: '继续',
        cancelText: '取消',
        onOk: () => {
          setSelectedModuleIds([]);
          apply();
        },
      });
      return;
    }
    apply();
  }, [defaultModule, modal, pageMeta, selectedApiIds, selectedModuleId, selectedModuleIds.length]);

  const handleDeletedModules = useCallback((result: ApiModuleDeleteResult) => {
    setSelectedModuleIds((ids) => ids.filter((id) => !result.deleted_module_ids.includes(id)));
    setSelectedApiIds((ids) => ids.filter((id) => !result.deleted_interface_ids.includes(id)));
    setSelectedModuleId((current) => current != null && result.deleted_module_ids.includes(current) ? null : current);
    setSelectedApiId((current) => current != null && result.deleted_interface_ids.includes(current) ? null : current);
  }, []);

  const resetFilters = useCallback(() => {
    setKeyword('');
    setMethod(undefined);
    setStatus(undefined);
  }, []);

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const moduleOptions = modules.map((module) => ({
    label: module.is_default ? `${module.name}（默认）` : module.name,
    value: module.id,
  }));
  const selectedModulePath = (() => {
    if (!selectedModule) return '接口详情';
    const byId = new Map(modules.map((module) => [module.id, module]));
    const parent = selectedModule.parent_id != null ? byId.get(selectedModule.parent_id) : null;
    return parent ? `${parent.name} / ${selectedModule.name}` : selectedModule.name;
  })();

  const selectApi = (id: number | null) => {
    setSelectedApiId(id);
    if (id != null) setSelectedModuleId(null);
  };
  const selectModule = (id: number | null) => {
    setSelectedModuleId(id);
    if (id != null) setSelectedApiId(null);
  };

  const unclassifiedPage = selectedModuleId != null && defaultModule?.id === selectedModuleId
    ? pageMeta
    : { loading: false, ids: [] };
  const unclassifiedChecked = selectedModuleId === defaultModule?.id
    && unclassifiedPage.ids.length > 0
    && unclassifiedPage.ids.every((id) => selectedApiIds.includes(id));
  const unclassifiedIndeterminate = selectedModuleId === defaultModule?.id
    && !unclassifiedChecked
    && unclassifiedPage.ids.some((id) => selectedApiIds.includes(id));
  const unclassified: UnclassifiedSelectionState = {
    checked: unclassifiedChecked,
    indeterminate: unclassifiedIndeterminate,
    disabled: selectedModuleId === defaultModule?.id
      && (unclassifiedPage.loading || unclassifiedPage.ids.length === 0),
    onToggle: toggleUnclassified,
  };

  const openCreate = (moduleId: number | null) => {
    createForm.resetFields();
    createForm.setFieldsValue({ module_id: moduleId ?? undefined });
    setCreateOpen(true);
  };

  const moduleTree = (
    <ModuleTree
      projectId={currentProjectId}
      keyword={keyword}
      method={method}
      status={status}
      selectedApiId={selectedApiId}
      selectedModuleId={selectedModuleId}
      selectedModuleIds={selectedModuleIds}
      onModuleSelectionChange={requestModuleSelection}
      unclassified={unclassified}
      onSelectApi={(id) => {
        selectApi(id);
        setDirOpen(false);
      }}
      onSelectModule={(id) => {
        selectModule(id);
        setDirOpen(false);
      }}
      onDeletedModules={handleDeletedModules}
    />
  );

  const detailContent = selectedModule ? (
    <ModuleApiList
      key={selectedModule.id}
      projectId={currentProjectId}
      module={selectedModule}
      modulePath={selectedModulePath}
      keyword={keyword}
      method={method}
      status={status}
      selectedApiId={selectedApiId}
      onSelectApi={selectApi}
      selectedIds={selectedApiIds}
      onSelectionChange={requestApiSelection}
      onPageMeta={handlePageMeta}
      onClearFilters={resetFilters}
      onCreate={() => openCreate(selectedModule.is_default ? null : selectedModule.id)}
      onImport={() => setImportOpen(true)}
    />
  ) : (
    <ApiDetail
      apiId={selectedApiId}
      modules={modules}
      projectId={currentProjectId}
    />
  );

  return (
    <PageContainer>
      <div className="api-catalog-page">
        <ApiToolbar
          keyword={keyword}
          setKeyword={(value) => setKeyword(value)}
          method={method}
          setMethod={setMethod}
          status={status}
          setStatus={setStatus}
          onReset={resetFilters}
          onCreate={() => openCreate(null)}
          onImport={() => setImportOpen(true)}
          onShowRecords={() => setRecordsOpen(true)}
        />

        {isNarrow ? (
          <>
            <div className="api-catalog-mobile-bar">
              <Button icon={<MenuOutlined />} onClick={() => setDirOpen(true)}>切换目录</Button>
              <Typography.Text type="secondary" ellipsis style={{ minWidth: 0 }}>
                当前：{selectedModulePath}
              </Typography.Text>
            </div>
            <div className="api-catalog-panel detail-panel">{detailContent}</div>
            <Drawer
              title="接口目录"
              placement="left"
              width={320}
              open={dirOpen}
              onClose={() => setDirOpen(false)}
              className="api-catalog-drawer"
              destroyOnHidden
            >
              {moduleTree}
            </Drawer>
          </>
        ) : (
          <Row gutter={16} wrap={false} className="api-catalog-layout">
            <Col flex="320px" className="api-catalog-sidebar">
              <div className="api-catalog-panel">{moduleTree}</div>
            </Col>
            <Col flex="1 1 0" style={{ minWidth: 0 }} className="api-catalog-detail">
              <div className="api-catalog-panel detail-panel">{detailContent}</div>
            </Col>
          </Row>
        )}
      </div>

      {/* 新建接口弹窗 */}
      <Modal
        title="新建接口"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await createForm.validateFields();
          await createMutation.mutateAsync({
            ...values,
            description: values.description || null,
            auth_type: values.auth_type || 'none',
            content_type: values.content_type || 'application/json',
            status: values.status || 'DRAFT',
            module_id: values.module_id ?? null,
          });
        }}
        confirmLoading={createMutation.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnHidden
        width={560}
      >
        <Form<CreateFormValues> form={createForm} layout="vertical" initialValues={{ method: 'GET', status: 'DRAFT' }}>
          <Form.Item
            name="name"
            label="接口名"
            rules={[{ required: true, message: '请输入接口名' }]}
          >
            <Input maxLength={200} placeholder="如 创建任务" />
          </Form.Item>
          <Form.Item name="module_id" label="所属模块" tooltip="留空归入未分类">
            <Select allowClear placeholder="未分类" options={moduleOptions} showSearch optionFilterProp="label" />
          </Form.Item>
          <div className="form-field-row">
            <Form.Item
              name="method"
              label="方法"
              style={{ flex: 1, margin: 0 }}
              rules={[{ required: true, message: '请选择方法' }]}
            >
              <Select options={METHOD_OPTIONS} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="status"
              label="状态"
              style={{ flex: 1, margin: 0 }}
            >
              <Select options={API_STATUS_OPTIONS} style={{ width: '100%' }} />
            </Form.Item>
          </div>
          <Form.Item
            name="path"
            label="路径"
            rules={[{ required: true, message: '请输入路径' }]}
          >
            <Input maxLength={500} placeholder="/api/v1/tasks" />
          </Form.Item>
          <Form.Item name="auth_type" label="鉴权类型">
            <Input maxLength={30} placeholder="none / bearer / api-key" />
          </Form.Item>
          <Form.Item name="content_type" label="Content-Type">
            <Input maxLength={100} placeholder="application/json" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        projectId={currentProjectId}
        modules={modules}
      />

      <ImportRecordsModal
        open={recordsOpen}
        onClose={() => setRecordsOpen(false)}
        projectId={currentProjectId}
      />
    </PageContainer>
  );
}

// 导入记录弹窗：独立子组件，避免主页面 state 膨胀。
function ImportRecordsModal({
  open,
  onClose,
  projectId,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
}) {
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  const query = useQuery({
    queryKey: ['api-catalog', projectId, 'import-records', pagination],
    queryFn: () => apiCatalogApi.listImportRecords(projectId, pagination),
    enabled: open,
  });

  return (
    <Modal
      title="导入记录"
      open={open}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={860}
      destroyOnHidden
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : (
        <ResourceTable<ApiImportRecord>
          rowKey={(row) => row.id}
          columns={[
            sequenceColumn<ApiImportRecord>({ page: pagination.page, pageSize: pagination.page_size }),
            {
              title: '来源',
              dataIndex: 'source_type',
              width: 90,
              render: (value: string) => <Tag>{value}</Tag>,
            },
            { title: '文件名', dataIndex: 'file_name', render: (value: string | null) => value ?? '-' },
            { title: '总数', dataIndex: 'total', width: 70 },
            {
              title: '新建/更新/跳过',
              key: 'counts',
              width: 150,
              render: (_: unknown, row: ApiImportRecord) => (
                <Space size={4}>
                  <Tag color="green">{row.created_count}</Tag>
                  <Tag color="orange">{row.updated_count}</Tag>
                  <Tag>{row.skipped_count}</Tag>
                </Space>
              ),
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 180,
              render: (value: string) => new Date(value).toLocaleString(),
            },
          ]}
          dataSource={query.data.items}
          loading={query.isFetching}
          total={query.data.total}
          pagination={pagination}
          onPaginationChange={setPagination}
          emptyText="暂无导入记录"
        />
      )}
    </Modal>
  );
}