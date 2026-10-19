// 场景编辑器：行为类型 / 状态码 / 延迟 / 响应头 / 响应体 / 响应模板 / 匹配规则 + 试跑。
//
// 安全约定：所有行为必须通过结构化 Schema 配置——表单里没有「表达式 / 脚本」输入框，
// 响应模板里的 ${request.*} / ${runtime.*} 只是白名单占位符，不是代码。
// 因此这里也不提供任意代码执行入口。
import { useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Divider,
  Drawer,
  Flex,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { getErrorMessage } from '@/api/client';
import { mockManagementApi } from '@/api/mockManagement';
import type {
  MockBehaviorType,
  MockMatcherCreate,
  MockMatcherOperator,
  MockMatcherSource,
  MockScenario,
  MockScenarioCreate,
  MockScenarioUpdate,
  ScenarioTestResponse,
} from '@/types';
import {
  BEHAVIOR_OPTIONS,
  MATCHER_OPERATOR_OPTIONS,
  MATCHER_SOURCE_OPTIONS,
  MOCK_KEY_PATTERN,
  fmtJson,
  operatorNeedValue,
  statusCodeColor,
} from './constants';

/** 匹配规则表单行：expected_value 以字符串承载，提交时才按 JSON 解析。 */
interface MatcherFormRow {
  source: MockMatcherSource;
  field: string;
  operator: MockMatcherOperator;
  expected_value?: string | null;
  priority?: number;
  enabled?: boolean;
}

interface ScenarioFormValues {
  name: string;
  scenario_key: string;
  description?: string;
  enabled: boolean;
  is_default: boolean;
  priority: number;
  behavior_type: MockBehaviorType;
  status_code: number;
  delay_ms?: number | null;
  response_headers_text?: string;
  response_body_text?: string;
  response_template_text?: string;
  matchers?: MatcherFormRow[];
}

const JSON_RULE = {
  validator: (_: unknown, value: string | undefined) => {
    if (!value || !value.trim()) return Promise.resolve();
    try {
      JSON.parse(value);
      return Promise.resolve();
    } catch {
      return Promise.reject(new Error('不是合法 JSON'));
    }
  },
};

const parseJson = (text: string | undefined, fallback: unknown) => {
  if (!text || !text.trim()) return fallback;
  return JSON.parse(text);
};

/** 场景编辑器抽屉。 */
export function ScenarioEditor({
  endpointId,
  open,
  editing,
  onClose,
  onSaved,
}: {
  endpointId: number;
  open: boolean;
  editing: MockScenario | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message: msg } = App.useApp();
  const [form] = Form.useForm<ScenarioFormValues>();
  // 最近一次保存成功的场景（含最新 revision）；新建后立即用它，编辑中重复保存也不会带过期 revision。
  const [saved, setSaved] = useState<MockScenario | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const current = saved ?? editing;

  const initialValues: ScenarioFormValues = editing
    ? {
        name: editing.name,
        scenario_key: editing.scenario_key,
        description: editing.description ?? '',
        enabled: editing.enabled,
        is_default: editing.is_default,
        priority: editing.priority,
        behavior_type: editing.behavior_type,
        status_code: editing.status_code,
        delay_ms: editing.delay_ms,
        response_headers_text: editing.response_headers ? JSON.stringify(editing.response_headers, null, 2) : '',
        response_body_text: editing.response_body != null ? JSON.stringify(editing.response_body, null, 2) : '',
        response_template_text: editing.response_template != null ? JSON.stringify(editing.response_template, null, 2) : '',
        matchers: editing.matchers.map((m) => ({
          source: m.source,
          field: m.field,
          operator: m.operator,
          expected_value: m.expected_value == null ? null : JSON.stringify(m.expected_value),
          priority: m.priority,
          enabled: m.enabled,
        })),
      }
    : {
        name: '',
        scenario_key: '',
        description: '',
        enabled: true,
        is_default: false,
        priority: 0,
        behavior_type: 'STATIC_RESPONSE',
        status_code: 200,
        delay_ms: null,
        response_headers_text: '',
        response_body_text: '',
        response_template_text: '',
        matchers: [],
      };

  // 打开时把初始值注入表单（key 变化会重挂载，这里额外同步一次保证稳妥）。
  useEffect(() => {
    if (open) {
      setSaved(null);
      form.setFieldsValue(initialValues);
    }
    setTestOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing?.id]);

  const saveMutation = useMutation({
    mutationFn: async (values: ScenarioFormValues) => {
      const matchers: MockMatcherCreate[] = (values.matchers ?? [])
        .filter((m): m is MatcherFormRow => !!m && !!m.field && !!m.operator)
        .map((m) => ({ ...m, expected_value: parseJson(String(m.expected_value ?? ''), null) }));
      if (current) {
        const updated = await mockManagementApi.updateScenario(current.id, {
          name: values.name,
          description: values.description || null,
          enabled: values.enabled,
          is_default: values.is_default,
          priority: values.priority,
          behavior_type: values.behavior_type,
          status_code: values.status_code,
          delay_ms: values.delay_ms ?? null,
          response_headers: parseJson(values.response_headers_text, null),
          response_body: parseJson(values.response_body_text, null),
          response_template: parseJson(values.response_template_text, null),
          revision: current.revision,
        } satisfies MockScenarioUpdate);
        // 匹配规则单独走整体替换：PUT /mock-scenarios/{id}/matchers；
        // 带上 revision 做乐观锁，否则两个会话同时保存会互相覆盖规则集。
        await mockManagementApi.replaceMatchers(updated.id, {
          matchers,
          revision: updated.revision,
        });
        return updated;
      }
      return mockManagementApi.createScenario(endpointId, {
        name: values.name,
        scenario_key: values.scenario_key,
        description: values.description || null,
        enabled: values.enabled,
        is_default: values.is_default,
        priority: values.priority,
        behavior_type: values.behavior_type,
        status_code: values.status_code,
        delay_ms: values.delay_ms ?? null,
        response_headers: parseJson(values.response_headers_text, null),
        response_body: parseJson(values.response_body_text, null),
        response_template: parseJson(values.response_template_text, null),
        matchers,
      } satisfies MockScenarioCreate);
    },
    onSuccess: (created) => {
      // 留在抽屉里：保存后即可用最新 id 直接试跑；重复保存用新 revision。
      setSaved(created);
      onSaved();
      msg.success('场景已保存');
    },
    onError: (e) => msg.error(getErrorMessage(e, '保存场景失败')),
  });

  return (
    <Drawer
      title={current ? `编辑场景：${current.name}` : '新建场景'}
      open={open}
      onClose={onClose}
      width={720}
      extra={
        <Space>
          <Button
            icon={<ThunderboltOutlined />}
            disabled={current == null}
            onClick={() => setTestOpen(true)}
          >
            试跑
          </Button>
          <Button
            type="primary"
            loading={saveMutation.isPending}
            onClick={() => {
              form
                .validateFields()
                .then((values) => saveMutation.mutate(values))
                .catch(() => undefined);
            }}
          >
            保存
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="结构化配置"
        description="行为类型、状态码、延迟与匹配规则全部是结构化字段，不接受任意代码、脚本或动态表达式；响应模板仅支持 ${request.*} / ${runtime.*} 白名单占位符。"
      />

      <Form form={form} layout="vertical" initialValues={initialValues}>
        <Flex gap="small">
          <Form.Item
            name="name"
            label="场景名称"
            style={{ flex: 1 }}
            rules={[{ required: true, message: '请输入场景名称' }, { max: 200 }]}
          >
            <Input placeholder="如：库存不足" maxLength={200} />
          </Form.Item>
          <Form.Item
            name="scenario_key"
            label="场景唯一键"
            tooltip="同一接口内唯一"
            style={{ flex: 1 }}
            rules={[
              { required: true, message: '请输入场景唯一键' },
              { pattern: MOCK_KEY_PATTERN, message: '首字母大写，仅允许字母 / 数字 / 下划线（≤100）' },
            ]}
          >
            <Input placeholder="如：STOCK_EMPTY" maxLength={100} disabled={!!current} />
          </Form.Item>
        </Flex>

        <Form.Item name="description" label="描述">
          <Input.TextArea maxLength={1000} rows={2} placeholder="该场景模拟的依赖表现" />
        </Form.Item>

        <Divider style={{ margin: '8px 0 16px' }} plain>行为配置</Divider>

        <Flex gap="small" wrap="wrap">
          <Form.Item name="behavior_type" label="行为类型" style={{ minWidth: 200 }}>
            <Select options={BEHAVIOR_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
          </Form.Item>
          <Form.Item
            name="status_code"
            label="响应状态码"
            tooltip="TIMEOUT 固定返回 504"
            rules={[{ required: true }]}
          >
            <InputNumber min={100} max={599} style={{ width: 130 }} />
          </Form.Item>
          <Form.Item
            name="delay_ms"
            label="延迟（毫秒）"
            tooltip="DELAY_RESPONSE / TIMEOUT 使用，最大 60000"
          >
            <InputNumber min={0} max={60000} step={100} style={{ width: 150 }} placeholder="0" />
          </Form.Item>
        </Flex>

        <Space size="large" wrap style={{ marginBottom: 16 }}>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item
            name="is_default"
            label="默认场景"
            tooltip="未匹配任何规则时兜底；同一接口只能有一个"
            valuePropName="checked"
          >
            <Switch checkedChildren="默认" unCheckedChildren="非默认" />
          </Form.Item>
          <Form.Item name="priority" label="优先级" tooltip="数值越高越先匹配">
            <InputNumber min={0} style={{ width: 110 }} />
          </Form.Item>
        </Space>

        <Divider style={{ margin: '8px 0 16px' }} plain>响应内容</Divider>

        <Form.Item name="response_headers_text" label="响应头（JSON）" rules={[JSON_RULE]}>
          <Input.TextArea rows={2} placeholder='{"X-Env": "mock"}' />
        </Form.Item>
        <Form.Item
          name="response_body_text"
          label="响应体（JSON，EMPTY_RESPONSE 留空）"
          tooltip="EMPTY_RESPONSE 固定返回空体；TIMEOUT 固定返回 504 空体"
          rules={[JSON_RULE]}
        >
          <Input.TextArea rows={5} placeholder='{"code": 0, "data": {"id": 1}}' />
        </Form.Item>
        <Form.Item
          name="response_template_text"
          label="响应模板（JSON，可选）"
          tooltip="支持 ${request.path.id} / ${request.query.x} / ${request.headers.x} / ${request.body.x} / ${runtime.request_id}"
          rules={[JSON_RULE]}
        >
          <Input.TextArea rows={4} placeholder='{"id": "${request.path.id}", "trace": "${runtime.request_id}"}' />
        </Form.Item>

        <Divider style={{ margin: '8px 0 16px' }} plain>匹配规则（AND 语义，全部通过才命中）</Divider>

        <Form.List name="matchers">
          {(fields, { add, remove }) => (
            <>
              {fields.map((field) => (
                <Flex key={field.key} gap="small" align="flex-start" style={{ marginBottom: 8 }}>
                  <Form.Item
                    name={[field.name, 'source']}
                    rules={[{ required: true, message: '选择来源' }]}
                    style={{ marginBottom: 0, width: 130 }}
                  >
                    <Select options={MATCHER_SOURCE_OPTIONS} placeholder="来源" />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, 'field']}
                    rules={[{ required: true, message: '字段' }]}
                    style={{ marginBottom: 0, flex: 1 }}
                  >
                    <Input placeholder="字段名或 JSONPath（$.amount）" />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, 'operator']}
                    rules={[{ required: true, message: '操作符' }]}
                    style={{ marginBottom: 0, width: 160 }}
                  >
                    <Select options={MATCHER_OPERATOR_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
                  </Form.Item>
                  <Form.Item
                    noStyle
                    shouldUpdate={(prev, cur) =>
                      prev.matchers?.[field.name]?.operator !== cur.matchers?.[field.name]?.operator
                    }
                  >
                    {({ getFieldValue }) => {
                      const op = getFieldValue(['matchers', field.name, 'operator']) as string | undefined;
                      return operatorNeedValue(op ?? '') ? (
                        <Form.Item
                          name={[field.name, 'expected_value']}
                          style={{ marginBottom: 0, width: 180 }}
                          rules={[JSON_RULE]}
                        >
                          <Input.TextArea rows={1} placeholder="期望值（JSON）" />
                        </Form.Item>
                      ) : (
                        <Input.TextArea rows={1} disabled placeholder="无期望值" />
                      );
                    }}
                  </Form.Item>
                  <Button
                    type="text"
                    danger
                    onClick={() => remove(field.name)}
                    style={{ marginTop: 4 }}
                  >
                    删除
                  </Button>
                </Flex>
              ))}
              <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add()}>
                新增匹配规则
              </Button>
              {fields.length === 0 && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  没有规则的场景总是命中；若它是默认场景，请给其它场景配更高优先级，避免默认场景遮蔽一切。
                </Typography.Text>
              )}
            </>
          )}
        </Form.List>
      </Form>

      <ScenarioTestDrawer
        open={testOpen}
        scenarioId={current?.id ?? null}
        onClose={() => setTestOpen(false)}
      />
    </Drawer>
  );
}

/** 场景试跑：模拟一个请求验证 Matcher + 响应构建，不真实调用被测系统。 */
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
