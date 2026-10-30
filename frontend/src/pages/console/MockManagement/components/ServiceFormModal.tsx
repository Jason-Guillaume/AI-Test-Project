// Mock 服务创建与编辑表单。
import { Alert, Form, Input, Modal, Space, Switch } from 'antd';
import type { MockService } from '@/features/mocking/contracts';
import { MOCK_KEY_PATTERN } from "../constants";

export interface ServiceFormValues {
  name: string;
  service_key: string;
  base_path?: string;
  description?: string;
  enabled: boolean;
  public_runtime: boolean;
  runtime_token?: string;
}

/** 一次性 token 弹窗：明文只在这里出现，关闭后无法再取回。 */
export function ServiceFormModal({
  open,
  editing,
  onClose,
  onSubmit,
  loading,
}: {
  open: boolean;
  editing: MockService | null;
  onClose: () => void;
  onSubmit: (values: ServiceFormValues) => void;
  loading: boolean;
}) {
  const [form] = Form.useForm<ServiceFormValues>();
  const initialValues: ServiceFormValues = editing
    ? {
        name: editing.name,
        service_key: editing.service_key,
        base_path: editing.base_path ?? '',
        description: editing.description ?? '',
        enabled: editing.enabled,
        public_runtime: editing.public_runtime,
        runtime_token: '',
      }
    : { name: '', service_key: '', base_path: '', description: '', enabled: true, public_runtime: false, runtime_token: '' };

  return (
    <Modal
      key={editing ? `edit-${editing.id}` : 'create'}
      title={editing ? `编辑 Mock 服务：${editing.name}` : '新建 Mock 依赖服务'}
      open={open}
      onCancel={onClose}
      confirmLoading={loading}
      onOk={() => {
        form.validateFields().then((values) => onSubmit(values)).catch(() => undefined);
      }}
    >
      <Form form={form} layout="vertical" initialValues={initialValues}>
        <Form.Item
          name="name"
          label="服务名称"
          rules={[{ required: true, message: '请输入服务名称' }, { max: 200 }]}
        >
          <Input placeholder="如：地图服务" maxLength={200} />
        </Form.Item>
        <Form.Item
          name="service_key"
          label="服务唯一键"
          tooltip="项目内唯一，被测系统调 Mock 地址时使用"
          rules={[
            { required: true, message: '请输入服务唯一键' },
            { pattern: MOCK_KEY_PATTERN, message: '首字母大写，仅允许字母 / 数字 / 下划线（≤100）' },
          ]}
        >
          <Input placeholder="如：MAP_SERVICE" maxLength={100} disabled={!!editing} />
        </Form.Item>
        <Form.Item name="base_path" label="基础路径（展示用）">
          <Input placeholder="/v1/maps" maxLength={500} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="该依赖服务在本项目中的用途" maxLength={1000} rows={2} />
        </Form.Item>
        <Space size="large" wrap>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item name="public_runtime" label="允许匿名调用执行面" valuePropName="checked">
            <Switch checkedChildren="允许" unCheckedChildren="需 Token" />
          </Form.Item>
        </Space>
        {!editing && (
          <Form.Item
            name="runtime_token"
            label="自定义 Runtime Token（可选）"
            rules={[{ min: 8, max: 200, message: '长度 8-200' }]}
          >
            <Input.Password placeholder="留空则自动生成" autoComplete="new-password" />
          </Form.Item>
        )}
      </Form>
      <Alert
        type="info"
        showIcon
        message="Token 与安全"
        description="平台只保存 Token 的哈希；明文仅在新建 / 重置后返回一次。默认必须携带 X-Mock-Token 才能调用执行面。"
      />
    </Modal>
  );
}

/** 从接口目录一键创建 Mock 弹窗（§二十 / §二十一 推荐场景模板）。 */
