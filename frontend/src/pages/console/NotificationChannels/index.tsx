import { collectPages } from '@/api/pagination';
// 飞书通知渠道管理页：渠道 CRUD + 连通性测试 + 发送记录审计。
//
// 数据：
//   - GET/POST /projects/{project_id}/notification-channels  渠道列表 / 新建
//   - PATCH/DELETE /notification-channels/{channel_id}        编辑 / 删除
//   - POST   /notification-channels/{channel_id}/test        连通性测试（不关联报告）
//   - GET    /notification-channels/{channel_id}/records     渠道发送记录
//
// 安全红线：Webhook URL 与签名密钥只写不读——新建/编辑时明文提交，后端加密入库；
// 页面只展示 webhook_masked（脱敏 URL）与「是否已配置」，从不要求展示明文，也永不回显密钥。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
  PlusOutlined,
  SafetyOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { notificationChannelsApi } from '@/api/notificationChannels';
import { getErrorMessage } from '@/api/client';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { fmtTime } from '@/shared/format';
import { NOTIFY_CONDITION_OPTIONS, NOTIFY_STATUS_COLOR, NOTIFY_STATUS_OPTIONS } from '@/shared/notify';
import { labelOf } from '@/shared/options';
import type {
  ChannelCreateRequest,
  ChannelUpdateRequest,
  NotificationChannel,
  NotificationRecord,
  NotifyCondition,
  NotifyStatus,
} from '@/types';

interface ChannelFormValues {
  name: string;
  webhook_url: string;
  secret?: string;
  enabled: boolean;
  notify_condition: NotificationChannel['notify_condition'];
  keyword?: string;
}

/** 新建 / 编辑渠道弹窗。编辑时 webhook 与 secret 留空即保持不变。 */
function ChannelFormModal({
  open,
  editing,
  onClose,
  onSubmit,
  loading,
}: {
  open: boolean;
  editing: NotificationChannel | null;
  onClose: () => void;
  onSubmit: (values: ChannelFormValues) => void;
  loading: boolean;
}) {
  const [form] = Form.useForm<ChannelFormValues>();
  // 新建与编辑使用同一份弹窗；编辑时把渠道详情转成初始值（密钥不回填）。
  const initialValues: ChannelFormValues = editing
    ? formFieldsFromChannel(editing)
    : { name: '', webhook_url: '', secret: '', enabled: true, notify_condition: 'ALWAYS', keyword: '' };

  return (
    <Modal
      // key 让弹窗在「新建 / 编辑不同渠道」之间重新挂载，从而按 initialValues 重设字段值。
      key={editing ? `edit-${editing.id}` : 'create'}
      title={editing ? `编辑通知渠道：${editing.name}` : '新建飞书通知渠道'}
      open={open}
      onCancel={onClose}
      confirmLoading={loading}
      onOk={() => {
        form
          .validateFields()
          .then((values) => onSubmit(values))
          .catch(() => undefined);
      }}
    >
      <Form form={form} layout="vertical" initialValues={initialValues}>
        <Form.Item
          name="name"
          label="渠道名称"
          rules={[{ required: true, message: '请输入渠道名称' }, { max: 128 }]}
        >
          <Input placeholder="如：研发测试群" maxLength={128} />
        </Form.Item>
        <Form.Item
          name="webhook_url"
          label={editing ? 'Webhook URL（留空表示保持不变）' : 'Webhook URL'}
          rules={[
            ...(editing ? [] : [{ required: true, message: '请输入飞书 Webhook URL' }]),
            {
              pattern: /^https?:\/\//,
              message: '需为 http(s) 地址',
            },
          ]}
        >
          <Input.Password
            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
            autoComplete="new-password"
          />
        </Form.Item>
        <Form.Item
          name="secret"
          label={editing ? '签名密钥（留空表示保持不变；如需清除请删除并重建渠道）' : '签名密钥（可选）'}
        >
          <Input.Password placeholder="飞书机器人的签名校验密钥" autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="notify_condition" label="通知条件" rules={[{ required: true }]}>
          <Select options={NOTIFY_CONDITION_OPTIONS} />
        </Form.Item>
        <Form.Item name="keyword" label="关键词校验（可选）">
          <Input placeholder="飞书群自定义关键词" maxLength={64} />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="禁用" />
        </Form.Item>
      </Form>
      <Alert
        type="info"
        showIcon
        message="密钥安全"
        description="Webhook URL 与签名密钥提交后即加密入库，之后只能看到脱敏地址，系统不会在任何接口、报告或页面中回显明文。"
      />
    </Modal>
  );
}

