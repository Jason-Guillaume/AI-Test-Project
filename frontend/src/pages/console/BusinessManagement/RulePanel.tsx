// 业务规则面板：展示与管理流程级的业务规则。
// 规则可关联到流程或具体步骤；表达式仅人工维护，第一阶段不自动执行（标记「未接入」）。
import { useState } from 'react';
import { App, Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/api/business';
import { getErrorMessage } from '@/api/client';
import { RULE_TYPE_OPTIONS } from './constants';
import type { BusinessAction, BusinessRule, BusinessRuleCreate } from '@/types';

const RULE_TYPE_LABELS: Record<string, { color: string; text: string }> = {
  GENERAL: { color: 'blue', text: '通用' },
  CONSTRAINT: { color: 'orange', text: '约束' },
  PRECONDITION: { color: 'purple', text: '前置' },
};

export function RulePanel({
  flowId,
  projectId,
  actions,
}: {
  flowId: number;
  projectId: number;
  actions: BusinessAction[];
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [editRule, setEditRule] = useState<{ id: number; values: Partial<BusinessRuleCreate> } | null>(null);
  const [form] = Form.useForm<BusinessRuleCreate>();

  const { data, isPending } = useQuery({
    queryKey: ['business', flowId, 'rules'],
    queryFn: () => businessApi.listRules(projectId, { page: 1, page_size: 100, flow_id: flowId }),
    enabled: flowId > 0,
  });
  const rules = data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: (body: BusinessRuleCreate) => businessApi.createRule(projectId, body),
    onSuccess: () => {
      message.success('规则已添加');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setAddOpen(false);
      form.resetFields();
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: Partial<BusinessRuleCreate> }) =>
      businessApi.updateRule(id, values),
    onSuccess: () => {
      message.success('规则已更新');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setEditRule(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (ruleId: number) => businessApi.removeRule(ruleId),
    onSuccess: () => {
      message.success('规则已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const actionName = (actionId: number | null) =>
    actionId == null ? '流程级' : actions.find((a) => a.id === actionId)?.name ?? `#${actionId}`;

  const columns = [
    { title: '规则名', dataIndex: 'name', width: 160 },
    {
      title: '类型',
      dataIndex: 'rule_type',
      width: 90,
      render: (v: string) => {
        const info = RULE_TYPE_LABELS[v] ?? { color: 'default', text: v };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '关联',
      dataIndex: 'action_id',
      width: 100,
      render: (v: number | null) => actionName(v),
    },
    {
      title: '表达式',
      dataIndex: 'expression',
      render: (v: string | null) => v ?? <span style={{ color: '#999' }}>—</span>,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 60,
      render: (v: boolean, r: { id: number; enabled: boolean }) => (
        <Switch
          size="small"
          checked={v}
          onChange={(checked) => updateMutation.mutate({ id: r.id, values: { enabled: checked } })}
        />
      ),
    },
    {
      title: '操作',
      key: 'op',
      width: 120,
      render: (_: unknown, r: BusinessRule) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditRule({ id: r.id, values: { name: r.name, description: r.description ?? undefined, rule_type: r.rule_type, expression: r.expression ?? undefined, enabled: r.enabled } });
              form.setFieldsValue(r);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除该规则？"
            onConfirm={() => deleteMutation.mutate(r.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Button
          size="small"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setAddOpen(true);
          }}
        >
          新增规则
        </Button>
        <Tag color="default">第一阶段：表达式仅人工维护，不自动执行（未接入）</Tag>
      </Space>
      {isPending ? (
        <Empty description="加载中" />
      ) : rules.length > 0 ? (
        <Table rowKey="id" columns={columns} dataSource={rules} pagination={false} size="small" />
      ) : (
        <Empty description="暂无业务规则" />
      )}

      <RuleFormModal
        open={addOpen || editRule != null}
        title={editRule ? '编辑规则' : '新增规则'}
        isEdit={editRule != null}
        onClose={() => {
          setAddOpen(false);
          setEditRule(null);
        }}
        onSubmit={async () => {
          const values = await form.validateFields();
          if (editRule) {
            await updateMutation.mutateAsync({ id: editRule.id, values });
          } else {
            await createMutation.mutateAsync({ ...values, flow_id: flowId });
          }
        }}
        form={form}
        actions={actions}
        submitting={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  );
}

function RuleFormModal({
  open,
  title,
  isEdit,
  onClose,
  onSubmit,
  form,
  actions,
  submitting,
}: {
  open: boolean;
  title: string;
  isEdit: boolean;
  onClose: () => void;
  onSubmit: () => Promise<void>;
  form: ReturnType<typeof Form.useForm<BusinessRuleCreate>>[0];
  actions: BusinessAction[];
  submitting: boolean;
}) {
  return (
    <Modal title={title} open={open} onCancel={onClose} onOk={onSubmit} confirmLoading={submitting} okText="保存" cancelText="取消" destroyOnClose width={560}>
      <Form<BusinessRuleCreate> form={form} layout="vertical" initialValues={{ rule_type: 'GENERAL', enabled: true }}>
        <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Space size="middle" style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="rule_type" label="类型" style={{ flex: 1, margin: 0 }}>
            <Select options={RULE_TYPE_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="action_id" label="关联步骤" style={{ flex: 1, margin: 0 }} tooltip={isEdit ? '编辑模式下关联步骤不可修改' : '留空表示流程级规则'}>
            <Select
              allowClear
              placeholder="流程级（不关联具体步骤）"
              options={actions.map((a) => ({ value: a.id, label: a.name }))}
              style={{ width: '100%' }}
              disabled={isEdit}
            />
          </Form.Item>
        </Space>
        <Form.Item name="expression" label="规则表达式" tooltip="第一阶段仅人工维护，不自动执行">
          <Input.TextArea rows={2} placeholder="如 task.status == CREATED" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}
