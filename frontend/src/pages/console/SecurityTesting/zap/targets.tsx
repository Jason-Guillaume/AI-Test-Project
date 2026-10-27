// 安全扫描 · 子 Tab 1：扫描目标。
//
// 目标 CRUD + 列表带授权状态徽标。base_url 由后端 scope_guard 校验（协议 / 白名单 / 解析 IP），
// 前端不重复实现校验，也不为 base_url 提供默认值。
// 列表数组字段（allowed_hosts / include_paths / exclude_paths）在表单里用逗号分隔文本编辑。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { projectsApi } from '@/api/projects';
import { securityApi } from '@/api/securityTesting';
import type {
  ScanTarget,
  ScanTargetCreate,
  ScanTargetUpdate,
} from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import {
  AUTHORIZATION_STATUS_OPTIONS,
  authStatusLabel,
  authStatusColor,
  TARGET_TYPE_OPTIONS,
  targetTypeLabel,
} from './constants';

const PAGE_SIZE = 10;

/** 逗号分隔文本 → 字符串数组（去空白、去空项）。 */
function splitCsv(text: string | undefined): string[] {
  return (text ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 字符串数组 → 逗号分隔文本。 */
function joinCsv(list: string[] | undefined): string {
  return (list ?? []).join(', ');
}

/** 扫描目标子 Tab。projectId 由父页传入（已确保非空）。 */
export function TargetsSubTab({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [enabledFilter, setEnabledFilter] = useState<boolean | undefined>(undefined);
  const [drawer, setDrawer] = useState<{ mode: 'create' | 'edit'; data?: ScanTarget } | null>(
    null,
  );

  const listQuery = useQuery({
    queryKey: ['zap-targets', projectId, { enabled: enabledFilter, page }],
    queryFn: () =>
      securityApi.listScanTargets(projectId, {
        page,
        page_size: PAGE_SIZE,
        enabled: enabledFilter,
      }),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['zap-targets', projectId] });
  };

  const createMutation = useMutation({
    mutationFn: (body: ScanTargetCreate) => securityApi.createScanTarget(projectId, body),
    onSuccess: () => {
      message.success('扫描目标已创建');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: ScanTargetUpdate }) =>
      securityApi.updateScanTarget(projectId, id, body),
    onSuccess: () => {
      message.success('扫描目标已更新');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => securityApi.removeScanTarget(projectId, id),
    onSuccess: () => {
      message.success('扫描目标已删除');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const columns: TableColumnsType<ScanTarget> = [
    {
      title: '目标',
      dataIndex: 'name',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{r.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
            {r.base_url}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'target_type',
      width: 130,
      render: (v: string) => targetTypeLabel(v),
    },
    {
      title: '授权状态',
      dataIndex: 'authorization_status',
      width: 130,
      render: (v: string, r) => (
        <Tooltip title={r.authorization_note ?? undefined}>
          <Tag color={authStatusColor(v)}>{authStatusLabel(v)}</Tag>
        </Tooltip>
      ),
    },
    {
      title: '主动扫描',
      dataIndex: 'active_scan_allowed',
      width: 110,
      render: (v: boolean) =>
        v ? <Tag color="volcano">已允许</Tag> : <Tag>不允许</Tag>,
    },
    {
      title: '环境',
      width: 110,
      render: (_, r) =>
        r.is_production ? <Tag color="red">生产</Tag> : <Tag color="green">非生产</Tag>,
    },
    {
      title: '允许主机数',
      width: 110,
      render: (_, r) => r.allowed_hosts.length || '-',
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '操作',
      width: 150,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => setDrawer({ mode: 'edit', data: r })}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除该扫描目标？"
            description="删除后无法再用它发起扫描；已有任务记录不受影响。"
            onConfirm={() => removeMutation.mutate(r.id)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const { items, total, page_size } = listQuery.data ?? { items: [], total: 0, page_size: PAGE_SIZE };

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            allowClear
            placeholder="启用状态"
            style={{ width: 140 }}
            value={enabledFilter}
            onChange={(v) => {
              setEnabledFilter(v);
              setPage(1);
            }}
            options={[
              { value: true, label: '已启用' },
              { value: false, label: '已停用' },
            ]}
          />
          <Button type="primary" onClick={() => setDrawer({ mode: 'create' })}>
            新建扫描目标
          </Button>
        </Space>
      </Card>

      <Table<ScanTarget>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={
          total > page_size
            ? {
                current: page,
                pageSize: page_size,
                total,
                showSizeChanger: false,
                onChange: setPage,
              }
            : { pageSize: page_size, showSizeChanger: false }
        }
      />

      {drawer && (
        <TargetDrawer
          projectId={projectId}
          mode={drawer.mode}
          data={drawer.data}
          submitting={createMutation.isPending || updateMutation.isPending}
          onCancel={() => setDrawer(null)}
          onSubmit={(body, id) => {
            if (id != null) updateMutation.mutate({ id, body });
            else createMutation.mutate(body as ScanTargetCreate);
          }}
        />
      )}
    </div>
  );
}

/** 新建 / 编辑扫描目标抽屉。 */
function TargetDrawer({
  projectId,
  mode,
  data,
  submitting,
  onCancel,
  onSubmit,
}: {
  projectId: number;
  mode: 'create' | 'edit';
  data?: ScanTarget;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (body: ScanTargetUpdate, id?: number) => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<
    ScanTargetCreate & {
      allowed_hosts_text: string;
      include_paths_text: string;
      exclude_paths_text: string;
    }
  >();
  // mode/data 变化时重建表单初值。
  const formKey = `${mode}-${data?.id ?? 'new'}`;

  const environmentQuery = useQuery({
    queryKey: ['project-environments', projectId, 'zap-targets'],
    queryFn: () => projectsApi.listEnvironments(projectId),
    enabled: mode === 'create',
  });

  const environmentOptions = (environmentQuery.data?.items ?? [])
    .filter((e) => e.id != null)
    .map((e) => ({ value: e.id as number, label: `${e.display_name}（${e.name}）` }));

  const handleOk = async () => {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    if (mode === 'create' && !v.base_url.trim()) {
      message.error('请输入 base_url');
      return;
    }
    const body: ScanTargetCreate = {
      name: v.name.trim(),
      target_type: v.target_type,
      base_url: v.base_url.trim(),
      entry_url: v.entry_url?.trim() || null,
      environment_id: v.environment_id ?? null,
      enabled: v.enabled ?? true,
      authorization_status: v.authorization_status ?? 'AUTHORIZED',
      authorization_note: v.authorization_note?.trim() || null,
      active_scan_allowed: v.active_scan_allowed ?? false,
      allowed_hosts: splitCsv(v.allowed_hosts_text),
      include_paths: splitCsv(v.include_paths_text),
      exclude_paths: splitCsv(v.exclude_paths_text),
    };
    onSubmit(body, data?.id);
  };

  return (
    <Drawer
      title={mode === 'create' ? '新建扫描目标' : `编辑扫描目标 #${data?.id}`}
      open
      onClose={onCancel}
      width={600}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleOk}>
            保存
          </Button>
        </Space>
      }
    >
      <Form
        key={formKey}
        form={form}
        layout="vertical"
        initialValues={
          data
            ? {
                name: data.name,
                target_type: data.target_type,
                base_url: data.base_url,
                entry_url: data.entry_url ?? '',
                environment_id: data.environment_id,
                enabled: data.enabled,
                authorization_status: data.authorization_status,
                authorization_note: data.authorization_note ?? '',
                active_scan_allowed: data.active_scan_allowed,
                allowed_hosts_text: joinCsv(data.allowed_hosts),
                include_paths_text: joinCsv(data.include_paths),
                exclude_paths_text: joinCsv(data.exclude_paths),
              }
            : {
                target_type: 'HYBRID',
                enabled: true,
                authorization_status: 'AUTHORIZED',
                active_scan_allowed: false,
                allowed_hosts_text: '',
                include_paths_text: '',
                exclude_paths_text: '',
              }
        }
      >
        <Form.Item name="name" label="目标名称" rules={[{ required: true, message: '请输入目标名称' }]}>
          <Input maxLength={100} placeholder="如 订单服务（测试环境）" />
        </Form.Item>

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item
            name="target_type"
            label="目标类型"
            rules={[{ required: true, message: '请选择目标类型' }]}
            style={{ width: 200 }}
          >
            <Select options={TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="environment_id"
            label="环境"
            tooltip="选择生产环境时后端会把 is_production 置为 True，主动扫描会被直接拒绝。"
            style={{ width: 280 }}
          >
            <Select
              allowClear
              placeholder="未指定环境"
              options={environmentOptions}
              loading={environmentQuery.isLoading}
            />
          </Form.Item>
        </Space>

        <Form.Item
          name="base_url"
          label="base_url"
          rules={[{ required: true, message: '请输入 base_url' }]}
          tooltip="由后端 scope_guard 校验协议 / 主机白名单 / 解析 IP，不合法的地址会被拒绝。"
        >
          <Input
            placeholder="如 https://staging-api.example.com（必须是公网可解析地址）"
            maxLength={500}
          />
        </Form.Item>

        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="内网地址（10.x / 192.168.x / 172.16-31.x 等私网与保留地址）目前会被后端直接拒绝"
          description="一期为了防 SSRF，只放行明确解析到公网地址的目标；授权的内网测试环境需要单独的「授权私网段白名单」设计，属于后续阶段，不会在本阶段放宽。"
        />

        <Form.Item name="entry_url" label="入口 URL（Web 爬取起点）" tooltip="可选；仅 WEB / HYBRID 模式使用。">
          <Input
            placeholder="如 https://staging-api.example.com/login"
            maxLength={500}
          />
        </Form.Item>

        <Form.Item
          name="authorization_status"
          label="授权状态"
          tooltip="由人工按实际授权情况填写，扫描是否被允许由后端结合该状态与主动扫描开关独立判定。"
        >
          <Select options={AUTHORIZATION_STATUS_OPTIONS} />
        </Form.Item>

        <Form.Item name="authorization_note" label="授权说明">
          <Input.TextArea rows={2} maxLength={500} placeholder="如：安全负责人已书面批准，范围限测试环境" />
        </Form.Item>

        <Form.Item
          name="allowed_hosts_text"
          label="允许主机（allowed_hosts，逗号分隔）"
          tooltip="空表示只允许 base_url 的主机。"
        >
          <Input placeholder="如 staging-api.example.com:8443 或 api.example.com" />
        </Form.Item>

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="include_paths_text" label="包含路径" style={{ width: 280 }}>
            <Input placeholder="如 /api/v1/**" />
          </Form.Item>
          <Form.Item name="exclude_paths_text" label="排除路径" style={{ width: 280 }}>
            <Input placeholder="如 /health,/metrics" />
          </Form.Item>
        </Space>

        <Form.Item name="active_scan_allowed" label="允许主动扫描" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>

        {data && (
          <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="ID">{data.id}</Descriptions.Item>
            <Descriptions.Item label="生产环境">
              {data.is_production ? <Tag color="red">是</Tag> : <Tag color="green">否</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">{data.created_at ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{data.updated_at ?? '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Form>
    </Drawer>
  );
}
