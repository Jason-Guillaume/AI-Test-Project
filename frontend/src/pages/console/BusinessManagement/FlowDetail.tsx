// 流程详情：一次拉取聚合详情（动作+前置条件+变量+状态+绑定+映射+引用+规则），
// 三个 Tab 共享同一份数据，避免切 Tab 时重复请求。
// 点击步骤打开 ActionDrawer 配置单步子配置。
import { useState } from 'react';
import {
  App,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tag,
} from 'antd';
import { EditOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/api/business';
import { getErrorMessage } from '@/api/client';
import { ErrorState } from '@/components/PageState';
import { FLOW_STATUS_OPTIONS } from './constants';
import { FlowSteps } from './FlowSteps';
import { VariableRefPanel } from './VariableRefPanel';
import { RulePanel } from './RulePanel';
import { ActionDrawer } from './ActionDrawer';
import type { BusinessActionCreate, BusinessFlowUpdate, BusinessFlowStatus } from '@/types';

const FLOW_STATUS_LABELS: Record<string, { color: string; text: string }> = {
  DRAFT: { color: 'blue', text: '草稿' },
  ACTIVE: { color: 'green', text: '已上线' },
  DEPRECATED: { color: 'default', text: '已废弃' },
};

export function FlowDetail({ flowId, projectId }: { flowId: number; projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [editForm] = Form.useForm<BusinessFlowUpdate>();
  const [actionCreateOpen, setActionCreateOpen] = useState(false);
  const [actionCreateForm] = Form.useForm<BusinessActionCreate>();
  const [selectedActionId, setSelectedActionId] = useState<number | null>(null);
  const [detailRefresh, setDetailRefresh] = useState(0);

  const detailQuery = useQuery({
    queryKey: ['business', flowId, 'detail'],
    queryFn: () => businessApi.getFlowDetail(flowId),
    enabled: flowId > 0,
  });
  const detail = detailQuery.data;

  const editMutation = useMutation({
    mutationFn: (body: BusinessFlowUpdate) => businessApi.updateFlow(flowId, body),
    onSuccess: () => {
      message.success('流程已更新');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setEditOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const createActionMutation = useMutation({
    mutationFn: (body: BusinessActionCreate) =>
      businessApi.createAction(flowId, body),
    onSuccess: () => {
      message.success('步骤已添加');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setActionCreateOpen(false);
      actionCreateForm.resetFields();
      setDetailRefresh((n) => n + 1);
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const deleteActionMutation = useMutation({
    mutationFn: (actionId: number) => businessApi.removeAction(actionId),
    onSuccess: () => {
      message.success('步骤已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setSelectedActionId(null);
      setDetailRefresh((n) => n + 1);
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  if (detailQuery.isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (detailQuery.isError)
    return <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />;
  if (!detail) return <Empty />;

  const statusInfo = FLOW_STATUS_LABELS[detail.status] ?? { color: 'default', text: detail.status };

  const tabItems = [
    {
      key: 'steps',
      label: `步骤编排（${detail.actions.length}）`,
      children: (
        <FlowSteps
          actions={detail.actions}
          onReorder={() => {
            queryClient.invalidateQueries({ queryKey: ['business'] });
            setDetailRefresh((n) => n + 1);
          }}
          onDelete={(actionId) => deleteActionMutation.mutate(actionId)}
          deleting={deleteActionMutation.isPending}
          onAdd={() => {
            actionCreateForm.resetFields();
            setActionCreateOpen(true);
          }}
          onSelectAction={setSelectedActionId}
        />
      ),
    },
    {
      key: 'refs',
      label: '变量引用',
      children: <VariableRefPanel flowId={flowId} actions={detail.actions} refreshKey={detailRefresh} />,
    },
    {
      key: 'rules',
      label: '业务规则',
      children: <RulePanel flowId={flowId} projectId={projectId} actions={detail.actions} />,
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <Space direction="vertical" size={0}>
          <Space size={8}>
            <span style={{ fontWeight: 600, fontSize: 16 }}>{detail.name}</span>
            <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
          </Space>
          <span style={detail.description ? undefined : { color: '#999' }}>
            {detail.description ?? '暂无描述'}
          </span>
          <span style={{ color: '#999', fontSize: 12 }}>
            所属业务域：{detail.domain_name ?? '-'}
          </span>
        </Space>
        <Button size="small" icon={<EditOutlined />} onClick={() => {
          editForm.setFieldsValue({ name: detail.name, description: detail.description ?? undefined, status: detail.status as BusinessFlowStatus });
          setEditOpen(true);
        }}>
          编辑流程
        </Button>
      </div>

      <Tabs items={tabItems} size="small" />

      {/* 编辑流程弹窗 */}
      <Modal
        title="编辑业务流程"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={async () => {
          const values = await editForm.validateFields();
          await editMutation.mutateAsync(values);
        }}
        confirmLoading={editMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<BusinessFlowUpdate> form={editForm} layout="vertical">
          <Form.Item name="name" label="流程名称" rules={[{ required: true, message: '请输入流程名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={FLOW_STATUS_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增步骤弹窗 */}
      <Modal
        title="新增业务步骤"
        open={actionCreateOpen}
        onCancel={() => setActionCreateOpen(false)}
        onOk={async () => {
          const values = await actionCreateForm.validateFields();
          await createActionMutation.mutateAsync({
            name: values.name,
            action_key: values.action_key,
            description: values.description || null,
            action_type: values.action_type || 'API',
            sort: values.sort ?? 0,
          });
        }}
        confirmLoading={createActionMutation.isPending}
        okText="添加"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<BusinessActionCreate>
          form={actionCreateForm}
          layout="vertical"
          initialValues={{ action_type: 'API' }}
        >
          <Form.Item name="name" label="步骤名称" rules={[{ required: true, message: '请输入步骤名称' }]}>
            <Input maxLength={200} placeholder="如 创建任务" />
          </Form.Item>
          <Form.Item
            name="action_key"
            label="业务标识"
            tooltip="稳定标识，不依赖接口 ID，如 CREATE_TASK"
            rules={[{ required: true, message: '请输入业务标识' }]}
          >
            <Input maxLength={100} placeholder="如 CREATE_TASK" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 步骤配置抽屉 */}
      <Drawer
        title="步骤配置"
        placement="right"
        width={720}
        open={selectedActionId != null}
        onClose={() => setSelectedActionId(null)}
      >
        {selectedActionId != null && detail.actions.some((a) => a.id === selectedActionId) && (
          <ActionDrawer
            projectId={projectId}
            action={detail.actions.find((a) => a.id === selectedActionId)!}
            onConfigChanged={() => {
              queryClient.invalidateQueries({ queryKey: ['business'] });
              setDetailRefresh((n) => n + 1);
            }}
          />
        )}
      </Drawer>
    </div>
  );
}
