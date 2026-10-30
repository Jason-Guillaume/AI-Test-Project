import { Alert, Card, Col, Divider, Flex, Row, Statistic, Tag, theme, Typography } from 'antd';
import { FAILURE_TYPE_OPTIONS } from './constants';
import type { ReportFailureType } from '@/features/reports/contracts';
import type { SecuritySummary } from '@/features/security-testing/contracts';

// 失败聚类条目：后端返回 Record<string, unknown>，这里做一次结构校验再渲染。
export interface FailureClusterRow {
  failure_type: ReportFailureType | null;
  count: number;
  case_execution_ids: number[];
}

const KNOWN_FAILURE_TYPES = new Set(FAILURE_TYPE_OPTIONS.map((o) => o.value));

/** 收窄失败聚类数组，字段缺失时按空值兜底，不把原始 Record 直接摊进渲染。 */
export function readFailureClusters(raw: Array<Record<string, unknown>> | undefined): FailureClusterRow[] {
  if (!raw) return [];
  const rows: FailureClusterRow[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const ft =
      typeof item.failure_type === 'string' && KNOWN_FAILURE_TYPES.has(item.failure_type as ReportFailureType)
        ? (item.failure_type as ReportFailureType)
        : null;
    rows.push({
      failure_type: ft,
      count: typeof item.count === 'number' ? item.count : 0,
      case_execution_ids: Array.isArray(item.case_execution_ids)
        ? item.case_execution_ids.filter((v): v is number => typeof v === 'number')
        : [],
    });
  }
  return rows;
}

/** 收窄安全摘要：字段口径由后端 features/reports/schemas.py 的 SecuritySummary 保证。 */
export function readSecuritySummary(summary: Record<string, unknown> | null): SecuritySummary | null {
  const sec = summary?.security;
  return sec && typeof sec === 'object' ? (sec as SecuritySummary) : null;
}

/** AI 总结区块：只展示 LLM 结构化字段，不参与统计计算。 */
export function AiSummaryPanel({ summary }: { summary: Record<string, unknown> | null }) {
  const { token } = theme.useToken();

  if (!summary) {
    return (
      <Alert
        type="info"
        showIcon
        message="暂无 AI 总结"
        description="AI 总结生成失败或已被跳过。报告统计与风险等级由代码计算，不受影响；可点击「重新生成 AI 总结」重试。"
      />
    );
  }

  const text = (k: string) => (summary[k] as string | undefined) ?? '';
  const list = (k: string) => ((summary[k] as string[] | undefined) ?? []).filter((v) => typeof v === 'string');

  const listBlock = (title: string, items: string[], tone: 'normal' | 'warn' | 'danger' = 'normal') => {
    if (items.length === 0) return null;
    const color = tone === 'danger' ? token.colorError : tone === 'warn' ? token.colorWarning : token.colorText;
    return (
      <div style={{ marginBottom: token.margin }}>
        <Typography.Text strong>{title}</Typography.Text>
        <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
          {items.map((t, i) => (
            <li key={i} style={{ color, lineHeight: 1.7 }}>
              {t}
            </li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <div>
      {text('overview') && (
        <Alert
          type="success"
          showIcon
          message="总体结论"
          description={<div style={{ lineHeight: 1.8 }}>{text('overview')}</div>}
          style={{ marginBottom: token.margin }}
        />
      )}
      {listBlock('主要发现', list('key_findings'))}
      {listBlock('疑似产品问题（需人工确认，不是已确认缺陷）', list('potential_issues'), 'warn')}
      {listBlock('测试数据问题', list('test_data_issues'))}
      {listBlock('环境问题', list('environment_issues'))}
      {listBlock('改进建议', list('recommendations'))}
      {text('risk_summary') && (
        <div style={{ marginBottom: token.margin }}>
          <Typography.Text strong>风险解释</Typography.Text>
          <div style={{ marginTop: 4, lineHeight: 1.8 }}>{text('risk_summary')}</div>
        </div>
      )}
    </div>
  );
}

/**
 * 安全摘要卡片。
 *
 * 文案统一「疑似问题」，不写「已发现漏洞」；top_findings 不含 evidence 正文。
 */
export function SecuritySummaryCard({ summary }: { summary: SecuritySummary }) {
  const { token } = theme.useToken();
  const sec = summary;

  const severityLabel: Record<string, string> = {
    INFO: '提示',
    LOW: '低',
    MEDIUM: '中',
    HIGH: '高',
    CRITICAL: '严重',
  };
  const severityColor: Record<string, string> = {
    INFO: 'default',
    LOW: 'blue',
    MEDIUM: 'orange',
    HIGH: 'red',
    CRITICAL: 'volcano',
  };

  return (
    <Card size="small" title="安全摘要（疑似问题）" style={{ marginTop: token.margin }}>
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} lg={4}>
          <Statistic title="安全用例" value={sec.cases} />
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Statistic title="通过" value={sec.pass} valueStyle={{ color: token.colorSuccess }} />
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Statistic title="疑似问题" value={sec.potential_issues} valueStyle={{ color: token.colorError }} />
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Statistic title="不确定" value={sec.inconclusive} />
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Statistic title="执行失败" value={sec.failed_execution} valueStyle={{ color: token.colorWarning }} />
        </Col>
        <Col xs={12} sm={8} lg={4}>
          <Statistic title="跳过" value={sec.skipped} />
        </Col>
      </Row>
      <Divider style={{ margin: `${token.marginSM}px 0` }} />
      <Flex gap="small" wrap>
        {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as const).map((lv) => (
          <Tag key={lv} color={severityColor[lv] ?? 'default'}>
            {severityLabel[lv] ?? lv}：{sec.findings?.[lv] ?? 0}
          </Tag>
        ))}
      </Flex>
      {sec.top_findings && sec.top_findings.length > 0 && (
        <>
          <Typography.Text strong style={{ display: 'block', marginTop: token.marginSM }}>
            疑似问题 Top（不含证据正文）
          </Typography.Text>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
            {sec.top_findings.map((f) => (
              <li key={f.id} style={{ lineHeight: 1.7 }}>
                <Tag color={severityColor[f.severity] ?? 'default'}>{severityLabel[f.severity] ?? f.severity}</Tag>
                <Typography.Text>{f.title}</Typography.Text>
                <Typography.Text type="secondary" style={{ marginLeft: token.marginXXS, fontSize: token.fontSizeSM }}>
                  {f.mutation_type}
                </Typography.Text>
              </li>
            ))}
          </ul>
        </>
      )}
      <Alert
        type="info"
        showIcon
        style={{ marginTop: token.marginSM }}
        message="疑似问题需人工确认，不等于已发现漏洞；证据请到「安全测试 · 疑似问题」查看。"
      />
    </Card>
  );
}

