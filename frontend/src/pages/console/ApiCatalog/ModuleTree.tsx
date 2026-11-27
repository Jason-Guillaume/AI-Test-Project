// 左侧接口目录树：模块（最多两级）为文件夹节点，接口与子模块共同作为子节点。
// 选择列固定在树最左侧：点击复选框只勾选，点击箭头只展开，点击名称打开该模块列表。
// 模块 CRUD：顶部「新建模块」+ 行尾更多菜单（重命名/删除）；未分类不可改名/删除。
// 「未分类」为系统保留节点，树中禁选；选择本页未分类接口明确放在右侧接口列表。
import { useMemo, useState } from 'react';
import { App, Button, Checkbox, Dropdown, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd';
import {
  DeleteOutlined,
  DownOutlined,
  EditOutlined,
  FolderOutlined,
  MoreOutlined,
  PlusOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi, type ApiModuleDeleteResult } from '@/features/api-catalog/api/apiCatalog';
import { getErrorMessage } from '@/shared/api/client';
import { collectPages } from '@/shared/api/pagination';
import { LoadingState, ErrorState } from '@/shared/ui/PageState';
import { METHOD_COLOR } from './constants';
import type { ApiInterface, ApiModule, ApiModuleCreate, ApiStatus } from '@/features/api-catalog/contracts';


type TreeDataNode =
  | { kind: 'module'; module: ApiModule; level: number; children?: TreeDataNode[] }
  | { kind: 'api'; api: ApiInterface; level: number };

/**
 * 模块树面板。
 *
 * 查询：模块列表 + 全部分页接口（按工具条过滤）。
 * 构建树：模块按 parent_id 嵌套，接口按 module_id 归入对应模块。
 * 选择：普通模块支持累加勾选、全选普通模块（排除未分类）与整棵子树预览删除；未分类禁选。
 */
export function ModuleTree({
  projectId,
  keyword,
  method,
  status,
  selectedApiId,
  selectedModuleId,
  selectedModuleIds,
  onModuleSelectionChange,
  onSelectApi,
  onSelectModule,
  onDeletedModules,
}: {
  projectId: number;
  keyword: string;
  method: string | undefined;
  status: ApiStatus | undefined;
  selectedApiId: number | null;
  selectedModuleId: number | null;
  selectedModuleIds: number[];
  onModuleSelectionChange: (ids: number[]) => void;
  onSelectApi: (id: number | null) => void;
  onSelectModule: (id: number | null) => void;
  onDeletedModules: (result: ApiModuleDeleteResult) => void;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ApiModule | null>(null);
  const [createForm] = Form.useForm<ApiModuleCreate & { parent_id?: number | null }>();
  const [renameForm] = Form.useForm<{ name: string }>();
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);

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
    queryFn: async () => (await collectPages((page) => apiCatalogApi.listApis(projectId, {
      page,
      page_size: 200,
      keyword: keyword || undefined,
      method,
      status,
    }))).items,
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
    mutationFn: (ids: number[]) => apiCatalogApi.deleteModules(projectId, ids),
    onSuccess: (result) => {
      message.success(`已将 ${result.module_count} 个模块和 ${result.interface_count} 个接口移入回收站`);
      onDeletedModules(result);
      queryClient.invalidateQueries({ queryKey: ['api-catalog', projectId] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const treeData = useMemo<TreeDataNode[]>(() => {
    const modules = modulesQuery.data ?? [];
    const apis = apisQuery.data ?? [];
    const defaultModule = modules.find((m) => m.is_default);
    const byModule = new Map<number | null, ApiInterface[]>();
    for (const api of apis) {
      const key = api.module_id ?? (defaultModule?.id ?? null);
      const list = byModule.get(key) ?? [];
      list.push(api);
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
    // 未分类始终排在根节点首位，其余按 sort 与 id 稳定排序。
    const sortModules = (items: ApiModule[]) => [...items].sort((a, b) =>
      Number(b.is_default) - Number(a.is_default) || a.sort - b.sort || a.id - b.id);

    const makeApiNode = (api: ApiInterface, level: number): TreeDataNode => ({ kind: 'api', api, level });
    const makeModuleNode = (module: ApiModule, level: number): TreeDataNode => {
      const children = [
        ...sortModules(modulesByParent.get(module.id) ?? []).map((child) => makeModuleNode(child, level + 1)),
        ...(byModule.get(module.id) ?? []).map((api) => makeApiNode(api, level + 1)),
      ];
      return {
        kind: 'module',
        module,
        level,
        children: children.length ? children : undefined,
      };
    };

    // 不再按接口数过滤未分类：目录入口必须常显，空页由复选框禁用而不是隐藏。
    return sortModules(modulesByParent.get(null) ?? []).map((module) => makeModuleNode(module, 0));
  }, [modulesQuery.data, apisQuery.data]);

  const normalModuleIds = useMemo(
    () => (modulesQuery.data ?? []).filter((module) => !module.is_default).map((module) => module.id),
    [modulesQuery.data],
  );
  const selectedNormalCount = normalModuleIds.filter((id) => selectedModuleIds.includes(id)).length;
  const allNormalSelected = normalModuleIds.length > 0 && selectedNormalCount === normalModuleIds.length;
  const indeterminateNormal = selectedNormalCount > 0 && selectedNormalCount < normalModuleIds.length;

  if (modulesQuery.isPending || apisQuery.isPending) return <LoadingState tip="加载接口树..." />;
  if (modulesQuery.isError)
    return <ErrorState error={modulesQuery.error} onRetry={modulesQuery.refetch} />;
  if (apisQuery.isError)
    return <ErrorState error={apisQuery.error} onRetry={apisQuery.refetch} />;

  const parentOptions = (modulesQuery.data ?? [])
    .filter((m) => !m.is_default && m.parent_id == null)
    .map((m) => ({ label: m.name, value: m.id }));

  const openModule = (module: ApiModule) => {
    onSelectApi(null);
    onSelectModule(module.id);
  };

  const toggleExpand = (module: ApiModule) => {
    const key = `m:${module.id}`;
    setExpandedKeys((current) => current.includes(key)
      ? current.filter((expandedKey) => expandedKey !== key)
      : [...current, key]);
  };

  /** 先取子树影响预览，确认后一次性移入回收站；预览失败时提供重试。 */
  const requestDelete = async (ids: number[]) => {
    if (!ids.length || previewing || deleteMutation.isPending) return;
    setPreviewing(true);
    try {
      const impact = await apiCatalogApi.previewModuleDelete(projectId, ids);
      modal.confirm({
        title: `移入回收站：${impact.root_names.join('、')}`,
        content: <div>
          <p>将删除整棵所选模块子树，并自动去重父子模块的重复选择。</p>
          <p>影响范围包含折叠中、当前筛选外以及分页外的子模块与接口：</p>
          <p><strong>{impact.module_count} 个模块，{impact.interface_count} 个接口</strong></p>
          <p>接口、模块层级及接口归属可从回收站恢复。</p>
        </div>,
        okText: '移入回收站',
        okType: 'danger',
        cancelText: '取消',
        onOk: () => deleteMutation.mutateAsync(ids),
      });
    } catch (error) {
      // 预览失败不能直接删除；保留所选 IDs，允许用户重试同一批模块。
      modal.confirm({
        title: '无法获取模块删除影响',
        content: getErrorMessage(error, '删除影响预览失败，请稍后重试'),
        okText: '重试',
        cancelText: '取消',
        onOk: () => requestDelete(ids),
      });
    } finally {
      setPreviewing(false);
    }
  };

  const renderNode = (node: TreeDataNode): React.ReactNode => {
    if (node.kind === 'api') {
      const { api } = node;
      return (
        <div
          key={`a:${api.id}`}
          className={`api-module-api-row${selectedApiId === api.id ? ' is-selected' : ''}`}
          role="treeitem"
          aria-selected={selectedApiId === api.id}
        >
          <span className="api-module-select-cell" aria-hidden="true" />
          <button
            type="button"
            className="api-module-api-open"
            style={{ paddingLeft: 8 + node.level * 16 }}
            title={`${api.method} ${api.path} · ${api.name}`}
            aria-label={`${api.method} ${api.path} · ${api.name}`}
            onClick={() => {
              onSelectModule(null);
              onSelectApi(api.id);
            }}
          >
            <Tag color={METHOD_COLOR[api.method] ?? 'default'} title={api.method}>{api.method}</Tag>
            <span className="api-module-api-name">{api.name}</span>
          </button>
        </div>
      );
    }

    const { module } = node;
    const key = `m:${module.id}`;
    const expanded = expandedKeys.includes(key);
    const hasChildren = Boolean(node.children?.length);
    const selected = selectedModuleId === module.id;
    const moduleChecked = selectedModuleIds.includes(module.id);
    const selectControl = module.is_default ? (
      <Checkbox
        aria-label="未分类模块不可删除"
        checked={false}
        disabled
        title="未分类为系统模块，不可删除；请点击进入右侧接口列表选择本页接口"
      />
    ) : (
      <Checkbox
        aria-label={`选择模块 ${module.name}`}
        checked={moduleChecked}
        onChange={(event) => {
          const next = event.target.checked
            ? [...selectedModuleIds, module.id]
            : selectedModuleIds.filter((id) => id !== module.id);
          onModuleSelectionChange([...new Set(next)]);
        }}
      />
    );

    return (
      <div key={key} className="api-module-tree-node" role="treeitem" aria-expanded={hasChildren ? expanded : undefined}>
        <div className={`api-module-row${selected ? ' is-selected' : ''}`}>
          <span className="api-module-select-cell">{selectControl}</span>
          <div className="api-module-main" style={{ paddingLeft: node.level * 16 }}>
            {hasChildren ? (
              <button
                type="button"
                className="api-module-caret-btn"
                aria-label={`${expanded ? '收起' : '展开'}模块 ${module.name}`}
                aria-expanded={expanded}
                onClick={() => toggleExpand(module)}
              >
                {expanded ? <DownOutlined className="api-module-caret" /> : <RightOutlined className="api-module-caret" />}
              </button>
            ) : (
              <span className="api-module-caret-spacer" aria-hidden="true" />
            )}
            <button
              type="button"
              className="api-module-open"
              title={module.name}
              aria-current={selected ? 'true' : undefined}
              onClick={() => openModule(module)}
            >
              <FolderOutlined className="api-module-folder-icon" />
              <span className={`api-module-name${module.is_default ? ' is-default' : ''}`}>{module.name}</span>
              <span className="api-module-count">{module.interface_count}</span>
            </button>
            {!module.is_default && (
              <span className="api-module-actions">
                <Dropdown
                  trigger={['click']}
                  menu={{
                    items: [
                      { key: 'rename', icon: <EditOutlined />, label: '重命名' },
                      { key: 'delete', icon: <DeleteOutlined />, danger: true, label: '删除模块' },
                    ],
                    onClick: ({ key: actionKey }) => {
                      if (actionKey === 'rename') {
                        setRenameTarget(module);
                        renameForm.setFieldsValue({ name: module.name });
                      } else if (actionKey === 'delete') {
                        void requestDelete([module.id]);
                      }
                    },
                  }}
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    aria-label={`更多操作 ${module.name}`}
                  />
                </Dropdown>
              </span>
            )}
          </div>
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
    <div className="api-module-tree-panel">
      <div className="api-module-toolbar">
        <Button size="small" icon={<PlusOutlined />} onClick={() => { createForm.resetFields(); setCreateOpen(true); }}>
          新建模块
        </Button>
        <Checkbox
          checked={allNormalSelected}
          indeterminate={indeterminateNormal}
          disabled={normalModuleIds.length === 0 || deleteMutation.isPending || previewing}
          onChange={(event) => onModuleSelectionChange(event.target.checked ? normalModuleIds : [])}
        >
          全选普通模块（{normalModuleIds.length}）
        </Checkbox>
        {selectedModuleIds.length > 0 ? (
          <Space size={4} wrap>
            <Typography.Text type="secondary">已选 {selectedModuleIds.length} 个模块</Typography.Text>
            <Button
              size="small"
              type="link"
              disabled={deleteMutation.isPending || previewing}
              onClick={() => onModuleSelectionChange([])}
            >
              清空
            </Button>
            <Button
              size="small"
              danger
              disabled={deleteMutation.isPending || previewing}
              loading={deleteMutation.isPending || previewing}
              onClick={() => { void requestDelete(selectedModuleIds); }}
            >
              删除模块
            </Button>
          </Space>
        ) : (
          <Typography.Text type="secondary">已选 0 个模块</Typography.Text>
        )}
      </div>
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
        destroyOnHidden
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
        destroyOnHidden
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