// 执行记录详情抽屉（Phase B）。
//
// §7.5：试跑后打开详情看到每步 input / output / error。
// 结构自上而下：总记录（状态 / 错误 / 清理 / 耗时）→ 每个 Fixture 执行（含契约输出）
// → 该 Fixture 下的 Provider 步骤；单 Provider 试跑没有 Fixture 归属，
// 步骤直接列在「无归属步骤」区块。
//
// 快照全部来自后端已脱敏 JSON，前端只原样展示，不做还原。
import { Alert, Collapse, Descriptions, Divider, Drawer, Empty, Space, Spin, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { testDataApi } from '@/features/test-data/api/testData';
import { getErrorMessage } from '@/shared/api/client';
import {
  CLEANUP_STATUS_COLOR,
  DATA_EXECUTION_STATUS_COLOR,
  PROVIDER_EXECUTION_STATUS_COLOR,
  labelOf,
  DATA_EXECUTION_STATUS_OPTIONS,
} from './constants';
import type { DataExecutionDetail, FixtureExecution, ProviderExecution } from '@/features/test-data/executionContracts';


/** JSON 快照只读视图：与执行历史页同一套样式。 */
function JsonView({ value }: { value: unknown }) {
  if (value == null) return <Typography.Text type="secondary">无数据</Typography.Text>;
  return (
    <pre
      style={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        maxHeight: 320,
        overflow: 'auto',
        background: '#fafafa',
        padding: 8,
        borderRadius: 6,
        fontSize: 12,
        margin: 0,
      }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** 状态标签：值为空时返回 '-'，避免渲染空 Tag。 */
function StatusTag({ color, value }: { color: string; value: string | null | undefined }) {
  if (!value) return <span>-</span>;
  return <Tag color={color}>{value}</Tag>;
}

function cleanupTag(value: string | null) {
  if (!value) return <span>-</span>;
  return <Tag color={CLEANUP_STATUS_COLOR[value as keyof typeof CLEANUP_STATUS_COLOR] ?? 'default'}>{value}</Tag>;
}

/** 一个 Provider 步骤：input / output / error 三段，出错时高亮。 */
function StepCard({ step }: { step: ProviderExecution }) {
  const failed = step.status === 'FAILED';
  return (
    <Collapse
      size="small"
      items={[
        {
          key: String(step.id),
          label: (
            <Space size="small" wrap>
              <StatusTag color={PROVIDER_EXECUTION_STATUS_COLOR[step.status]} value={step.status} />
              <Tag>{step.provider_type}</Tag>
              <span>{step.provider_id != null ? `Provider #${step.provider_id}` : '步骤内联配置'}</span>
              <Typography.Text type="secondary">
                {step.duration_ms != null ? `${step.duration_ms}ms` : '—'}
              </Typography.Text>
              {step.error_code ? <Tag color="red">{step.error_code}</Tag> : null}
            </Space>
          ),
          children: (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <div style={{ marginBottom: 4 }}>
                  <Typography.Text strong>input 快照</Typography.Text>
                </div>
                <JsonView value={step.input_snapshot} />
              </div>
              <div>
                <div style={{ marginBottom: 4 }}>
                  <Typography.Text strong>output 快照</Typography.Text>
                </div>
                <JsonView value={step.output_snapshot} />
              </div>
              {step.error_message ? (
                <Alert
                  type="error"
                  showIcon
                  message={step.error_code ?? '执行失败'}
                  description={step.error_message}
                />
              ) : null}
            </div>
          ),
          style: failed ? { borderColor: '#ff4d4f' } : undefined,
        },
      ]}
    />
  );
}

/** 一个 Fixture 执行：契约输出 + 该 Fixture 的步骤列表。 */
function FixtureBlock({ fx }: { fx: FixtureExecution }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ marginBottom: 8 }}>
        <Space size="small" wrap>
          <Typography.Text strong>{fx.fixture_key}</Typography.Text>
          <StatusTag color={DATA_EXECUTION_STATUS_COLOR[fx.status]} value={fx.status} />
          <span>作用域 {fx.scope || '-'}</span>
          <span>缓存命中 {fx.cache_hit ? '是' : '否'}</span>
          <span>{fx.duration_ms != null ? `${fx.duration_ms}ms` : '—'}</span>
          <span>清理 {cleanupTag(fx.cleanup_status)}</span>
        </Space>
      </div>
      {fx.output_snapshot ? (
        <div style={{ marginBottom: 8 }}>
          <Typography.Text type="secondary">契约输出（已脱敏）</Typography.Text>
          <div style={{ marginTop: 4 }}>
            <JsonView value={fx.output_snapshot} />
          </div>
        </div>
      ) : null}
      {fx.error_message ? (
        <Alert type="error" showIcon message={fx.error_code ?? '生成失败'} description={fx.error_message} />
      ) : null}
      {fx.provider_executions.length > 0 ? (
        <>
          <Divider style={{ margin: '8px 0' }} />
          {fx.provider_executions.map((step) => (
            <div key={step.id} style={{ marginBottom: 4 }}>
              <StepCard step={step} />
            </div>
          ))}
        </>
      ) : (
        <Typography.Text type="secondary">无 Provider 步骤记录</Typography.Text>
      )}
    </div>
  );
}

