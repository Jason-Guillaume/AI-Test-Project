// Fixture 基本信息表单。
//
// §7.3：name、fixture_key、entity_type、description、scope、status、cache_enabled、cleanup_policy。
// fixture_key 创建后不可改（后端 FixtureUpdate 不含该字段），以只读展示。
import { useEffect } from 'react';
import { App, Button, Form, Input, Select, Switch } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { getErrorMessage } from '@/api/client';
import {
  FIXTURE_CLEANUP_POLICY_OPTIONS,
  FIXTURE_SCOPE_OPTIONS,
  FIXTURE_STATUS_OPTIONS,
} from './constants';
import type { FixtureDetail, FixtureUpdate } from '@/types';

interface FormValues {
  name: string;
  entity_type: string;
  description?: string;
  scope: string;
  status: string;
  cache_enabled: boolean;
  cleanup_policy: string;
}

/**
 * 基本信息表单：回填当前值，保存走 PATCH /fixtures/{id}。
 */
export function FixtureBasicForm({ fixture }: { fixture: FixtureDetail }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();

  useEffect(() => {
    form.setFieldsValue({
      name: fixture.name,
      entity_type: fixture.entity_type,
      description: fixture.description ?? undefined,
      scope: fixture.scope,
      status: fixture.status,
      cache_enabled: fixture.cache_enabled,
      cleanup_policy: fixture.cleanup_policy,
    });
  }, [fixture, form]);

  const mutation = useMutation({
    mutationFn: (body: FixtureUpdate) => testDataApi.updateFixture(fixture.id, body),
    onSuccess: () => {
      message.success('已保存');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixture', fixture.id] });
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixtures'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  const handleSave = async () => {
    const values = await form.validateFields();
    const body: FixtureUpdate = {
      name: values.name,
      description: values.description || null,
      scope: values.scope as FixtureUpdate['scope'],
      status: values.status as FixtureUpdate['status'],
      cache_enabled: values.cache_enabled,
      cleanup_policy: values.cleanup_policy as FixtureUpdate['cleanup_policy'],
    };
    mutation.mutate(body);
  };

  return (
    <Form<FormValues> form={form} layout="vertical" style={{ maxWidth: 560 }}>
      <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
        <Input maxLength={200} />
      </Form.Item>
      <Form.Item name="entity_type" label="实体类型">
        <Input maxLength={100} disabled />
      </Form.Item>
      <Form.Item label="fixture_key">
        <Input value={fixture.fixture_key} disabled />
      </Form.Item>
      <Form.Item name="description" label="描述">
        <Input.TextArea rows={2} maxLength={500} />
      </Form.Item>
      <Form.Item name="scope" label="作用域">
        <Select options={FIXTURE_SCOPE_OPTIONS} />
      </Form.Item>
      <Form.Item name="status" label="状态">
        <Select options={FIXTURE_STATUS_OPTIONS} />
      </Form.Item>
      <Form.Item name="cache_enabled" label="启用缓存" valuePropName="checked">
        <Switch />
      </Form.Item>
      <Form.Item name="cleanup_policy" label="清理策略">
        <Select options={FIXTURE_CLEANUP_POLICY_OPTIONS} />
      </Form.Item>
      <Button type="primary" loading={mutation.isPending} onClick={handleSave}>
        保存
      </Button>
    </Form>
  );
}
