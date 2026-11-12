import { App, Form, Input, InputNumber, Modal, Select, Space, Switch } from 'antd';
import { useMutation } from '@tanstack/react-query';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { getErrorMessage } from '@/shared/api/client';
import { EXPECTATION_OPTIONS, SEVERITY_OPTIONS } from './constants';
import { MUTATION_TYPES, TARGET_LOCATIONS, STRATEGY_CATEGORIES, RESERVED_CATEGORIES } from './strategyConstants';
import type { MutationRule, MutationRuleCreate, SecurityStrategy, SecurityStrategyCreate } from '@/features/security-testing/contracts';

/** 新建 / 编辑策略弹窗。 */
export function StrategyModal({
  mode,
  data,
  submitting,
  onCancel,
  onSubmit,
}: {
  mode: 'create' | 'edit';
  data?: SecurityStrategy;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (body: SecurityStrategyCreate) => void;
}) {
  const [form] = Form.useForm<SecurityStrategyCreate>();
  // mode/data 变化时重建表单初值。
  const formKey = `${mode}-${data?.id ?? 'new'}`;

  return (
    <Modal
      title={mode === 'create' ? '新建策略' : '编辑策略'}
      open
      onCancel={onCancel}
      confirmLoading={submitting}
      okText="保存"
      cancelText="取消"
      destroyOnClose
      onOk={() => form.validateFields().then((v) => onSubmit(v))}
    >
      <Form
        key={formKey}
        form={form}
        layout="vertical"
        initialValues={
          mode === 'edit' && data
            ? {
                name: data.name,
                description: data.description ?? undefined,
                risk_level: data.risk_level,
                enabled: data.enabled,
                revision: data.revision,
              }
            : {
                name: '',
                strategy_key: '',
                category: 'AUTHENTICATION',
                risk_level: 'MEDIUM',
                enabled: true,
              }
        }
      >
        <Form.Item name="name" label="策略名" rules={[{ required: true, message: '请输入策略名' }]}>
          <Input maxLength={200} disabled={mode === 'edit'} />
        </Form.Item>
        {mode === 'create' && (
          <>
            <Form.Item
              name="strategy_key"
              label="策略 Key"
              rules={[
                { required: true, message: '请输入策略 Key' },
                {
                  pattern: /^[A-Z][A-Z0-9_]{0,99}$/,
                  message: '大写字母开头，仅含大写字母/数字/下划线',
                },
              ]}
            >
              <Input maxLength={100} placeholder="如 MY_AUTH_CHECK" />
            </Form.Item>
            <Form.Item name="category" label="类别" rules={[{ required: true, message: '请选择类别' }]}>
              <Select
                options={STRATEGY_CATEGORIES.map((c) => ({
                  value: c,
                  label: RESERVED_CATEGORIES.has(c) ? `${c}（预留，强制停用）` : c,
                }))}
              />
            </Form.Item>
          </>
        )}
        <Form.Item name="description" label="描述">
          <Input.TextArea maxLength={1000} rows={2} />
        </Form.Item>
        <Form.Item name="risk_level" label="风险级别">
          <Select options={SEVERITY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
        {mode === 'edit' && (
          <Form.Item name="revision" hidden>
            <InputNumber />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

/** 新建 / 编辑规则弹窗。mutation_config 以 JSON 文本输入，提交前解析校验。 */
export function RuleModal({
  strategyId,
  data,
  onCancel,
  onDone,
}: {
  strategyId: number;
  data?: MutationRule;
  onCancel: () => void;
  onDone: () => void;
}) {
  const { message } = App.useApp();
  const formKey = `${data?.id ?? 'new'}-${strategyId}`;
  const [form] = Form.useForm<MutationRuleCreate & { config_text: string; codes_text: string }>();

  const createMutation = useMutation({
    mutationFn: (body: MutationRuleCreate) => securityApi.createRule(strategyId, body),
    onSuccess: () => {
      message.success('规则已创建');
      onDone();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
  const updateMutation = useMutation({
    mutationFn: (body: MutationRuleCreate) =>
      data ? securityApi.updateRule(data.id, body) : Promise.reject(),
    onSuccess: () => {
      message.success('规则已更新');
      onDone();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const handleOk = async () => {
    const v = await form.validateFields();
    let config: Record<string, unknown>;
    try {
      config = v.config_text ? (JSON.parse(v.config_text) as Record<string, unknown>) : {};
    } catch {
      message.error('mutation_config 不是合法 JSON');
      return;
    }
    // 期望状态码：逗号分隔文本 → number[]，越界留给后端拦（100-599）。
    const codes: number[] = (v.codes_text ?? '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => Number(s))
      .filter((n) => Number.isFinite(n));
    const body: MutationRuleCreate = {
      name: v.name,
      mutation_type: v.mutation_type,
      target_location: v.target_location,
      target_field: v.target_field || null,
      operator: v.operator || null,
      mutation_config: config,
      expected_security_behavior: v.expected_security_behavior || undefined,
      expected_status_codes: codes.length ? codes : null,
      severity: v.severity || undefined,
      enabled: v.enabled ?? true,
      confirmation_required: v.confirmation_required ?? false,
      sort: v.sort ?? 0,
    };
    if (data) updateMutation.mutate(body);
    else createMutation.mutate(body);
  };

  return (
    <Modal
      title={data ? '编辑规则' : '新增规则'}
      open
      onCancel={onCancel}
      confirmLoading={createMutation.isPending || updateMutation.isPending}
      okText="保存"
      cancelText="取消"
      destroyOnClose
      width={620}
      onOk={handleOk}
    >
      <Form
        key={formKey}
        form={form}
        layout="vertical"
        initialValues={
          data
            ? {
                name: data.name,
                mutation_type: data.mutation_type,
                target_location: data.target_location,
                target_field: data.target_field ?? '',
                operator: data.operator ?? '',
                expected_security_behavior: data.expected_security_behavior,
                severity: data.severity,
                enabled: data.enabled,
                confirmation_required: data.confirmation_required,
                sort: data.sort,
                config_text: JSON.stringify(data.mutation_config ?? {}, null, 2),
                codes_text: (data.expected_status_codes ?? []).join(','),
              }
            : {
                name: '',
                mutation_type: 'REMOVE_TOKEN',
                target_location: 'HEADER',
                target_field: '',
                operator: '',
                expected_security_behavior: 'EXPECTED_DENY',
                severity: 'MEDIUM',
                enabled: true,
                confirmation_required: false,
                sort: 0,
                config_text: '{}',
                codes_text: '',
              }
        }
      >
        <Form.Item name="name" label="规则名" rules={[{ required: true, message: '请输入规则名' }]}>
          <Input maxLength={200} />
        </Form.Item>
        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="mutation_type" label="变异类型" rules={[{ required: true }]} style={{ width: 220 }}>
            <Select options={MUTATION_TYPES.map((t) => ({ value: t, label: t }))} />
          </Form.Item>
          <Form.Item name="target_location" label="目标位置" rules={[{ required: true }]} style={{ width: 160 }}>
            <Select options={TARGET_LOCATIONS.map((t) => ({ value: t, label: t }))} />
          </Form.Item>
          <Form.Item name="target_field" label="目标字段" style={{ width: 180 }}>
            <Input maxLength={200} placeholder="如 Authorization" />
          </Form.Item>
        </Space>
        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="expected_security_behavior" label="期望" style={{ width: 200 }}>
            <Select options={EXPECTATION_OPTIONS} />
          </Form.Item>
          <Form.Item name="severity" label="严重级别" style={{ width: 140 }}>
            <Select options={SEVERITY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
          </Form.Item>
          <Form.Item name="sort" label="排序" style={{ width: 120 }}>
            <InputNumber min={0} max={10000} style={{ width: '100%' }} />
          </Form.Item>
        </Space>
        <Form.Item name="codes_text" label="期望状态码（逗号分隔，100-599）">
          <Input placeholder="如 401,403" />
        </Form.Item>
        <Form.Item
          name="config_text"
          label="mutation_config（结构化 JSON，禁止脚本键）"
          tooltip="安全变异必须是结构化配置；出现 script/python/sql/shell/payload_file/command 等键会被后端拒绝。"
        >
          <Input.TextArea
            rows={4}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
            placeholder='{"location":"HEADER","field":"Authorization"}'
          />
        </Form.Item>
        <Space>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="confirmation_required" label="高风险（需人工确认）" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}

