// 左侧模块树：模块（最多两级）为文件夹节点，接口与子模块共同作为子节点。
// 模块 CRUD：顶部「新建模块」+ 节点内重命名/删除按钮（未分类不可删/改名）。
// 点击文件夹选中并展开模块；点击接口回调 onSelectApi。
import { useMemo, useState } from 'react';
import { App, Button, Form, Input, Modal, Select, Space, Tag } from 'antd';
import { DeleteOutlined, DownOutlined, EditOutlined, FolderOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { LoadingState, ErrorState } from '@/components/PageState';
import { METHOD_COLOR } from './constants';
import type { ApiInterface, ApiModule, ApiModuleCreate, ApiStatus } from '@/types';

type TreeDataNode =
  | { kind: 'module'; module: ApiModule; children?: TreeDataNode[] }
  | { kind: 'api'; api: ApiInterface };

/**
 * 模块树面板。
 *
 * 查询：模块列表 + 全部分页接口（按工具条过滤）。
 * 构建树：模块按 parent_id 嵌套，接口按 module_id 归入对应模块。
 */
export function ModuleTree({
  projectId,
  keyword,
  method,
  status,
  selectedApiId,
  selectedModuleId,
  onSelectApi,
  onSelectModule,
}: {
  projectId: number;
  keyword: string;
  method: string | undefined;
  status: ApiStatus | undefined;
  selectedApiId: number | null;
  selectedModuleId: number | null;
  onSelectApi: (id: number | null) => void;
  onSelectModule: (id: number | null) => void;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ApiModule | null>(null);
  const [createForm] = Form.useForm<ApiModuleCreate & { parent_id?: number | null }>();
  const [renameForm] = Form.useForm<{ name: string }>();
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);

  const modulesQuery = useQuery({
    queryKey: ['api-catalog', projectId, 'modules'],
    queryFn: () => apiCatalogApi.listModules(projectId),
  });
  const apisQuery = useQuery({
    queryKey: [
      'api-catalog',
      projectId,
      'tree-apis',
      { keyword, method, status },
    ],
    queryFn: async () => {
      const params = { page_size: 200, keyword: keyword || undefined, method, status };
      const first = await apiCatalogApi.listApis(projectId, { ...params, page: 1 });
      const pages = Math.ceil(first.total / params.page_size);
      const rest = await Promise.all(
        Array.from({ length: Math.max(0, pages - 1) }, (_, index) =>
          apiCatalogApi.listApis(projectId, { ...params, page: index + 2 })),
      );
      return [...first.items, ...rest.flatMap((page) => page.items)];
    },
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
    const apis = apisQuery.data ?? [];
    // 按 module_id 分组；null 归入默认模块（未分类）。
    const defaultModule = modules.find((m) => m.is_default);
    const byModule = new Map<number | null, ApiInterface[]>();
    for (const a of apis) {
      const key = a.module_id ?? (defaultModule?.id ?? null);
      const list = byModule.get(key) ?? [];
      list.push(a);
      byModule.set(key, list);
    }
    const modulesByParent = new Map<number | null, ApiModule[]>();
    for (const module of modules) {
      const parentId = module.parent_id != null && modules.some((candidate) => candidate.id === module.parent_id)
        ? module.parent_id
        : null;
      const siblings = modulesByParent.get(parentId) ?? [];
      siblings.push(module);
      modulesByParent.set(parentId, siblings);
    }

    const makeApiNode = (api: ApiInterface): TreeDataNode => ({ kind: 'api', api });

    const makeModuleNode = (m: ApiModule): TreeDataNode => {
      const children = [
        ...(modulesByParent.get(m.id) ?? []).map(makeModuleNode),
        ...(byModule.get(m.id) ?? []).map(makeApiNode),
      ];
      return {
        kind: 'module',
        module: m,
        children: children.length ? children : undefined,
      };
    };

    return (modulesByParent.get(null) ?? [])
      .filter((module) => !module.is_default || module.interface_count > 0 || (byModule.get(module.id)?.length ?? 0) > 0 || (modulesByParent.get(module.id)?.length ?? 0) > 0)
      .map(makeModuleNode);
  }, [modulesQuery.data, apisQuery.data]);

  if (modulesQuery.isPending || apisQuery.isPending) return <LoadingState tip="加载接口树..." />;
  if (modulesQuery.isError)
    return <ErrorState error={modulesQuery.error} onRetry={modulesQuery.refetch} />;
  if (apisQuery.isError)
    return <ErrorState error={apisQuery.error} onRetry={apisQuery.refetch} />;

  const parentOptions = (modulesQuery.data ?? [])
    .filter((m) => !m.is_default && m.parent_id == null)
    .map((m) => ({ label: m.name, value: m.id }));

  const toggleModule = (module: ApiModule) => {
    const key = `m:${module.id}`;
    onSelectApi(null);
    onSelectModule(module.id);
    setExpandedKeys((current) => current.includes(key)
      ? current.filter((expandedKey) => expandedKey !== key)
      : [...current, key]);
  };

  const renderNode = (node: TreeDataNode): React.ReactNode => {
    if (node.kind === 'api') {
      const { api } = node;
      return (
        <button
          key={`a:${api.id}`}
          type="button"
          className={`api-module-api-row${selectedApiId === api.id ? ' is-selected' : ''}`}
          title={`${api.method} ${api.path} · ${api.name}`}
          onClick={() => {
            onSelectModule(null);
            onSelectApi(api.id);
          }}
        >
          <Tag color={METHOD_COLOR[api.method] ?? 'default'}>{api.method}</Tag>
          <span className="api-module-api-name">{api.name}</span>
        </button>
      );
    }

    const { module } = node;
    const key = `m:${module.id}`;
    const expanded = expandedKeys.includes(key);
    return (
      <div key={key} className="api-module-tree-node">
        <div className={`api-module-row${selectedModuleId === module.id ? ' is-selected' : ''}`}>
          <button
            type="button"
            className="api-module-trigger"
            aria-expanded={expanded}
            title={module.name}
            onClick={() => toggleModule(module)}
          >
            {expanded ? <DownOutlined className="api-module-caret" /> : <RightOutlined className="api-module-caret" />}
            <FolderOutlined className="api-module-folder-icon" />
            <span className={`api-module-name${module.is_default ? ' is-default' : ''}`}>{module.name}</span>
            <span className="api-module-count">{module.interface_count}</span>
          </button>
          {!module.is_default && (
            <span className="api-module-actions">
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                aria-label={`重命名模块 ${module.name}`}
                onClick={() => {
                  setRenameTarget(module);
                  renameForm.setFieldsValue({ name: module.name });
                }}
              />
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label={`删除模块 ${module.name}`}
                onClick={() => {
                  modal.confirm({
                    title: `删除模块「${module.name}」？`,
                    content: '模块下的接口将归入「未分类」，不会被删除。',
                    okText: '删除',
                    okType: 'danger',
                    cancelText: '取消',
                    onOk: () => deleteMutation.mutateAsync(module.id),
                  });
                }}
              />
            </span>
          )}
        </div>
        {expanded && node.children?.length ? (
          <div className="api-module-children" role="group">
            {node.children.map(renderNode)}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Space style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />} onClick={() => { createForm.resetFields(); setCreateOpen(true); }}>
          新建模块
        </Button>
      </Space>
      <div className="api-module-tree-scroll">
        <div className="api-module-tree" role="tree" aria-label="接口模块">
          {treeData.map(renderNode)}
        </div>
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