/** 把渠道详情转成编辑弹窗的初始值；已配置的密钥不回填（后端不回吐明文）。 */
function formFieldsFromChannel(c: NotificationChannel): ChannelFormValues {
  return {
    name: c.name,
    webhook_url: '',
    secret: '',
    enabled: c.enabled,
    notify_condition: c.notify_condition,
    keyword: c.keyword ?? '',
  };
}

/** 渠道的发送记录抽屉。 */
function RecordsDrawer({
  channel,
  onClose,
}: {
  channel: NotificationChannel | null;
  onClose: () => void;
}) {
  const recordsQuery = useQuery({
    queryKey: ['channel-records', channel?.id],
    queryFn: () => notificationChannelsApi.listChannelRecords(channel!.id, { page: 1, page_size: 50 }),
    enabled: channel != null,
  });
  const records = recordsQuery.data?.items ?? [];

  const columns: TableColumnsType<NotificationRecord> = [
    { title: '记录ID', dataIndex: 'id', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: NotifyStatus) => (
        <Tag color={NOTIFY_STATUS_COLOR[v] ?? 'default'}>{labelOf(NOTIFY_STATUS_OPTIONS, v)}</Tag>
      ),
    },
    {
      title: '报告ID',
      dataIndex: 'report_id',
      width: 90,
      render: (v: number | null) => (v == null ? '（连通性测试）' : `#${v}`),
    },
    { title: '错误信息', dataIndex: 'error_message', render: (v: string | null) => v ?? '-' },
    { title: '发送时间', dataIndex: 'sent_at', width: 160, render: (v: string | null) => fmtTime(v) },
  ];

  return (
    <Drawer
      title={channel ? `发送记录 · ${channel.name}` : '发送记录'}
      open={channel != null}
      onClose={onClose}
      width={720}
    >
      {recordsQuery.isLoading ? (
        <LoadingState />
      ) : records.length === 0 ? (
        <Empty description="该渠道尚无发送记录" />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={records}
          pagination={false}
        />
      )}
    </Drawer>
  );
}

