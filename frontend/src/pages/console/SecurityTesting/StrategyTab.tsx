import { collectPages } from '@/api/pagination';
// 安全测试 · 策略与规则 Tab。
//
// 系统模板（builtin=true）只读，不可改不可删；项目自定义策略可建/改/删。
// 预留攻击类（INJECTION 等）策略允许保存但强制 enabled=false，不能重新启用。
// 规则在策略下增删改；mutation_config 一律结构化（禁止脚本键，由后端拦）。
//
// 环境开关：项目级 allow_dev/test/staging/production；allow_production 在前端恒禁用，
// 仅展示「恒不生效」提示——生产环境永远拒绝安全变异请求，由后端 gate 强制。
import { useEffect, useState } from 'react';
import {
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import {
  EXPECTATION_OPTIONS,
  SEVERITY_OPTIONS,
  expectationLabel,
  severityColor,
  severityLabel,
} from './constants';
import type {
  MutationRule,
  MutationRuleCreate,
  SecurityStrategy,
  SecurityStrategyCreate,
  SecurityStrategyUpdate,
} from '@/types';

const MUTATION_TYPES = [
  'REMOVE_TOKEN', 'EMPTY_TOKEN', 'INVALID_TOKEN', 'MALFORMED_TOKEN', 'WRONG_AUTH_SCHEME', 'EXPIRED_TOKEN',
  'CROSS_USER', 'CROSS_PROJECT', 'ROLE_DOWNGRADE', 'RESOURCE_OWNER_CHANGE', 'IDOR',
  'REMOVE_FIELD', 'NULL_VALUE', 'EMPTY_STRING', 'TYPE_MUTATION', 'ZERO', 'NEGATIVE', 'OVER_MAX', 'UNDER_MIN', 'INVALID_ENUM', 'INVALID_FORMAT',
  'REMOVE_HEADER', 'EMPTY_HEADER', 'INVALID_HEADER_VALUE', 'CONTENT_TYPE_MUTATION', 'AUTHORIZATION_MUTATION',
  'METHOD_MUTATION', 'REPLAY_SAME_REQUEST', 'BUSINESS_STATE', 'SEQUENCE_BYPASS', 'DUPLICATE_SUBMIT',
] as const;

const TARGET_LOCATIONS = ['HEADER', 'QUERY', 'PATH', 'BODY', 'METHOD', 'REQUEST'] as const;

const STRATEGY_CATEGORIES = [
  'AUTHENTICATION', 'AUTHORIZATION', 'IDOR', 'PARAMETER', 'HEADER', 'METHOD',
  'REPLAY', 'DUPLICATE_SUBMIT', 'BUSINESS_STATE', 'SEQUENCE_BYPASS',
  'INJECTION', 'RATE_LIMIT', 'UPLOAD', 'SSRF',
] as const;
const RESERVED_CATEGORIES = new Set(['INJECTION', 'RATE_LIMIT', 'UPLOAD', 'SSRF']);

/** 策略与规则 Tab。projectId 由父页传入（已确保非空）。 */
export function StrategyTab({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [keyword, setKeyword] = useState('');
  const [enabledFilter, setEnabledFilter] = useState<boolean | undefined>(undefined);
  const [strategyModal, setStrategyModal] = useState<{
    mode: 'create' | 'edit';
    data?: SecurityStrategy;
  } | null>(null);
  const [ruleModal, setRuleModal] = useState<{
    strategyId: number;
    data?: MutationRule;
  } | null>(null);
  const [settingOpen, setSettingOpen] = useState(false);

  const listQuery = useQuery({
    queryKey: ['security-strategies', projectId, { keyword, enabled: enabledFilter }],
    queryFn: () =>
      collectPages((page) => securityApi.listStrategies(projectId, { page, page_size: 100, enabled: enabledFilter })),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['security-strategies'] });
    queryClient.invalidateQueries({ queryKey: ['security-overview', projectId] });
  };

  const createStrategyMutation = useMutation({
    mutationFn: (body: SecurityStrategyCreate) => securityApi.createStrategy(projectId, body),
    onSuccess: () => {
      message.success('策略已创建');
      setStrategyModal(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateStrategyMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: SecurityStrategyUpdate }) =>
      securityApi.updateStrategy(id, body),
    onSuccess: () => {
      message.success('策略已更新');
      setStrategyModal(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const removeStrategyMutation = useMutation({
    mutationFn: (id: number) => securityApi.removeStrategy(id),
    onSuccess: () => {
      message.success('策略已删除');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const toggleEnabledMutation = useMutation({
    mutationFn: ({ s, next }: { s: SecurityStrategy; next: boolean }) =>
      securityApi.updateStrategy(s.id, { enabled: next, revision: s.revision }),
    onSuccess: () => {
      message.success('已切换启用状态');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '切换失败')),
  });

  const columns: TableColumnsType<SecurityStrategy> = [
    {
      title: '策略',
      dataIndex: 'name',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{r.name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.strategy_key}
          </Typography.Text>
        </Space>
      ),
    },
    { title: '类别', dataIndex: 'category', width: 150 },
    {
      title: '风险级别',
      dataIndex: 'risk_level',
      width: 100,
      render: (v: string) => <Tag color={severityColor(v)}>{severityLabel(v)}</Tag>,
    },
    { title: '规则数', dataIndex: 'rules', width: 80, render: (v: MutationRule[]) => v.length },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 90,
      render: (v: boolean, r) =>
        r.builtin ? (
          <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
        ) : (
          <Switch
            checked={v}
            size="small"
            onChange={(next) => toggleEnabledMutation.mutate({ s: r, next })}
          />
        ),
    },
    {
      title: '来源',
      dataIndex: 'builtin',
      width: 90,
      render: (v: boolean) => (v ? <Tag>系统模板</Tag> : <Tag color="blue">项目</Tag>),
    },
    {
      title: '操作',
      width: 220,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => setRuleModal({ strategyId: r.id })}>
            新增规则
          </Button>
          {!r.builtin && (
            <>
              <Button size="small" onClick={() => setStrategyModal({ mode: 'edit', data: r })}>
                编辑
              </Button>
              <Popconfirm
                title="确认删除该策略？"
                description="连带删除其下所有规则。"
                onConfirm={() => removeStrategyMutation.mutate(r.id)}
              >
                <Button size="small" danger>
                  删除
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const items = (listQuery.data?.items ?? []).filter((s) =>
    keyword ? s.name.includes(keyword) || s.strategy_key.includes(keyword.toUpperCase()) : true,
  );

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Input.Search
            placeholder="策略名 / key"
            allowClear
            style={{ width: 220 }}
            onSearch={setKeyword}
          />
          <Select
            allowClear
            placeholder="启用状态"
            style={{ width: 140 }}
            value={enabledFilter}
            onChange={setEnabledFilter}
            options={[
              { value: true, label: '已启用' },
              { value: false, label: '已停用' },
            ]}
          />
          <Button onClick={() => setSettingOpen(true)}>环境开关</Button>
          <Button type="primary" onClick={() => setStrategyModal({ mode: 'create' })}>
            新建策略
          </Button>
        </Space>
      </Card>

      <Table<SecurityStrategy>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
        expandable={{
          expandedRowRender: (r) => (
            <RulesTable
              strategy={r}
              onEditRule={(rule) => setRuleModal({ strategyId: r.id, data: rule })}
            />
          ),
          rowExpandable: (r) => r.rules.length > 0,
        }}
      />

      {strategyModal && (
        <StrategyModal
          mode={strategyModal.mode}
          data={strategyModal.data}
          submitting={
            strategyModal.mode === 'create'
              ? createStrategyMutation.isPending
              : updateStrategyMutation.isPending
          }
          onCancel={() => setStrategyModal(null)}
          onSubmit={(body) => {
            if (strategyModal.mode === 'create') {
              createStrategyMutation.mutate(body);
            } else if (strategyModal.data) {
              updateStrategyMutation.mutate({ id: strategyModal.data.id, body });
            }
          }}
        />
      )}

      {ruleModal && (
        <RuleModal
          strategyId={ruleModal.strategyId}
          data={ruleModal.data}
          onCancel={() => setRuleModal(null)}
          onDone={() => {
            setRuleModal(null);
            invalidate();
          }}
        />
      )}

      {settingOpen && <SettingModal projectId={projectId} onCancel={() => setSettingOpen(false)} />}
    </div>
  );
}

/** 策略下的规则列表（展开行）。 */
function RulesTable({
  strategy,
  onEditRule,
}: {
  strategy: SecurityStrategy;
  onEditRule: (rule: MutationRule) => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const removeMutation = useMutation({
    mutationFn: (id: number) => securityApi.removeRule(id),
    onSuccess: () => {
      message.success('规则已删除');
      queryClient.invalidateQueries({ queryKey: ['security-strategies'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const columns: TableColumnsType<MutationRule> = [
    { title: '规则名', dataIndex: 'name' },
    { title: '变异类型', dataIndex: 'mutation_type', width: 160 },
    {
      title: '位置',
      width: 160,
      render: (_, r) => `${r.target_location}${r.target_field ? ` · ${r.target_field}` : ''}`,
    },
    {
      title: '期望',
      dataIndex: 'expected_security_behavior',
      width: 120,
      render: (v: string) => expectationLabel(v),
    },
    {
      title: '严重级别',
      dataIndex: 'severity',
      width: 90,
      render: (v: string) => <Tag color={severityColor(v)}>{severityLabel(v)}</Tag>,
    },
    {
      title: '高风险',
      dataIndex: 'confirmation_required',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="orange">需确认</Tag> : '-'),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 70,
      render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '操作',
      width: 120,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => onEditRule(r)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该规则？" onConfirm={() => removeMutation.mutate(r.id)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Table<MutationRule>
      rowKey="id"
      size="small"
      columns={columns}
      dataSource={strategy.rules}
      pagination={false}
    />
  );
}

/** 新建 / 编辑策略弹窗。 */
function StrategyModal({
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
function RuleModal({
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

/** 环境开关弹窗：allow_production 恒禁用。用本地 state 承载开关，不污染缓存对象。 */
function SettingModal({ projectId, onCancel }: { projectId: number; onCancel: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settingQuery = useQuery({
    queryKey: ['security-setting', projectId],
    queryFn: () => securityApi.getSetting(projectId),
  });
  const [dev, setDev] = useState(false);
  const [test, setTest] = useState(false);
  const [staging, setStaging] = useState(false);
  const [revision, setRevision] = useState<number>(1);

  // 拿到后端初值后写一次本地 state（避免直接 mutate 缓存对象）。
  useEffect(() => {
    const s = settingQuery.data;
    if (!s) return;
    setDev(s.allow_dev);
    setTest(s.allow_test);
    setStaging(s.allow_staging);
    setRevision(s.revision);
  }, [settingQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (body: Parameters<typeof securityApi.updateSetting>[1]) =>
      securityApi.updateSetting(projectId, body),
    onSuccess: () => {
      message.success('环境开关已更新');
      queryClient.invalidateQueries({ queryKey: ['security-setting', projectId] });
      onCancel();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  return (
    <Modal
      title="安全测试环境开关"
      open
      onCancel={onCancel}
      confirmLoading={updateMutation.isPending}
      okText="保存"
      cancelText="取消"
      onOk={() =>
        updateMutation.mutate({
          allow_dev: dev,
          allow_test: test,
          allow_staging: staging,
          // allow_production 故意不提交：前端恒禁用，生产永远拒绝（后端 gate 强制）。
          revision,
        })
      }
    >
      {settingQuery.isLoading ? (
        <LoadingState />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text>
            仅勾选的环境允许发起安全变异请求。生产环境恒为关闭，不可开启。
          </Typography.Text>
          <Form layout="vertical">
            <Form.Item label="开发环境（DEV）">
              <Switch checked={dev} onChange={setDev} />
            </Form.Item>
            <Form.Item label="测试环境（TEST）">
              <Switch checked={test} onChange={setTest} />
            </Form.Item>
            <Form.Item label="预发环境（STAGING）">
              <Switch checked={staging} onChange={setStaging} />
            </Form.Item>
            <Form.Item label="生产环境（PRODUCTION）">
              <Switch checked={false} disabled />
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                恒不生效（安全红线）
              </Typography.Text>
            </Form.Item>
          </Form>
        </Space>
      )}
    </Modal>
  );
}
