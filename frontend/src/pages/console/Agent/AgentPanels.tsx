import { Alert, Button, Empty, Flex, Tag, Typography } from 'antd';
import { EyeOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { AgentMessage } from '@/features/agent/contracts';

// ---- 阶段 → 快捷操作按钮映射（与后端 _STAGE_ACTIONS 对齐）----
export const STAGE_ACTION_LABELS: Record<string, string> = {
  confirm_points: '确认测试点',
  confirm_cases: '确认测试用例',
  execute: '执行测试',
  analyze: '分析结果',
  regenerate_points: '重新生成测试点',
  regenerate_cases: '重新生成测试用例',
  confirm_report: '确认报告并发送飞书通知',
  skip_notification: '跳过飞书通知',
};

export const STAGE_LABELS: Record<string, string> = {
  UNDERSTANDING: '理解中',
  CONTEXT_LOADING: '加载上下文',
  PLANNING: '规划中',
  TEST_POINT_REVIEW: '测试点待确认',
  TEST_POINT_GENERATED: '测试点已生成',
  TEST_CASE_REVIEW: '用例待确认',
  READY_TO_EXECUTE: '准备执行',
  EXECUTING: '执行中',
  ANALYZING: '分析中',
  REPORT_GENERATING: '报告生成中',
  REPORT_REVIEW: '报告待确认',
  NOTIFYING: '通知发送中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CLARIFY: '等待澄清',
};

/** 报告风险等级 Tag 颜色（与报告页保持一致）。 */
const RISK_TAG_COLOR: Record<string, string> = {
  LOW: 'green',
  MEDIUM: 'gold',
  HIGH: 'orange',
  CRITICAL: 'red',
};
const RISK_LABEL: Record<string, string> = {
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  CRITICAL: '严重',
};

// ---- 消息类型 → 渲染器 ----
export function MessageBubble({ message }: { message: AgentMessage }) {
  const navigate = useNavigate();
  const roleIcon = message.role === 'USER' ? '👤' : message.role === 'SYSTEM' ? '⚙️' : '🤖';
  const bgColor =
    message.role === 'USER'
      ? 'background: #e6f7ff;'
      : message.role === 'SYSTEM'
        ? 'background: #fff7e6;'
        : 'background: #f0f0f0;';

  // 结构化消息：从 metadata_json 提取内容渲染
  if (message.message_type !== 'TEXT' && message.metadata_json) {
    const meta = message.metadata_json as Record<string, unknown>;
    let body: React.ReactNode = null;
    switch (message.message_type) {
      case 'TEST_PLAN':
        body = (
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>
            <b>测试计划</b>
            {meta.plan != null && (
              <pre style={{ margin: '4px 0 0', padding: 8, background: '#fafafa', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(meta.plan, null, 2)}
              </pre>
            )}
          </div>
        );
        break;
      case 'TEST_POINTS':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>测试点</b>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {(meta.points as Array<Record<string, unknown>> | undefined)?.map((p, i) => (
                <li key={i}>
                  {p.name as string}
                  {p.priority != null && <Tag style={{ marginLeft: 6 }} color="blue">{p.priority as string}</Tag>}
                </li>
              ))}
            </ul>
          </div>
        );
        break;
      case 'TEST_CASES':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>测试用例</b>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {(meta.cases as Array<Record<string, unknown>> | undefined)?.map((c, i) => (
                <li key={i}>
                  {c.name as string}
                  {c.priority != null && <Tag style={{ marginLeft: 6 }}>{c.priority as string}</Tag>}
                </li>
              ))}
            </ul>
          </div>
        );
        break;
      case 'EXECUTION':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>执行结果</b>
            <pre style={{ margin: '4px 0 0', padding: 8, background: '#fafafa', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(meta.run ?? meta, null, 2)}
            </pre>
          </div>
        );
        break;
      case 'RESULT':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>分析结果</b>
            <pre style={{ margin: '4px 0 0', padding: 8, background: '#fafafa', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(meta.analysis ?? meta, null, 2)}
            </pre>
          </div>
        );
        break;
      case 'REPORT': {
        const brief = (meta.report ?? meta) as Record<string, unknown>;
        const totals = (brief.totals as Record<string, unknown> | undefined) ?? {};
        const ai = (brief.ai_summary as Record<string, unknown> | undefined) ?? null;
        const risk = String(brief.risk_level ?? '');
        return (
          <div style={{ fontSize: 13 }}>
            <b>测试报告</b>
            <div style={{ margin: '4px 0' }}>
              <Tag color={RISK_TAG_COLOR[risk] ?? 'default'}>
                风险 {(RISK_LABEL[risk] ?? risk) || '-'}
              </Tag>
              <Tag color="blue">通过率 {String(brief.pass_rate ?? '-')}%</Tag>
              <Tag>共 {String(totals.total ?? brief.total_cases ?? '-')} 条</Tag>
              <Tag color="green">{String(totals.passed ?? '-')} 通过</Tag>
              <Tag color="red">{String(totals.failed ?? '-')} 失败</Tag>
              {Number(totals.error ?? 0) > 0 && <Tag color="orange">{String(totals.error)} 错误</Tag>}
            </div>
            {brief.report_no != null && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {String(brief.report_no)}
                {brief.title ? ` · ${String(brief.title)}` : ''}
              </Typography.Text>
            )}
            {typeof ai?.overview === 'string' && ai.overview ? (
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#555', whiteSpace: 'pre-wrap' }}>
                {ai.overview}
              </p>
            ) : null}
            {brief.report_id != null && (
              <Button
                size="small"
                type="link"
                style={{ padding: 0, marginTop: 2 }}
                icon={<EyeOutlined />}
                onClick={() => navigate(`/console/test-reports/${String(brief.report_id)}`)}
              >
                查看完整报告
              </Button>
            )}
          </div>
        );
      }
      case 'NOTIFICATION': {
        const brief = (meta.notification ?? meta) as Record<string, unknown>;
        const ok = brief.skipped === false && brief.status === 'SUCCESS';
        const skipped = brief.skipped === true;
        return (
          <div style={{ fontSize: 13 }}>
            <b>飞书通知</b>
            <div style={{ margin: '4px 0' }}>
              <Tag color={skipped ? 'default' : ok ? 'green' : 'red'}>
                {skipped ? '已跳过' : ok ? '发送成功' : `发送失败：${String(brief.error_message ?? '未知错误')}`}
              </Tag>
              {brief.channel_name != null && <Tag>{String(brief.channel_name)}</Tag>}
            </div>
            {brief.message != null && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {String(brief.message)}
              </Typography.Text>
            )}
            {!ok && !skipped && (
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 2 }}>
                通知发送失败不影响报告与执行记录状态，可在报告详情页重试。
              </Typography.Text>
            )}
          </div>
        );
      }
      case 'CLARIFY':
        body = <div style={{ fontSize: 13 }}><b>需要澄清</b><p style={{ margin: '4px 0 0' }}>{message.content}</p></div>;
        break;
      default:
        body = <pre style={{ fontSize: 12 }}>{JSON.stringify(meta, null, 2)}</pre>;
    }
    return (
      <div style={{ marginBottom: 12 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{roleIcon} {message.role}</Typography.Text>
        <div style={{ marginTop: 4, padding: '8px 12px', borderRadius: 8, ...bgColor.split(';').reduce((acc, prop) => { const [k, v] = prop.split(':').map(s => s.trim()); return { ...acc, [k]: v }; }, {} as React.CSSProperties) }}>
          {body}
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{roleIcon} {message.role}</Typography.Text>
      <div style={{ marginTop: 4, padding: '8px 12px', borderRadius: 8, ...bgColor.split(';').reduce((acc, prop) => { const [k, v] = prop.split(':').map(s => s.trim()); return { ...acc, [k]: v }; }, {} as React.CSSProperties) }}>
        <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{message.content}</span>
      </div>
    </div>
  );
}

// ---- 工作区「报告」面板：Agent 侧脱敏摘要（由代码统计，不含 webhook / secret）----
export function ReportBriefPanel({
  brief,
  onOpen,
}: {
  brief: Record<string, unknown> | null;
  onOpen: () => void;
}) {
  if (!brief) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无报告数据" />;
  const totals = (brief.totals as Record<string, unknown> | undefined) ?? {};
  const ai = (brief.ai_summary as Record<string, unknown> | undefined) ?? null;
  const risk = String(brief.risk_level ?? '');
  const potentialIssues = ((ai?.potential_issues as string[] | undefined) ?? []);
  const recommendations = ((ai?.recommendations as string[] | undefined) ?? []);

  return (
    <div style={{ fontSize: 13 }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 6 }}>
        <Typography.Text strong>{String(brief.title ?? brief.report_no ?? '测试报告')}</Typography.Text>
        {brief.report_id != null && (
          <Button size="small" type="link" style={{ padding: 0 }} icon={<EyeOutlined />} onClick={onOpen}>
            查看详情
          </Button>
        )}
      </Flex>
      <div style={{ marginBottom: 6 }}>
        <Tag color={RISK_TAG_COLOR[risk] ?? 'default'}>风险 {(RISK_LABEL[risk] ?? risk) || '-'}</Tag>
        <Tag color="blue">通过率 {String(brief.pass_rate ?? '-')}%</Tag>
      </div>
      <div style={{ color: '#666', fontSize: 12, marginBottom: 8 }}>
        共 {String(totals.total ?? '-')} 条 · 通过 {String(totals.passed ?? '-')} · 失败 {String(totals.failed ?? '-')} ·
        错误 {String(totals.error ?? '-')} · 跳过 {String(totals.skipped ?? '-')}
        {brief.duration_ms != null && ` · 耗时 ${(Number(brief.duration_ms) / 1000).toFixed(2)}s`}
      </div>
      {typeof ai?.overview === 'string' && ai.overview && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 8, fontSize: 12 }}
          message="总体结论"
          description={<span style={{ whiteSpace: 'pre-wrap' }}>{ai.overview}</span>}
        />
      )}
      {potentialIssues.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8, fontSize: 12 }}
          message="疑似产品问题（需人工确认，不是已确认缺陷）"
          description={
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {potentialIssues.map((t, i) => (
                <li key={i} style={{ lineHeight: 1.6 }}>
                  {t}
                </li>
              ))}
            </ul>
          }
        />
      )}
      {recommendations.length > 0 && (
        <div style={{ fontSize: 12, color: '#666' }}>
          <b>建议</b>
          <ul style={{ margin: '2px 0 0', paddingLeft: 16 }}>
            {recommendations.map((t, i) => (
              <li key={i} style={{ lineHeight: 1.6 }}>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---- 工作区「通知」面板：飞书发送结果留痕 ----
export function NotificationBriefPanel({ brief }: { brief: Record<string, unknown> | null }) {
  if (!brief) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知记录" />;
  const skipped = brief.skipped === true;
  const ok = !skipped && brief.status === 'SUCCESS';
  return (
    <div style={{ fontSize: 13 }}>
      <Tag color={skipped ? 'default' : ok ? 'green' : 'red'}>
        {skipped ? '已跳过' : ok ? '发送成功' : '发送失败'}
      </Tag>
      {brief.channel_name != null && <Tag>{String(brief.channel_name)}</Tag>}
      {brief.message != null && (
        <div style={{ marginTop: 6, fontSize: 12, color: '#666' }}>{String(brief.message)}</div>
      )}
      {!ok && !skipped && (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 8, fontSize: 12 }}
          message="通知发送失败"
          description={String(brief.error_message ?? '未知错误')}
        />
      )}
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
        通知失败不会把报告或执行记录标记为失败，可在报告详情页重试。
      </Typography.Text>
    </div>
  );
}

