import { useState } from 'react';
import { Alert, App, Button, Drawer, Flex, Form, Input, Select, Space, Tag, Typography } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { getErrorMessage } from '@/shared/api/client';
import { mockManagementApi } from '@/features/mocking/api/mockManagement';
import type { ScenarioTestResponse } from '@/features/mocking/contracts';
import { JSON_RULE, parseJson } from './scenarioFormUtils';
import { fmtJson, statusCodeColor } from './constants';

export /** 场景试跑：模拟一个请求验证 Matcher + 响应构建，不真实调用被测系统。 */
function ScenarioTestDrawer({
  open,
  scenarioId,
  onClose,
}: {
  open: boolean;
  scenarioId: number | null;
  onClose: () => void;
}) {
  const { message: msg } = App.useApp();
  const [form] = Form.useForm<{ method: string; path: string; query_text?: string; headers_text?: string; body_text?: string }>();
  const [result, setResult] = useState<ScenarioTestResponse | null>(null);

  const testMutation = useMutation({
    mutationFn: (values: {
      method: string;
      path: string;
      query_text?: string;
      headers_text?: string;
      body_text?: string;
    }) =>
      mockManagementApi.testScenario(scenarioId!, {
        method: values.method,
        path: values.path,
        query: parseJson(values.query_text, {}),
        headers: parseJson(values.headers_text, {}),
        body: parseJson(values.body_text, null),
      }),
    onSuccess: (data) => {
      setResult(data);
      if (data.matched) msg.success(`命中场景 ${data.scenario_key}，返回 ${data.status_code}`);
      else msg.warning('未命中任何场景');
    },
    onError: (e) => msg.error(getErrorMessage(e, '试跑失败')),
  });

  return (
    <Drawer title="场景试跑（不真实调用被测系统）" open={open} onClose={onClose} width={640}>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ method: 'GET', path: '/', query_text: '', headers_text: '', body_text: '' }}
      >
        <Flex gap="small">
          <Form.Item name="method" label="方法" style={{ width: 120 }}>
            <Select options={['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => ({ value: m, label: m }))} />
          </Form.Item>
          <Form.Item name="path" label="路径" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Input placeholder="/items/42" />
          </Form.Item>
        </Flex>
        <Form.Item name="query_text" label="查询参数（JSON）" rules={[JSON_RULE]}>
          <Input.TextArea rows={2} placeholder='{"env": "B"}' />
        </Form.Item>
        <Form.Item name="headers_text" label="请求头（JSON）" rules={[JSON_RULE]}>
          <Input.TextArea rows={2} placeholder='{"X-Trace": "t-1"}' />
        </Form.Item>
        <Form.Item name="body_text" label="请求体（JSON）" rules={[JSON_RULE]}>
          <Input.TextArea rows={3} placeholder='{"amount": 100}' />
        </Form.Item>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={testMutation.isPending}
          disabled={scenarioId == null}
          onClick={() => {
            form.validateFields().then((values) => testMutation.mutate(values)).catch(() => undefined);
          }}
        >
          执行试跑
        </Button>
      </Form>

      {result && (
        <Alert
          style={{ marginTop: 16 }}
          type={result.matched ? 'success' : 'warning'}
          showIcon
          message={
            <Space wrap>
              <span>{result.matched ? `命中：${result.scenario_key ?? ''}` : '未命中'}</span>
              <Tag color={statusCodeColor(result.status_code)}>{result.status_code ?? '-'}</Tag>
              <Tag>耗时 {result.duration_ms}ms</Tag>
              {result.delay_ms > 0 ? <Tag color="gold">延迟 {result.delay_ms}ms</Tag> : null}
            </Space>
          }
          description={(
            <div>
              <Typography.Text strong>响应头</Typography.Text>
              <pre style={{ margin: '4px 0 8px', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {fmtJson(result.headers)}
              </pre>
              <Typography.Text strong>响应体</Typography.Text>
              <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {fmtJson(result.body)}
              </pre>
            </div>
          )}
        />
      )}
    </Drawer>
  );
}
