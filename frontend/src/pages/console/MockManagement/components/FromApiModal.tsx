// 从 API Catalog 的结构化接口定义创建 Mock 服务。
import { collectPages } from '@/shared/api/pagination';
import { Alert, Form, Input, Modal, Select } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import type { ApiInterface } from '@/features/api-catalog/contracts';
import type { CreateMockFromApiRequest } from '@/features/mocking/contracts';
import { API_MOCK_TEMPLATES, MOCK_KEY_PATTERN } from "../constants";

export function FromApiModal({
  projectId,
  open,
  onClose,
  onSubmit,
  loading,
}: {
  projectId: number;
  open: boolean;
  onClose: () => void;
  onSubmit: (apiId: number, values: CreateMockFromApiRequest) => void;
  loading: boolean;
}) {
  const [form] = Form.useForm<{ api_id: number; service_key: string; service_name?: string; templates: string[] }>();
  const apisQuery = useQuery({
    queryKey: ['apis-for-mock', projectId],
    queryFn: () => collectPages((page) => apiCatalogApi.listApis(projectId, { page, page_size: 200 })),
    enabled: open,
  });
  const apis: ApiInterface[] = apisQuery.data?.items ?? [];

  return (
    <Modal
      title="从接口一键创建 Mock"
      open={open}
      onCancel={onClose}
      confirmLoading={loading}
      onOk={() => {
        form.validateFields().then((values) => {
          const { api_id, ...rest } = values;
          onSubmit(api_id, rest);
        }).catch(() => undefined);
      }}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ templates: ['NORMAL'] }}
        onValuesChange={(changed) => {
          // 选中接口后自动带出服务名，用户仍可改写。
          if ('api_id' in changed) {
            const picked = apis.find((a) => a.id === changed.api_id);
            if (picked) form.setFieldsValue({ service_name: picked.name });
          }
        }}
      >
        <Form.Item
          name="api_id"
          label="选择接口"
          rules={[{ required: true, message: '请选择一个已登记的接口' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={apisQuery.isLoading}
            options={apis.map((a) => ({
              value: a.id,
              label: `${a.method} ${a.path}（${a.name}）`,
            }))}
            placeholder="选择要 Mock 的接口"
          />
        </Form.Item>
        <Form.Item
          name="service_key"
          label="服务唯一键"
          rules={[
            { required: true, message: '请输入服务唯一键' },
            { pattern: MOCK_KEY_PATTERN, message: '首字母大写，仅允许字母 / 数字 / 下划线（≤100）' },
          ]}
        >
          <Input placeholder="如：MAP_SERVICE" maxLength={100} />
        </Form.Item>
        <Form.Item name="service_name" label="服务名称（可选）">
          <Input placeholder="默认取接口语义" maxLength={200} />
        </Form.Item>
        <Form.Item
          name="templates"
          label="推荐场景模板"
          tooltip="每个模板生成一个场景：正常 / 各类 HTTP 错误 / 空数据 / 延迟 / 超时"
          rules={[{ required: true, message: '至少选择一个模板' }]}
        >
          <Select mode="multiple" options={API_MOCK_TEMPLATES} placeholder="选择要生成的场景" />
        </Form.Item>
      </Form>
      <Alert
        type="info"
        showIcon
        message="生成内容"
        description="按接口的 method + path 建立 Mock 接口并关联 api_id，再按模板生成场景；每个场景的响应体基于接口已登记的响应结构初始化。"
      />
    </Modal>
  );
}

/** Mock 服务管理页。 */
