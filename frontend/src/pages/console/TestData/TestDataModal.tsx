// 测试数据资产 新增/编辑 弹窗。
//
// §7.2：name、entity_type、source、scope、status、description、value（JSON 文本）。
// 脱敏约定：后端把 value_json 里的敏感键替换成 ******。编辑时「留空表示不修改」——
// 即编辑态文本框初始为空，留空则不提交 value_json（保留服务端原值，避免把掩码写回）；
// 一旦填写即整体覆盖，提示用户勿粘贴含 ****** 的掩码。
import { useEffect } from 'react';
import { App, Form, Input, Modal, Select } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { getErrorMessage } from '@/api/client';
import {
  ASSET_SOURCE_OPTIONS,
  ASSET_STATUS_OPTIONS,
  FIXTURE_SCOPE_OPTIONS,
} from './constants';
import type { TestDataAsset, TestDataAssetCreate, TestDataAssetUpdate } from '@/types';

interface FormValues {
  name: string;
  entity_type: string;
  source?: string;
  scope?: string;
  status?: string;
  description?: string;
  value_text?: string;
}

/**
 * 资产新增/编辑弹窗。editing 为 null 表示新增。
 */
export function TestDataModal({
  open,
  onClose,
  projectId,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  editing: TestDataAsset | null;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();

  useEffect(() => {
    if (!open) return;
    if (editing) {
      // 编辑态：value_text 留空（不回显掩码），其余字段回填。
      form.setFieldsValue({
        name: editing.name,
        entity_type: editing.entity_type,
        source: editing.source,
        scope: editing.scope,
        status: editing.status,
        description: editing.description ?? undefined,
        value_text: '',
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        source: 'STATIC',
        scope: 'PROJECT',
        status: 'ACTIVE',
      });
    }
  }, [open, editing, form]);

  const createMutation = useMutation({
    mutationFn: (body: TestDataAssetCreate) => testDataApi.createAsset(projectId, body),
    onSuccess: () => {
      message.success('资产已创建');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'assets'] });
      onClose();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: (body: TestDataAssetUpdate) => testDataApi.updateAsset(editing!.id, body),
    onSuccess: () => {
      message.success('资产已更新');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'assets'] });
      onClose();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const handleOk = async () => {
    const values = await form.validateFields();
    const valueText = (values.value_text ?? '').trim();
    // 解析 JSON：填写了才校验与提交；留空则不修改（编辑态保留原值）。
    let parsedValue: Record<string, unknown> | null | undefined = undefined;
    if (valueText) {
      try {
        const parsed = JSON.parse(valueText);
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          message.error('value 必须是 JSON 对象');
          return;
        }
        parsedValue = parsed as Record<string, unknown>;
      } catch {
        message.error('value 不是合法 JSON');
        return;
      }
    }

    if (editing) {
      const body: TestDataAssetUpdate = {
        name: values.name,
        entity_type: values.entity_type,
        source: values.source as TestDataAssetUpdate['source'],
        scope: values.scope as TestDataAssetUpdate['scope'],
        status: values.status as TestDataAssetUpdate['status'],
        description: values.description || null,
      };
      if (parsedValue !== undefined) body.value_json = parsedValue;
      updateMutation.mutate(body);
    } else {
      const body: TestDataAssetCreate = {
        name: values.name,
        entity_type: values.entity_type,
        source: values.source as TestDataAssetCreate['source'],
        scope: values.scope as TestDataAssetCreate['scope'],
        status: values.status as TestDataAssetCreate['status'],
        description: values.description || null,
        value_json: parsedValue ?? {},
      };
      createMutation.mutate(body);
    }
  };

  const pending = createMutation.isPending || updateMutation.isPending;

  return (
    <Modal
      title={editing ? '编辑测试数据' : '新增测试数据'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={pending}
      okText="保存"
      cancelText="取消"
      destroyOnClose
      width={600}
    >
      <Form<FormValues> form={form} layout="vertical">
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: '请输入名称' }]}
        >
          <Input maxLength={200} placeholder="如 测试用户_001" />
        </Form.Item>
        <Form.Item
          name="entity_type"
          label="实体类型"
          rules={[{ required: true, message: '请输入实体类型' }]}
        >
          <Input maxLength={100} placeholder="如 user / order" />
        </Form.Item>
        <Form.Item name="source" label="来源">
          <Select options={ASSET_SOURCE_OPTIONS} />
        </Form.Item>
        <Form.Item name="scope" label="作用域">
          <Select options={FIXTURE_SCOPE_OPTIONS} />
        </Form.Item>
        <Form.Item name="status" label="状态">
          <Select options={ASSET_STATUS_OPTIONS} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
        <Form.Item
          name="value_text"
          label="value（JSON 对象）"
          tooltip={
            editing
              ? '留空表示不修改现有值；填写将整体覆盖，请勿粘贴含 ****** 的掩码'
              : 'JSON 对象，如 {"username":"alice","age":18}'
          }
        >
          <Input.TextArea
            rows={6}
            placeholder={
              editing
                ? '留空表示不修改现有值'
                : '{"username":"alice","age":18}'
            }
            style={{ fontFamily: 'monospace' }}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
