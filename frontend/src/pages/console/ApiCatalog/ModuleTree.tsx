// 左侧模块树：模块（最多两级）为文件夹节点，接口与子模块共同作为子节点。
// 模块 CRUD：顶部「新建模块」+ 节点内重命名/删除按钮（未分类不可删/改名）。
// 点击文件夹选中并展开模块；点击接口回调 onSelectApi。
import { useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Form, Input, Modal, Select, Space, Tag, Tree, Typography } from 'antd';
import { DeleteOutlined, EditOutlined, FolderOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { LoadingState, ErrorState } from '@/components/PageState';
import { METHOD_COLOR } from './constants';
import type { ApiInterface, ApiModule, ApiModuleCreate, ApiStatus } from '@/types';

interface TreeDataNode {
  key: string;
  title: React.ReactNode;
  children?: TreeDataNode[];
  selectable?: boolean;
}

/**
 * 模块树面板。
 *
 * 查询：模块列表 + 接口列表（page_size=200，按工具条过滤）。
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
  const expandedProjectId = useRef<number | null>(null);

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
        status,
      }),
  });

  useEffect(() => {
    if (modulesQuery.data && expandedProjectId.current !== projectId) {
      expandedProjectId.current = projectId;
      setExpandedKeys(modulesQuery.data.map((module) => `m:${module.id}`));
    }
  }, [projectId, modulesQuery.data]);

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
    const modulesByParent = new Map<number | null, ApiModule[]>();
    for (const module of modules) {
      const parentId = module.parent_id != null && modules.some((candidate) => candidate.id === module.parent_id)
        ? module.parent_id
        : null;
      const siblings = modulesByParent.get(parentId) ?? [];
      siblings.push(module);
      modulesByParent.set(parentId, siblings);
    }

    const makeApiNode = (api: ApiInterface): TreeDataNode => ({
        key: `a:${api.id}`,
        title: (
          <span className="api-module-api-title">
            <Tag color={METHOD_COLOR[api.method] ?? 'default'}>{api.method}</Tag>
            <Typography.Text className="api-module-name" title={`${api.name} · ${api.path}`}>
              {api.name}
            </Typography.Text>
          </span>
        ),
        selectable: true,
      });

    const makeModuleNode = (m: ApiModule): TreeDataNode => {
      const children = [
        ...(modulesByParent.get(m.id) ?? []).map(makeModuleNode),
        ...(byModule.get(m.id) ?? []).map(makeApiNode),
      ];
      return {
        key: `m:${m.id}`,
        title: (
          <span className="api-module-title">
            <FolderOutlined className="api-module-folder-icon" />
            <Typography.Text className="api-module-name" strong={m.is_default} title={m.name}>
              {m.name}
            </Typography.Text>
            <span className="api-module-count">{m.interface_count}</span>
            {!m.is_default && (
              <span className="api-module-actions">
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  aria-label={`重命名模块 ${m.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setRenameTarget(m);
                    renameForm.setFieldsValue({ name: m.name });
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label={`删除模块 ${m.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
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
              </span>
            )}
          </span>
        ),
        children: children.length ? children : undefined,
        selectable: true,
      };
    };

    return (modulesByParent.get(null) ?? []).map(makeModuleNode);
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
      <div className="api-module-tree-scroll">
        <Tree
          className="api-module-tree"
          treeData={treeData}
          expandedKeys={expandedKeys}
          onExpand={(keys) => setExpandedKeys(keys.map(String))}
          selectedKeys={selectedApiId ? [`a:${selectedApiId}`] : selectedModuleId ? [`m:${selectedModuleId}`] : []}
          onSelect={(_keys, info) => {
            const k = String(info.node.key);
            if (k && k.startsWith('a:')) {
              onSelectModule(null);
              onSelectApi(Number(k.slice(2)));
            } else if (k && k.startsWith('m:')) {
              const moduleId = Number(k.slice(2));
              onSelectApi(null);
              onSelectModule(moduleId);
              setExpandedKeys((current) => current.includes(k)
                ? current.filter((expandedKey) => expandedKey !== k)
                : [...current, k]);
            } else {
              onSelectModule(null);
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
