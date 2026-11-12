import { Button, Empty, Flex, Space, Tag, Typography } from 'antd';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

type RecordValue = Record<string, unknown>;
type SummaryKind = 'plan' | 'execution' | 'analysis';

function record(value: unknown): RecordValue | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as RecordValue : null;
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : [];
}

function raw(value: unknown): string {
  try { return JSON.stringify(value, null, 2) ?? String(value); } catch { return String(value); }
}

export function AgentRawDetails({ value }: { value: unknown }) {
  return <details className="agent-raw-details"><summary>查看原始数据</summary><pre>{raw(value)}</pre></details>;
}

function ExecutionLink({ id, projectId }: { id: unknown; projectId: unknown }) {
  if (typeof id !== 'number' || typeof projectId !== 'number') return null;
  return <Link to={`/console/execution-history?runId=${id}&projectId=${projectId}`}><Button type="link" size="small">查看执行详情</Button></Link>;
}

/** 只呈现后端当前契约里确实存在的业务字段；完整原始对象默认折叠。 */
export function AgentStructuredSummary({ kind, value }: { kind: SummaryKind; value: unknown }) {
  const outer = record(value);
  if (!outer) return <><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未返回结构化结果" /><AgentRawDetails value={value} /></>;
  const nested = record(kind === 'plan' ? outer.plan : kind === 'execution' ? outer.run : outer.analysis);
  const data = nested ?? outer;
  const known: ReactNode[] = [];

  if (kind === 'plan') {
    const target = text(data.target) ?? text(outer.intent);
    const targetType = text(outer.target_type);
    const targetIds = Array.isArray(outer.target_ids) ? outer.target_ids.filter((id) => typeof id === 'number') : [];
    const strategies = stringList(data.strategies);
    const focus = stringList(data.focus);
    const acceptance = stringList(data.acceptance_criteria);
    if (target) known.push(<div key="target"><Typography.Text strong>目标：</Typography.Text>{target}</div>);
    if (targetType || targetIds.length) known.push(<div key="scope"><Typography.Text strong>范围：</Typography.Text>{targetType ?? '未知类型'}{targetIds.length ? ` · ${targetIds.map((id) => `#${id}`).join(', ')}` : ''}</div>);
    const environment = text(data.environment) ?? (typeof data.environment_id === 'number' ? `环境 #${data.environment_id}` : typeof outer.environment_id === 'number' ? `环境 #${outer.environment_id}` : null);
    if (environment) known.push(<div key="environment"><Typography.Text strong>环境：</Typography.Text>{environment}</div>);
    if (strategies.length) known.push(<div key="strategies"><Typography.Text strong>策略：</Typography.Text><Space wrap>{strategies.map((item) => <Tag key={item}>{item}</Tag>)}</Space></div>);
    if (focus.length) known.push(<div key="focus"><Typography.Text strong>重点场景：</Typography.Text>{focus.join('、')}</div>);
    if (typeof data.estimated_points === 'number') known.push(<div key="points"><Typography.Text strong>预计测试点：</Typography.Text>{data.estimated_points}</div>);
    if (acceptance.length) known.push(<div key="acceptance"><Typography.Text strong>验收条件：</Typography.Text><ul>{acceptance.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></div>);
  } else if (kind === 'execution') {
    const status = text(data.status);
    const statusLabel: Record<string, string> = { COMPLETED: '已完成', FAILED: '失败', RUNNING: '执行中', PENDING: '等待中', CANCELLED: '已取消' };
    if (status) known.push(<Tag key="status" color={status === 'FAILED' ? 'red' : status === 'COMPLETED' ? 'green' : 'blue'}>{statusLabel[status] ?? status}</Tag>);
    const counters = [
      ['total', '总数'], ['passed', '通过'], ['failed', '失败'], ['skipped', '跳过'], ['error', '错误'],
    ] as const;
    const available = counters.filter(([key]) => typeof data[key] === 'number');
    if (available.length) known.push(<Flex key="counts" wrap="wrap" gap={8}>{available.map(([key, label]) => <Tag key={key}>{label} {String(data[key])}</Tag>)}</Flex>);
    const start = text(data.started_at);
    const finish = text(data.finished_at);
    if (start && finish) {
      const duration = Date.parse(finish) - Date.parse(start);
      known.push(<div key="duration"><Typography.Text strong>耗时：</Typography.Text>{Number.isFinite(duration) && duration >= 0 ? `${Math.round(duration / 1000)} 秒` : '未知'}</div>);
    }
    const error = text(data.error_message);
    const failures = typeof data.failed === 'number' ? data.failed : 0;
    const errors = typeof data.error === 'number' ? data.error : 0;
    if (error) known.push(<Typography.Paragraph key="error" type="danger" ellipsis={{ rows: 3, expandable: true }}>{error}</Typography.Paragraph>);
    else if (failures + errors > 0) known.push(<Typography.Text key="failure" type="secondary">失败明细与证据请在执行详情中查看。</Typography.Text>);
    const runId = data.id ?? outer.run_id;
    const projectId = data.project_id ?? outer.project_id;
    if (typeof runId === 'number' && typeof projectId === 'number') known.push(<ExecutionLink key="link" id={runId} projectId={projectId} />);
    if (known.length === 0) known.push(<Typography.Text key="empty" type="secondary">执行记录未包含可展示的状态或统计信息。</Typography.Text>);
  } else {
    const summary = text(data.summary);
    const issues = Array.isArray(data.issues) ? data.issues.map(record).filter((item): item is RecordValue => item != null) : null;
    const recommendation = text(data.recommendation);
    const findings = Array.isArray(data.security_findings) ? data.security_findings.map(record).filter((item): item is RecordValue => item != null) : null;
    if (summary) known.push(<Typography.Paragraph key="summary">{summary}</Typography.Paragraph>);
    if (issues) {
      known.push(issues.length ? <div key="issues"><Typography.Text strong>发现与证据</Typography.Text><ul>{issues.map((issue, index) => <li key={index}><Tag color={issue.severity === 'POTENTIAL_BUG' ? 'orange' : 'blue'}>{text(issue.severity) ?? '未知类型'}</Tag>{typeof issue.case_id === 'number' ? `用例 #${issue.case_id}：` : ''}{text(issue.summary) ?? '未提供摘要'}{text(issue.detail) ? <Typography.Text type="secondary"> — {text(issue.detail)}</Typography.Text> : null}</li>)}</ul></div> : <Typography.Text key="issues-empty" type="secondary">本次分析未列出问题。</Typography.Text>);
    } else {
      known.push(<Typography.Text key="issues-missing" type="secondary">分析结果未包含问题列表。</Typography.Text>);
    }
    if (findings) known.push(<Typography.Text key="findings" type="secondary">未关闭安全线索：{findings.length} 项（需人工复核，不代表已确认漏洞）</Typography.Text>);
    if (recommendation) known.push(<div key="recommendation"><Typography.Text strong>建议下一步：</Typography.Text>{recommendation}</div>);
  }

  return (
    <div className="agent-structured-summary">
      {known.length ? known : <Typography.Text type="secondary">未识别到已知摘要字段；可查看原始数据。</Typography.Text>}
      <AgentRawDetails value={value} />
    </div>
  );
}
