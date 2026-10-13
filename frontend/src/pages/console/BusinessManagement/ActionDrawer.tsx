// 步骤配置抽屉：接收已由聚合详情加载好的 BusinessActionDetail，
// 通过 Tab 配置该步骤的前置条件、输入/输出变量、状态定义与 API 绑定。
// 基本信息（名称/标识/描述/类型）在顶部区域直接编辑；子配置变更统一回调 onConfigChanged 刷新聚合详情。
import { useState } from 'react';
import { App, Button, Descriptions, Form, Input, Select, Space, Tabs, Tag } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { businessApi } from '@/api/business';
import { getErrorMessage } from '@/api/client';
import { ACTION_TYPE_OPTIONS } from './constants';
import { PreconditionEditor } from './PreconditionEditor';
import { VariableEditor } from './VariableEditor';
import { StateEditor } from './StateEditor';
import { BindingEditor } from './BindingEditor';
import type { BusinessActionDetail, BusinessActionUpdate } from '@/types';

const ACTION_TYPE_LABELS: Record<string, string> = {
  API: 'API',
  WEB: 'Web（预留）',
  MOBILE: '移动端（预留）',
};

export function ActionDrawer({
  projectId,
  action,
  onConfigChanged,
}: {
  projectId: number;
  action: BusinessActionDetail;
  onConfigChanged: () => void;
}) {
  const { message } = App.useApp();
  const [editOpen, setEditOpen] = useState(false);
  const [editForm] = Form.useForm<BusinessActionUpdate>();

  const updateMutation = useMutation({
    mutationFn: (body: BusinessActionUpdate) => businessApi.updateAction(action.id, body),
    onSuccess: () => {
      message.success('步骤基本信息已更新');
      setEditOpen(false);
      onConfigChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const binding = action.binding;
  const tabItems = [
    {
      key: 'preconditions',
      label: `前置条件（${action.preconditions.length}）`,
      children: <PreconditionEditor action={action} onChanged={onConfigChanged} />,
    },
    {
      key: 'variables',
      label: `变量（${action.input_variables.length + action.output_variables.length}）`,
      children: <VariableEditor action={action} onChanged={onConfigChanged} />,
    },
    {
      key: 'states',
      label: `状态定义（${action.states.length}）`,
      children: <StateEditor action={action} onChanged={onConfigChanged} />,
    },
    {
      key: 'binding',
      label: (
        <span>
          API 绑定
          {binding && <Tag color={binding.valid ? 'green' : 'red'} style={{ marginLeft: 4 }}>
            {binding.valid ? '有效' : '失效'}
          </Tag>}
        </span>
      ),
      children: <BindingEditor action={action} projectId={projectId} onChanged={onConfigChanged} />,
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <Space direction="vertical" size={2}>
          <Space size={8}>
            <span style={{ fontWeight: 600, fontSize: 15 }}>{action.name}</span>
            <Tag color="blue" style={{ fontSize: 11 }}>{ACTION_TYPE_LABELS[action.action_type] ?? action.action_type}</Tag>
          </Space>
          <span style={{ color: '#999', fontSize: 12 }}>
            业务标识：{action.action_key}
          </span>
        </Space>
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => {
            editForm.setFieldsValue({
              name: action.name,
              action_key: action.action_key,
              description: action.description ?? undefined,
              action_type: action.action_type,
              sort: action.sort,
            });
            setEditOpen(true);
          }}
        >
          编辑步骤
        </Button>
      </div>
      {action.description && (
        <div style={{ color: '#666', fontSize: 12, marginBottom: 8 }}>{action.description}</div>
      )}
      <Tabs items={tabItems} size="small" />

      <Descriptions column={1} size="small" style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
        <Descriptions.Item label="步骤 ID">{action.id}</Descriptions.Item>
        <Descriptions.Item label="所属流程 ID">{action.flow_id}</Descriptions.Item>
        <Descriptions.Item label="排序值">{action.sort}</Descriptions.Item>
      </Descriptions>

      {/* 编辑步骤基本信息 */}
      <Form
        form={editForm}
        layout="vertical"
        style={{ display: editOpen ? 'block' : 'none', marginTop: editOpen ? 8 : 0, padding: editOpen ? 12 : 0, border: editOpen ? '1px solid #e8e8e8' : 'none', borderRadius: editOpen ? 8 : 0 }}
      >
        <Form.Item name="name" label="步骤名称" rules={[{ required: true, message: '请输入步骤名称' }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Space size="middle" style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="action_key" label="业务标识" rules={[{ required: true, message: '请输入业务标识' }]} style={{ flex: 1, margin: 0 }}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="action_type" label="通道类型" style={{ flex: 1, margin: 0 }}>
            <Select options={ACTION_TYPE_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
        </Space>
        <Form.Item name="sort" label="排序值">
          <Input type="number" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
        <Space>
          <Button type="primary" size="small" loading={updateMutation.isPending} onClick={async () => {
            const values = await editForm.validateFields();
            await updateMutation.mutateAsync({
              name: values.name,
              action_key: values.action_key,
              description: values.description ?? null,
              action_type: values.action_type,
              sort: values.sort != null ? Number(values.sort) : undefined,
            });
          }}>
            保存
          </Button>
          <Button size="small" onClick={() => setEditOpen(false)}>取消</Button>
        </Space>
      </Form>
    </div>
  );
}
