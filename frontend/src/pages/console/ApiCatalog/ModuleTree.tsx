// 左侧模块树：模块（最多两级）为父节点，接口为子节点（Tag 方法 + 名称）。
// 模块 CRUD：顶部「新建模块」+ 节点内重命名/删除按钮（未分类不可删/改名）。
// 选中接口回调 onSelectApi；模块树与接口列表共用 ['api-catalog'] 缓存根。
import { useMemo, useState } from 'react';
import { App, Button, Form, Input, Modal, Select, Space, Tag, Tree, Typography } from 'antd';
import { DeleteOutlined, EditOutlined, FolderOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { LoadingState, ErrorState } from '@/components/PageState';
import { METHOD_COLOR } from './constants';
import type { ApiInterface, ApiModule, ApiModuleCreate } from '@/types';

interface TreeDataNode {
  key: string;
  title: React.ReactNode;
  children?: TreeDataNode[];
  selectable: boolean;
}

/**
 * 模块树面板。
 *
 * 查询：模块列表 + 接口列表（page_size=200，按工具条过滤）。
 * 构建树：模块为父节点，接口按 module_id 归入对应模块；module_id 为空归入「未分类」。
 */
export function ModuleTree({
  projectId,
  keyword,
  method,
  status,
  selectedApiId,
  onSelectApi,
}: {
  projectId: number;
  keyword: string;
  method: string | undefined;
  status: string | undefined;
  selectedApiId: number | null;
  onSelectApi: (id: number | null) => void;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ApiModule | null>(null);
  const [createForm] = Form.useForm<ApiModuleCreate & { parent_id?: number | null }>();
  const [renameForm] = Form.useForm<{ name: string }>();

  const modulesQuery = useQuery({
    queryKey: ['api-catalog', projectId, 'modules'],
    queryFn: () => apiCatalogApi.listModules(projectId),
  });
  const apisQuery = useQuery({
    queryKey: [
      'api-catalog',
      projectId,
      'apis',
      { page: 1, page_size: 200, keyword, method, status },
    ],
    queryFn: () =>
      apiCatalogApi.listApis(projectId, {
        page: 1,
        page_size: 200,
        keyword: keyword || undefined,
        method,
        status: status as never,
      }),
  });

  const createMutation = useMutation({
    mutationFn: (body: ApiModuleCreate) => apiCatalogApi.createModule(projectId, body),
    onSuccess: () => {
      message.success('模块已创建');
      queryClient.invalidateQueries({ queryKey: ['api-catalog', projectId, 'modules'] });
      setCreateOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      apiCatalogApi.updateModule(id, { name }),
    onSuccess: () => {
      message.success('已重命名');
      queryClient.invalidateQueries({ queryKey: ['api-catalog', projectId, 'modules'] });
      setRenameTarget(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '重命名失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiCatalogApi.removeModule(id),
    onSuccess: () => {
      message.success('模块已删除');
      queryClient.invalidateQueries({ queryKey: ['api-catalog', projectId] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const treeData = useMemo<TreeDataNode[]>(() => {
    const modules = modulesQuery.data ?? [];
    const apis = apisQuery.data?.items ?? [];
    // 按 module_id 分组；null 归入默认模块（未分类）。
    const defaultModule = modules.find((m) => m.is_default);
    const byModule = new Map<number | null, ApiInterface[]>();
    for (const a of apis) {
      const key = a.module_id ?? (defaultModule?.id ?? null);
      const list = byModule.get(key) ?? [];
      list.push(a);
      byModule.set(key, list);
    }
    return modules.map((m) => {
      const children = (byModule.get(m.id) ?? []).map((a) => ({
        key: `a:${a.id}`,
        title: (
          <Space size={4}>
            <Tag color={METHOD_COLOR[a.method] ?? 'default'} style={{ margin: 0 }}>
              {a.method}
            </Tag>
            <Typography.Text ellipsis style={{ maxWidth: 200 }}>
              {a.name}
            </Typography.Text>
          </Space>
        ),
        selectable: true,
      }));
      return {
        key: `m:${m.id}`,
        title: (
          <Space size={4} style={{ width: '100%' }} align="center">
            <FolderOutlined />
            <Typography.Text strong={m.is_default}>
              {m.is_default ? `${m.name}` : m.name}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              ({children.length})
            </Typography.Text>
            {!m.is_default && (
              <>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    setRenameTarget(m);
                    renameForm.setFieldsValue({ name: m.name });
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    modal.confirm({
                      title: `删除模块「${m.name}」？`,
                      content: '模块下的接口将归入「未分类」，不会被删除。',
                      okText: '删除',
                      okType: 'danger',
                      cancelText: '取消',
                      onOk: () => deleteMutation.mutateAsync(m.id),
                    });
                  }}
                />
              </>
            )}
          </Space>
        ),
        children,
        selectable: false,
      } as TreeDataNode;
    });
  }, [modulesQuery.data, apisQuery.data, renameForm, modal, deleteMutation]);

  if (modulesQuery.isPending || apisQuery.isPending) return <LoadingState tip="加载接口树..." />;
  if (modulesQuery.isError)
    return <ErrorState error={modulesQuery.error} onRetry={modulesQuery.refetch} />;
  if (apisQuery.isError)
    return <ErrorState error={apisQuery.error} onRetry={apisQuery.refetch} />;

  const parentOptions = (modulesQuery.data ?? [])
    .filter((m) => !m.is_default && m.parent_id == null)
    .map((m) => ({ label: m.name, value: m.id }));

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Space style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />} onClick={() => { createForm.resetFields(); setCreateOpen(true); }}>
          新建模块
        </Button>
      </Space>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <Tree
          treeData={treeData}
          defaultExpandAll
          selectedKeys={selectedApiId ? [`a:${selectedApiId}`] : []}
          onSelect={(keys) => {
            const k = keys[0] as string | undefined;
            if (k && k.startsWith('a:')) {
              onSelectApi(Number(k.slice(2)));
            } else {
              onSelectApi(null);
            }
          }}
          blockNode
        />
      </div>

      <Modal
        title="新建模块"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await createForm.validateFields();
          await createMutation.mutateAsync({
            name: values.name,
            parent_id: values.parent_id ?? null,
          });
        }}
        confirmLoading={createMutation.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            name="name"
            label="模块名"
            rules={[{ required: true, message: '请输入模块名' }]}
          >
            <Input maxLength={100} placeholder="如 用户" />
          </Form.Item>
          <Form.Item name="parent_id" label="父模块" tooltip="留空为一级模块；模块最多两级">
            <Select
              allowClear
              placeholder="（一级模块）"
              options={parentOptions}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="重命名模块"
        open={renameTarget != null}
        onCancel={() => setRenameTarget(null)}
        onOk={async () => {
          if (renameTarget == null) return;
          const values = await renameForm.validateFields();
          await renameMutation.mutateAsync({ id: renameTarget.id, name: values.name });
        }}
        confirmLoading={renameMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={renameForm} layout="vertical">
          <Form.Item
            name="name"
            label="模块名"
            rules={[{ required: true, message: '请输入模块名' }]}
          >
            <Input maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
