// 基本信息 Tab：展示接口基本信息 + 内联编辑（含移动模块）。
// 编辑走 Drawer + Form，提交 updateApi；保存后失效 ['api-catalog']（含详情、列表、模块树）。
import { useState } from 'react';
import { App, Button, Descriptions, Drawer, Form, Input, Select, Space, Tag, Typography } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { getErrorMessage } from '@/shared/api/client';
import { API_STATUS_COLOR, API_STATUS_OPTIONS, METHOD_COLOR, METHOD_OPTIONS } from '../constants';
import type { ApiInterfaceDetail, ApiInterfaceUpdate, ApiModule, ApiStatus } from '@/features/api-catalog/contracts';


interface FormValues {
  name: string;
  description?: string;
  method: string;
  path: string;
  auth_type?: string;
  content_type?: string;
  status?: ApiStatus;
  module_id?: number | null;
}

/**
 * 基本信息 Tab。
 *
 * 展示用 Descriptions；编辑打开 Drawer 表单（含模块下拉，模块选择即「移动接口」）。
 * modules 由父级传入（页面级模块树查询结果），含未分类默认模块。
 */
export function OverviewTab({
  api,
  modules,
}: {
  api: ApiInterfaceDetail;
  modules: ApiModule[];
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const updateMutation = useMutation({
    mutationFn: (body: ApiInterfaceUpdate) => apiCatalogApi.updateApi(api.id, body),
    onSuccess: () => {
      message.success('已保存');
      // 失效整棵 api-catalog 查询树：详情、列表、模块树、历史都会刷新。
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
      setOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  const openEdit = () => {
    form.setFieldsValue({
      name: api.name,
      description: api.description ?? undefined,
      method: api.method,
      path: api.path,
      auth_type: api.auth_type,
      content_type: api.content_type,
      status: api.status,
      module_id: api.module_id ?? undefined,
    });
    setOpen(true);
  };

  const moduleOptions = modules.map((m) => ({
    label: m.is_default ? `${m.name}（默认）` : m.name,
    value: m.id,
  }));

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={openEdit}>
          编辑
        </Button>
        <Typography.Text type="secondary">
          来源：{api.source_type} · 版本 v{api.version}
        </Typography.Text>
      </Space>

      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="接口名">{api.name}</Descriptions.Item>
        <Descriptions.Item label="方法">
          <Tag color={METHOD_COLOR[api.method] ?? 'default'}>{api.method}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="路径">
          <Typography.Text code copyable>
            {api.path}
          </Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="所属模块">{api.module_name ?? '未分类'}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={API_STATUS_COLOR[api.status]}>{api.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="鉴权类型">{api.auth_type}</Descriptions.Item>
        <Descriptions.Item label="Content-Type">{api.content_type}</Descriptions.Item>
        <Descriptions.Item label="描述">{api.description ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="参数 / 响应">
          {api.parameters.length} 个参数 · {api.responses.length} 个响应
        </Descriptions.Item>
        <Descriptions.Item label="创建 / 更新">
          {new Date(api.created_at).toLocaleString()} / {new Date(api.updated_at).toLocaleString()}
        </Descriptions.Item>
      </Descriptions>

      <Drawer
        title={`编辑接口 #${api.id}`}
        open={open}
        onClose={() => setOpen(false)}
        width={480}
        destroyOnClose
        extra={
          <Space>
            <Button onClick={() => setOpen(false)}>取消</Button>
            <Button
              type="primary"
              loading={updateMutation.isPending}
              onClick={async () => {
                const values = await form.validateFields();
                await updateMutation.mutateAsync({
                  ...values,
                  // 清空「所属模块」时 validateFields 返回 undefined，JSON 序列化会丢弃该键，
                  // 后端 exclude_unset 看不到字段就跳过 -> 接口永远回不了「未分类」。兜底成显式 null。
                  module_id: values.module_id ?? null,
                });
              }}
            >
              保存
            </Button>
          </Space>
        }
      >
        <Form<FormValues> form={form} layout="vertical">
          <Form.Item
            name="name"
            label="接口名"
            rules={[{ required: true, message: '请输入接口名' }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="module_id" label="所属模块" tooltip="选择即移动接口到该模块">
            <Select
              allowClear
              placeholder="未分类"
              options={moduleOptions}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <div className="form-field-row">
            <Form.Item
              name="method"
              label="方法"
              style={{ flex: 1, margin: 0 }}
              rules={[{ required: true, message: '请选择方法' }]}
            >
              <Select options={METHOD_OPTIONS} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="status"
              label="状态"
              style={{ flex: 1, margin: 0 }}
            >
              <Select options={API_STATUS_OPTIONS} style={{ width: '100%' }} />
            </Form.Item>
          </div>
          <Form.Item
            name="path"
            label="路径"
            rules={[{ required: true, message: '请输入路径' }]}
          >
            <Input maxLength={500} placeholder="/api/v1/tasks/{id}" />
          </Form.Item>
          <Form.Item name="auth_type" label="鉴权类型">
            <Input placeholder="none / bearer / api-key" maxLength={30} />
          </Form.Item>
          <Form.Item name="content_type" label="Content-Type">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Drawer>
    </>
  );
}