/**
 * 执行记录详情抽屉。
 *
 * `seed` 用于「刚跑完试跑」的场景：直接把返回体渲出来，省一次请求。
 * 只有 `seed.id === executionId` 时才采用，避免残留上一次的结果。
 */
export function ExecutionDetailDrawer({
  open,
  executionId,
  seed,
  onClose,
}: {
  open: boolean;
  executionId: number | null;
  seed: DataExecutionDetail | null;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ['test-data', 'execution', executionId],
    queryFn: () => testDataApi.getExecution(executionId!),
    enabled: open && executionId != null && seed?.id !== executionId,
  });

  const detail = seed?.id === executionId ? seed : query.data;

  return (
    <Drawer
      title={`执行记录 #${executionId ?? '-'}`}
      open={open}
      onClose={onClose}
      width="72%"
      destroyOnClose
    >
      {!open ? null : (
        <Spin spinning={query.isFetching && !detail}>
          {query.isError ? (
            <Alert type="error" showIcon message={getErrorMessage(query.error, '加载执行记录失败')} />
          ) : !detail ? null : (
            <div>
              <Descriptions
                size="small"
                column={3}
                bordered
                style={{ marginBottom: 16 }}
                items={[
                  {
                    key: 'status',
                    label: '状态',
                    children: (
                      <StatusTag
                        color={DATA_EXECUTION_STATUS_COLOR[detail.status]}
                        value={labelOf(DATA_EXECUTION_STATUS_OPTIONS, detail.status)}
                      />
                    ),
                  },
                  { key: 'scope', label: '作用域', children: detail.scope ?? '-' },
                  { key: 'env', label: '环境 ID', children: detail.environment_id ?? '-' },
                  { key: 'fixture', label: 'Fixture 数', children: detail.fixture_key_count },
                  { key: 'steps', label: 'Provider 步骤数', children: detail.provider_step_count },
                  {
                    key: 'duration',
                    label: '耗时(ms)',
                    children: detail.duration_ms ?? '-',
                  },
                  {
                    key: 'cleanup',
                    label: '清理',
                    children: cleanupTag(detail.cleanup_status),
                  },
                  { key: 'test_run', label: 'TestRun', children: detail.test_run_id ? `#${detail.test_run_id}` : '-' },
                  {
                    key: 'case_exec',
                    label: '用例执行',
                    children: detail.case_execution_id ? `#${detail.case_execution_id}` : '-',
                  },
                ]}
              />

              {detail.error_message ? (
                <Alert
                  type="error"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={detail.error_code ?? '生成失败'}
                  description={detail.error_message}
                />
              ) : null}
              {detail.cleanup_error_message ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`清理失败（${detail.cleanup_error_code ?? 'CLEANUP_FAILED'}）`}
                  description={detail.cleanup_error_message}
                />
              ) : null}

              {detail.fixture_executions.length > 0 ? (
                detail.fixture_executions.map((fx) => <FixtureBlock key={fx.id} fx={fx} />)
              ) : (
                <Typography.Text type="secondary">无 Fixture 执行记录</Typography.Text>
              )}

              {detail.provider_executions.length > 0 ? (
                <>
                  <Divider>无归属步骤（单 Provider 试跑）</Divider>
                  {detail.provider_executions.map((step) => (
                    <div key={step.id} style={{ marginBottom: 4 }}>
                      <StepCard step={step} />
                    </div>
                  ))}
                </>
              ) : null}

              {detail.fixture_executions.length === 0 && detail.provider_executions.length === 0 ? (
                <Empty description="该记录没有任何步骤明细" />
              ) : null}
            </div>
          )}
        </Spin>
      )}
    </Drawer>
  );
}
