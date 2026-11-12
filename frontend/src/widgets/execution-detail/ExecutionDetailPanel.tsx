import type { ReactNode } from 'react';
import { Alert, Divider, Tag, theme, Typography } from 'antd';
import { AlertOutlined } from '@ant-design/icons';
import { JsonView } from '@/shared/ui/JsonView';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { CASE_EXECUTION_STATUS_COLOR, CASE_EXECUTION_STATUS_LABEL } from '@/features/test-management/status';
import { WEB_STEP_STATUS_COLOR, WEB_STEP_STATUS_LABEL } from '@/features/web-testing/status';
import { fmtDuration, fmtTime } from '@/shared/lib/format';
import type { WebArtifactRef, WebStepRecord } from '@/features/web-testing/lib/webSnapshot';
import type { CaseExecutionLike } from './types';
import { formatLocator } from '@/features/web-testing/lib/webSnapshot';
import { AssertionViewer } from './AssertionViewer';
import { ScreenshotViewer } from './ScreenshotViewer';
import { TraceViewer } from './TraceViewer';

export function DetailPanel({
  execution,
  isWeb,
  selectedStepInfo,
  webArtifactCount,
  screenshotsCount,
  hasTrace,
  isFailed,
  traceArtifact,
  artifacts,
}: {
  execution: CaseExecutionLike;
  isWeb: boolean;
  selectedStepInfo: {
    index: number;
    stepNo: number;
    step: WebStepRecord;
    isFailed: boolean;
  } | null;
  webArtifactCount: number;
  screenshotsCount: number;
  hasTrace: boolean;
  isFailed: boolean;
  traceArtifact: WebArtifactRef | null;
  artifacts: WebArtifactRef[];
}) {
  const { token } = theme.useToken();

  // 用例概览
  const overview = (
    <Section title="执行概览">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: token.marginXS }}>
        <InfoCell label="状态">
          <StatusBadge value={execution.status} colors={CASE_EXECUTION_STATUS_COLOR} labels={CASE_EXECUTION_STATUS_LABEL} />
        </InfoCell>
        <InfoCell label="执行器">
          <Typography.Text style={{ fontSize: token.fontSizeSM }}>{execution.executor_type ?? '-'}</Typography.Text>
        </InfoCell>
        <InfoCell label="耗时">
          <Typography.Text style={{ fontSize: token.fontSizeSM }}>{fmtDuration(execution.duration_ms)}</Typography.Text>
        </InfoCell>
        <InfoCell label="开始">
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{fmtTime(execution.started_at)}</Typography.Text>
        </InfoCell>
        <InfoCell label="结束">
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{fmtTime(execution.finished_at)}</Typography.Text>
        </InfoCell>
      </div>
      {execution.test_case_id != null && (
        <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
          用例 ID：{execution.test_case_id}
        </Typography.Text>
      )}
    </Section>
  );

  // 失败时突出错误详情
  const errorSection = isFailed ? (
    <Alert
      type="error"
      showIcon
      icon={<AlertOutlined />}
      message={
        <span>
          执行失败
          {execution.error_code ? (
            <Tag color="error" bordered={false} style={{ marginLeft: 8 }}>
              {execution.error_code}
            </Tag>
          ) : null}
        </span>
      }
      description={
        <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {execution.error_message ?? '无错误信息'}
        </div>
      }
    />
  ) : null;

  // 报告页扩展：失败分类
  const failureTypeSection = execution.failure_type ? (
    <Section title="失败分类">
      <Tag color="error" bordered={false}>{execution.failure_type}</Tag>
    </Section>
  ) : null;

  // 报告页扩展：优先级与用例类型
  const metaSection = execution.priority || execution.case_type ? (
    <Section title="用例元信息">
      <div style={{ display: 'flex', gap: token.marginXS, flexWrap: 'wrap' }}>
        {execution.priority ? <Tag bordered={false}>优先级：{execution.priority}</Tag> : null}
        {execution.case_type ? <Tag bordered={false}>类型：{execution.case_type}</Tag> : null}
      </div>
    </Section>
  ) : null;

  // 选中步骤详情：只显示 locator 与 operation，不显示执行值（scrub 红线）
  const stepSection = selectedStepInfo ? (
    <Section title={`步骤 #${selectedStepInfo.stepNo}`}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: token.marginXS }}>
        <div style={{ display: 'flex', gap: token.marginXS, alignItems: 'center', flexWrap: 'wrap' }}>
          <StatusBadge
            value={selectedStepInfo.step.status}
            colors={WEB_STEP_STATUS_COLOR}
            labels={WEB_STEP_STATUS_LABEL}
          />
          {typeof selectedStepInfo.step.operation === 'string' && (
            <Typography.Text code style={{ fontSize: token.fontSizeSM }}>
              {selectedStepInfo.step.operation}
            </Typography.Text>
          )}
          {typeof selectedStepInfo.step.duration_ms === 'number' && (
            <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
              耗时 {fmtDuration(selectedStepInfo.step.duration_ms)}
            </Typography.Text>
          )}
        </div>

        {typeof selectedStepInfo.step.name === 'string' && selectedStepInfo.step.name.length > 0 && (
          <InfoCell label="名称" value={selectedStepInfo.step.name} />
        )}

        {(() => {
          const locator = formatLocator(selectedStepInfo.step.locator);
          return locator ? (
            <InfoCell
              label="定位器"
              value={
                <Typography.Text code style={{ wordBreak: 'break-all' }}>
                  {locator}
                </Typography.Text>
              }
            />
          ) : null;
        })()}

        {/* 后端只在执行级写 error_message（playwright_executor.py:151），没有步骤级错误字段；
            执行器在首个失败步骤即 break，所以首个失败步骤就是这个文案的确切出处 */}
        {selectedStepInfo.isFailed && typeof execution.error_message === 'string' && (
          <Alert
            type="error"
            showIcon
            message="步骤错误"
            description={execution.error_message}
          />
        )}
      </div>
    </Section>
  ) : null;

  // 断言：用例级列表，不挂到具体步骤（红线 6）
  const assertionSection = (
    <Section title="断言结果">
      <AssertionViewer rows={execution.assertion_results} emptyText="无断言结果" />
    </Section>
  );

  // 请求：Web 执行只说 step_count，不假装有关联请求（红线 4）
  const requestSection = (
    <Section title="请求快照">
      {isWeb ? (
        <Alert
          type="info"
          showIcon
          message="Web 执行不产生 HTTP 请求"
          description={
            <span>
              Web 用例的 request_snapshot 只写步骤数：
              <Tag style={{ marginLeft: 4 }} bordered={false}>
                step_count: {toDisplay(execution.request_snapshot?.step_count)}
              </Tag>
              关联请求/响应请查看执行器日志，此处不做伪造。
            </span>
          }
        />
      ) : (
        <JsonView value={execution.request_snapshot ?? null} />
      )}
    </Section>
  );

  // 响应：Web 执行说明只有 web 快照
  const responseSection = (
    <Section title="响应快照">
      {isWeb ? (
        <Alert
          type="info"
          showIcon
          message="Web 执行的响应快照"
          description={
            <span>
              包含 web 步骤日志与附件清单。附件数：
              <Tag style={{ marginLeft: 4 }} bordered={false}>
                {webArtifactCount}
              </Tag>
              其中截图 {screenshotsCount} 个，{hasTrace ? '1 个 Trace。' : '无 Trace。'}
            </span>
          }
        />
      ) : (
        <JsonView value={execution.response_snapshot ?? null} />
      )}
    </Section>
  );

  // 附件与 Trace：Web 执行独有
  const artifactsSection = isWeb
    ? (
      <Section title="附件与 Trace">
        {webArtifactCount === 0 ? (
          <Alert type="info" showIcon message="无附件" description="本次执行未产生截图或 Trace。" />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: token.marginXS }}>
            <ScreenshotViewer artifacts={artifacts} emptyText="无截图" />
            <Divider style={{ margin: `${token.marginXS}px 0` }} />
            <TraceViewer artifact={traceArtifact ?? undefined} emptyText="无 Trace 附件" />
          </div>
        )}
      </Section>
    )
    : null;

  // 上下文
  const contextSection = (
    <Section title="运行时上下文">
      <JsonView value={execution.context_json ?? null} />
    </Section>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: token.marginXS }}>
      {errorSection}
      {failureTypeSection}
      {metaSection}
      {overview}
      {stepSection}
      {assertionSection}
      {requestSection}
      {responseSection}
      {artifactsSection}
      {contextSection}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const { token } = theme.useToken();
  return (
    <div
      style={{
        padding: token.paddingSM,
        borderRadius: token.borderRadiusSM,
        background: token.colorFillQuaternary,
        border: `1px solid ${token.colorBorderSecondary}`,
      }}
    >
      <div style={{ marginBottom: token.marginXS }}>
        <Typography.Text strong style={{ fontSize: token.fontSize }}>
          {title}
        </Typography.Text>
      </div>
      {children}
    </div>
  );
}

function InfoCell({ label, value, children }: { label: string; value?: ReactNode; children?: ReactNode }) {
  const { token } = theme.useToken();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ color: token.colorTextTertiary, fontSize: token.fontSizeSM }}>{label}</span>
      <div style={{ fontSize: token.fontSize }}>{children ?? value}</div>
    </div>
  );
}

/** 把 request_snapshot.step_count 等 unknown 值转成可渲染的字符串。 */
function toDisplay(v: unknown): string {
  if (v == null) return '-';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}
