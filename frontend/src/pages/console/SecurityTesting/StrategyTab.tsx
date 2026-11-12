import { collectPages } from '@/shared/api/pagination';
// 安全测试 · 策略与规则 Tab。
//
// 系统模板（builtin=true）只读，不可改不可删；项目自定义策略可建/改/删。
// 预留攻击类（INJECTION 等）策略允许保存但强制 enabled=false，不能重新启用。
// 规则在策略下增删改；mutation_config 一律结构化（禁止脚本键，由后端拦）。
//
// 环境开关：项目级 allow_dev/test/staging/production；allow_production 在前端恒禁用，
// 仅展示「恒不生效」提示——生产环境永远拒绝安全变异请求，由后端 gate 强制。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Input,
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
import { useNavigate } from 'react-router-dom';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { StrategyModal, RuleModal } from './StrategyFormModals';
import { SettingModal } from './SecuritySettingModal';
import {
  expectationLabel,
  severityColor,
  severityLabel,
} from './constants';
import type { MutationRule, SecurityStrategy, SecurityStrategyCreate, SecurityStrategyUpdate } from '@/features/security-testing/contracts';


/** 策略与规则 Tab。projectId 由父页传入（已确保非空）。 */
export function StrategyTab({ projectId }: { projectId: number }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

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
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<number[]>([]);

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

  const batchDeleteStrategies = () => {
    if (!selectedStrategyIds.length) return;
    modal.confirm({
      title: `将 ${selectedStrategyIds.length} 条安全策略移入回收站？`,
      content: '批量选择仅包含没有规则的项目策略。含规则的策略请通过单条删除确认，系统会将策略和规则分别写入回收站。',
      okText: '移入回收站',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const receipt = await dataLifecycleApi.deleteMany('security_strategy', projectId, selectedStrategyIds);
          setSelectedStrategyIds([]);
          invalidate();
          queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
          if (receipt.failed) {
            modal.info({
              title: `已处理：成功 ${receipt.succeeded} 条，失败 ${receipt.failed} 条`,
              content: <Space direction="vertical" style={{ width: '100%' }}>{receipt.items.filter((item) => !item.succeeded).map((item) => <Alert key={item.id} type="error" showIcon message={`策略 #${item.id}`} description={item.error ?? '删除失败'} />)}</Space>,
            });
          } else {
            message.success(`已将 ${receipt.succeeded} 条策略移入回收站`);
          }
        } catch (error) {
          message.error(getErrorMessage(error, '批量删除失败'));
        }
      },
    });
  };

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
        <Space wrap className="ui-list-toolbar">
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
          <Button danger disabled={!selectedStrategyIds.length} onClick={batchDeleteStrategies}>
            批量删除（{selectedStrategyIds.length}）
          </Button>
          <Button onClick={() => navigate('/console/recycle-bin')}>回收站</Button>
        </Space>
      </Card>

      <Table<SecurityStrategy> scroll={{ x: 'max-content' }}
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        rowSelection={{
          selectedRowKeys: selectedStrategyIds,
          onChange: (keys) => setSelectedStrategyIds(keys.map(Number)),
          getCheckboxProps: (row) => ({ disabled: row.builtin || row.rules.length > 0 }),
        }}
        pagination={false}
        expandable={{
          expandedRowRender: (r) => (
            <RulesTable
              projectId={projectId}
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
  projectId,
  strategy,
  onEditRule,
}: {
  projectId: number;
  strategy: SecurityStrategy;
  onEditRule: (rule: MutationRule) => void;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [selectedRuleIds, setSelectedRuleIds] = useState<number[]>([]);

  const removeMutation = useMutation({
    mutationFn: (id: number) => securityApi.removeRule(id),
    onSuccess: () => {
      message.success('规则已删除');
      queryClient.invalidateQueries({ queryKey: ['security-strategies'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const batchDeleteRules = () => {
    if (!selectedRuleIds.length) return;
    modal.confirm({
      title: `将 ${selectedRuleIds.length} 条规则移入回收站？`,
      content: '安全用例和发现记录中的历史引用会保留。恢复规则前，所属策略必须先处于正常状态。',
      okText: '移入回收站',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const receipt = await dataLifecycleApi.deleteMany('security_rule', projectId, selectedRuleIds);
          setSelectedRuleIds([]);
          queryClient.invalidateQueries({ queryKey: ['security-strategies'] });
          queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
          if (receipt.failed) {
            modal.info({
              title: `已处理：成功 ${receipt.succeeded} 条，失败 ${receipt.failed} 条`,
              content: <Space direction="vertical" style={{ width: '100%' }}>{receipt.items.filter((item) => !item.succeeded).map((item) => <Alert key={item.id} type="error" showIcon message={`规则 #${item.id}`} description={item.error ?? '删除失败'} />)}</Space>,
            });
          } else {
            message.success(`已将 ${receipt.succeeded} 条规则移入回收站`);
          }
        } catch (error) {
          message.error(getErrorMessage(error, '批量删除失败'));
        }
      },
    });
  };

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
          {!strategy.builtin && <Button size="small" onClick={() => onEditRule(r)}>
            编辑
          </Button>}
          {!strategy.builtin && <Popconfirm title="确认将规则移入回收站？历史用例引用会保留。" onConfirm={() => removeMutation.mutate(r.id)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {!strategy.builtin && <Space>
        <Button danger disabled={!selectedRuleIds.length} onClick={batchDeleteRules}>批量删除规则（{selectedRuleIds.length}）</Button>
        <Button onClick={() => navigate('/console/recycle-bin')}>回收站</Button>
      </Space>}
      <Table<MutationRule> scroll={{ x: 'max-content' }}
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={strategy.rules}
        rowSelection={strategy.builtin ? undefined : {
          selectedRowKeys: selectedRuleIds,
          onChange: (keys) => setSelectedRuleIds(keys.map(Number)),
        }}
        pagination={false}
      />
    </Space>
  );
}
