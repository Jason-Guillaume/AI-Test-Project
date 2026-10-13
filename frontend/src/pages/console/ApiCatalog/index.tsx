// 接口管理页（用户视角）。
// 左右布局：左侧模块树（模块+接口），右侧接口详情 6 Tab。
// 顶部工具条：搜索/方法/状态过滤 + 新建接口 + 导入 + 导入记录。
//
// 权限（服务端为准，前端隐藏只是辅助）：
//   - 读 = 项目可见（viewer+）；写 = 项目成员（member+）；调试 = 平台管理员。
//   - 跨项目越权按 404 返回，前端不展示。
//
// 未接入（明确标记，不虚报）：批量导出、接口版本对比、Mock 服务、AI 用例生成。
import { useState } from 'react';
import { App, Button, Col, Form, Input, Modal, Row, Select, Space, Tag } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { API_STATUS_OPTIONS, METHOD_OPTIONS } from './constants';
import { ApiToolbar } from './ApiToolbar';
import { ModuleTree } from './ModuleTree';
import { ApiDetail } from './ApiDetail';
import { ImportDialog } from './ImportDialog';
import type {
  ApiImportRecord,
  ApiInterfaceCreate,
  ApiModule,
  ApiStatus,
} from '@/types';

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
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const [keyword, setKeyword] = useState('');
  const [method, setMethod] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<ApiStatus | undefined>(undefined);
  const [selectedApiId, setSelectedApiId] = useState<number | null>(null);
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

  const createMutation = useMutation({
    mutationFn: (body: ApiInterfaceCreate) =>
      apiCatalogApi.createApi(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('接口已创建');
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
      setCreateOpen(false);
      setSelectedApiId(data.id);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const moduleOptions = modules.map((m) => ({
    label: m.is_default ? `${m.name}（默认）` : m.name,
    value: m.id,
  }));

  return (
    <PageContainer>
      <ApiToolbar
        keyword={keyword}
        setKeyword={(v) => setKeyword(v)}
        method={method}
        setMethod={setMethod}
        status={status}
        setStatus={setStatus}
        onCreate={() => {
          createForm.resetFields();
          setCreateOpen(true);
        }}
        onImport={() => setImportOpen(true)}
        onShowRecords={() => setRecordsOpen(true)}
      />

      <Row gutter={16}>
        <Col flex="320px">
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 8,
              height: 'calc(100vh - 200px)',
              minHeight: 400,
              overflow: 'hidden',
            }}
          >
            <ModuleTree
              projectId={currentProjectId}
              keyword={keyword}
              method={method}
              status={status}
              selectedApiId={selectedApiId}
              onSelectApi={setSelectedApiId}
            />
          </div>
        </Col>
        <Col flex="auto">
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 16,
              height: 'calc(100vh - 200px)',
              minHeight: 400,
              overflow: 'auto',
            }}
          >
            <ApiDetail
              apiId={selectedApiId}
              modules={modules}
              projectId={currentProjectId}
            />
          </div>
        </Col>
      </Row>

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
        destroyOnClose
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
          <Space size="middle" style={{ display: 'flex', gap: 12 }}>
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
          </Space>
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
      destroyOnClose
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : (
        <ResourceTable<ApiImportRecord>
          rowKey={(r) => r.id}
          columns={[
            {
              title: '来源',
              dataIndex: 'source_type',
              width: 90,
              render: (v: string) => <Tag>{v}</Tag>,
            },
            { title: '文件名', dataIndex: 'file_name', render: (v: string | null) => v ?? '-' },
            { title: '总数', dataIndex: 'total', width: 70 },
            {
              title: '新建/更新/跳过',
              key: 'counts',
              width: 150,
              render: (_: unknown, r: ApiImportRecord) => (
                <Space size={4}>
                  <Tag color="green">{r.created_count}</Tag>
                  <Tag color="orange">{r.updated_count}</Tag>
                  <Tag>{r.skipped_count}</Tag>
                </Space>
              ),
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 180,
              render: (v: string) => new Date(v).toLocaleString(),
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