/** 飞书通知渠道管理页。 */
export function ConsoleNotificationChannelsPage() {
  const { currentProjectId } = useConsoleScope();
  const { message: msg } = App.useApp();
  const queryClient = useQueryClient();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<NotificationChannel | null>(null);
  const [recordsChannel, setRecordsChannel] = useState<NotificationChannel | null>(null);

  const channelsQuery = useQuery({
    queryKey: ['notification-channels', currentProjectId],
    queryFn: () =>
      collectPages((page) => notificationChannelsApi.list(currentProjectId!, { page, page_size: 100 })),
    enabled: currentProjectId != null,
  });
  const channels = channelsQuery.data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: (values: ChannelFormValues) =>
      notificationChannelsApi.create(currentProjectId!, values as ChannelCreateRequest),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notification-channels', currentProjectId] });
      msg.success('通知渠道已创建');
      setModalOpen(false);
      setEditing(null);
    },
    onError: (e) => msg.error(getErrorMessage(e, '创建渠道失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: ChannelUpdateRequest }) =>
      notificationChannelsApi.update(id, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notification-channels', currentProjectId] });
      msg.success('通知渠道已更新');
      setModalOpen(false);
      setEditing(null);
    },
    onError: (e) => msg.error(getErrorMessage(e, '更新渠道失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => notificationChannelsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notification-channels', currentProjectId] });
      msg.success('通知渠道已删除（其发送记录一并删除）');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除渠道失败')),
  });

  const testMutation = useMutation({
    mutationFn: (id: number) => notificationChannelsApi.test(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['channel-records'] });
      if (data.skipped) msg.warning('已跳过：渠道被禁用');
      else if (data.status === 'SUCCESS') msg.success('连通性测试成功，已收到测试卡片');
      else msg.error(`连通性测试失败：${data.error_message ?? '未知错误'}`);
    },
    onError: (e) => msg.error(getErrorMessage(e, '连通性测试失败')),
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const handleForm = (values: ChannelFormValues) => {
    if (editing) {
      // 编辑时留空的 webhook / secret 必须按「未传」提交，而不是空串：
      // 后端把空串当作「清除凭据」，直接透传会导致改个名字或改个开关就静默抹掉
      // 已保存的 webhook 与签名密钥，之后每次通知都失败（与「留空表示保持不变」相反）。
      const payload: ChannelUpdateRequest = {
        name: values.name,
        enabled: values.enabled,
        notify_condition: values.notify_condition,
        keyword: values.keyword,
      };
      if (values.webhook_url) payload.webhook_url = values.webhook_url;
      if (values.secret) payload.secret = values.secret;
      updateMutation.mutate({ id: editing.id, values: payload });
    } else {
      createMutation.mutate(values);
    }
  };

  const columns: TableColumnsType<NotificationChannel> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name', width: 180 },
    {
      title: '类型',
      dataIndex: 'channel_type',
      width: 140,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '通知条件',
      dataIndex: 'notify_condition',
      width: 190,
      render: (v: NotifyCondition) => <Tag color="blue">{labelOf(NOTIFY_CONDITION_OPTIONS, v)}</Tag>,
    },
    {
      title: 'Webhook（脱敏）',
      width: 240,
      render: (_, row) =>
        row.webhook_configured ? (
          <Typography.Text copyable={{ text: row.webhook_masked }} style={{ fontSize: 12 }}>
            {row.webhook_masked}
          </Typography.Text>
        ) : (
          <Tag color="red">未配置</Tag>
        ),
    },
    {
      title: '关键词',
      dataIndex: 'keyword',
      width: 130,
      render: (v: string | null) => v || '-',
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag>),
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => fmtTime(v) },
    {
      title: '操作',
      width: 290,
      fixed: 'right',
      render: (_, row) => (
        <Space size="small" wrap>
          <Button
            size="small"
            icon={<SendOutlined />}
            loading={testMutation.isPending}
            onClick={() => testMutation.mutate(row.id)}
          >
            连通性测试
          </Button>
          <Button
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => setRecordsChannel(row)}
          >
            发送记录
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditing(row);
              setModalOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除该通知渠道？"
            description="其发送记录将一并删除；不影响任何测试报告。"
            onConfirm={() => deleteMutation.mutate(row.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Flex vertical gap="2">
          <Typography.Title level={5} style={{ margin: 0 }}>
            飞书通知渠道
          </Typography.Title>
          <Typography.Text type="secondary">
            当前支持飞书群机器人；测试报告可推送到群内。任务与缺陷的站内消息不会自动通过此渠道发送。
          </Typography.Text>
        </Flex>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          新建渠道
        </Button>
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Alert
          type="warning"
          showIcon
          icon={<SafetyOutlined />}
          message="密钥只写不读"
          description="Webhook URL 与签名密钥仅在本页提交一次，后端加密存储；任何接口响应、测试报告、Agent 上下文与通知记录中都不会出现明文密钥。"
        />
      </Card>

      {channelsQuery.isLoading ? (
        <LoadingState />
      ) : channelsQuery.isError ? (
        <ErrorState error={channelsQuery.error} onRetry={channelsQuery.refetch} />
      ) : channels.length === 0 ? (
        <EmptyState description="尚未配置飞书通知渠道，点击右上角「新建渠道」开始" />
      ) : (
        <Table<NotificationChannel>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={channels}
          scroll={{ x: 1380 }}
          pagination={false}
        />
      )}

      <ChannelFormModal
        open={modalOpen}
        editing={editing}
        loading={createMutation.isPending || updateMutation.isPending}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onSubmit={handleForm}
      />

      <RecordsDrawer channel={recordsChannel} onClose={() => setRecordsChannel(null)} />
    </PageContainer>
  );
}
