// 用例执行详情：宽 880 抽屉，左 30% 时间线 + 右 70% 详情面板。
//
// 设计要点（对齐重构计划 §4 与本次任务红线）：
// - 不做多 Tab Modal，右侧用内部分区/折叠/锚点导航；
// - 失败用例自动定位到 firstFailedStep，突出错误与证据；
// - 成功用例：简洁展示执行步骤；
// - 三态完整：loading / error / empty（本组件无内部异步状态，由调用方控制 open）；
// - 纯组件：open / execution / onClose 三个 prop，状态由调用方持有；
// - open === false 或 execution == null 时不显示内容、不抛错、hooks 顺序稳定。
//
// 诚实性红线：
// 1. API / BUSINESS_FLOW 执行没有 steps —— readWebSnapshot 返回 null 时给出明确空态；
// 2. 步骤状态只有 PASSED/FAILED/ERROR；未执行步骤在时间线里以灰色占位行补出，不用「跳过」；
// 3. 步骤 value 不入库、FILL/SELECT 被 scrub —— 只显示 locator 与 operation；
// 4. WEB 用例的 request_snapshot 只有 { step_count }，不假装有关联 HTTP 请求；
// 5. Trace 不做 DOM 回放，只做可搜索的动作时序；
// 6. 断言字典里没有 step 索引，只作为「用例级断言列表」；
// 7. 截图强制走 webUIApi.artifact(id) 取 blob，不能把 artifacts.url 当 <img src>；
// 8. 业务流驱动的 case_execution_id 为 null，附件只读快照清单。

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Divider, Tag, theme, Typography } from 'antd';
import { AlertOutlined } from '@ant-design/icons';
import { DetailDrawer, DETAIL_DRAWER_WIDTH } from '@/components/DetailDrawer';
import { JsonView } from '@/components/JsonView';
import { StatusBadge } from '@/components/StatusBadge';
import {
  CASE_EXECUTION_STATUS_COLOR,
  CASE_EXECUTION_STATUS_LABEL,
  WEB_STEP_STATUS_COLOR,
  WEB_STEP_STATUS_LABEL,
} from '@/shared/status';
import { fmtDuration, fmtTime } from '@/shared/format';
import { readWebSnapshot, formatLocator, firstFailedStep, isWebStepEntry } from '@/shared/webSnapshot';
import type { WebArtifactRef, WebStepRecord } from '@/shared/webSnapshot';
import type { CaseExecutionLike } from './types';
import { ExecutionTimeline } from './ExecutionTimeline';
import { AssertionViewer } from './AssertionViewer';
import { ScreenshotViewer } from './ScreenshotViewer';
import { TraceViewer } from './TraceViewer';
import { DefectSourceLinks } from './DefectSourceLinks';

interface CaseExecutionDetailProps {
  open: boolean;
  /** null 表示尚未选择；此时抽屉不显示内容 */
  execution: CaseExecutionLike | null;
  onClose: () => void;
}

/**
 * 用例执行详情抽屉。
 *
 * 组件内不保存任何抽屉状态；调用方通过 open / execution / onClose 控制。
 * execution 为 null 时抽屉保持 open=false，即使 open=true 也不渲染内容以避免报错。
 */
export function CaseExecutionDetail({ open, execution, onClose }: CaseExecutionDetailProps) {
  const [selectedStep, setSelectedStep] = useState<number | null>(null);

  const snapshot = useMemo(() => readWebSnapshot(execution?.response_snapshot), [execution]);
  const steps = useMemo(() => {
    const raw = snapshot?.steps ?? [];
    return raw.filter(isWebStepEntry);
  }, [snapshot]);

  // 总步骤数：Web 执行器写在 request_snapshot.step_count 里。
  // 混合业务流程（BUSINESS_FLOW）的 request_snapshot 是 {flow_id, flow_name, ...}，
  // 没有 step_count，退回已记录的步骤数——否则「未执行」判定与头部总数都会失效。
  const totalSteps = useMemo(() => {
    const v = execution?.request_snapshot?.step_count;
    return typeof v === 'number' ? v : steps.length;
  }, [execution, steps]);

  const firstFailed = useMemo(() => firstFailedStep(steps), [steps]);
  const firstFailedIndex = useMemo(
    () => (firstFailed ? steps.indexOf(firstFailed) : null),
    [steps, firstFailed],
  );
  // 时间线会补出未执行占位行，数组下标不再是展示用的步骤号，失败定位必须用 step 字段
  const firstFailedStepNo = useMemo(() => {
    if (!firstFailed) return null;
    return typeof firstFailed.step === 'number' ? firstFailed.step : (firstFailedIndex ?? 0) + 1;
  }, [firstFailed, firstFailedIndex]);

  const traceArtifact = useMemo<WebArtifactRef | null>(() => {
    return snapshot?.artifacts?.find((a) => a.kind === 'TRACE') ?? null;
  }, [snapshot]);

  // 切换用例时重置选中步骤；失败用例自动定位到 firstFailedIndex
  useEffect(() => {
    setSelectedStep(firstFailedIndex);
  }, [execution?.id, firstFailedIndex]);

  const selectedStepInfo = useMemo(() => {
    if (selectedStep == null) return null;
    const step = steps[selectedStep];
    if (!step) return null;
    return {
      index: selectedStep,
      // 步骤号取后端 step 字段；没有时退回数组下标 +1（与时间线占位行补位后的下标不同）
      stepNo: typeof step.step === 'number' ? step.step : selectedStep + 1,
      step,
      isFailed: !!step.status && step.status !== 'PASSED',
    };
  }, [steps, selectedStep]);

  // ⚠️ 判据必须是「快照里确实有 Web 证据」，而不是执行器类型字面量：
  // 后端把嵌套 WEB 动作的 steps / artifacts 聚合进 BUSINESS_FLOW 的
  // response_snapshot.web（test_case_executor.py:332-338），而这类行的 executor_type
  // 是 'BUSINESS_FLOW'。只认 'WEB' 会把混合业务的步骤、截图与 Trace 整块丢弃，
  // 并显示「业务流程执行不产生步骤日志」的假陈述。
  const isWeb = snapshot != null;

  return (
    <DetailDrawer
      open={open && execution != null}
      onClose={onClose}
      title={execution ? `用例执行 #${execution.id} · ${execution.case_name ?? '未命名'}` : '用例执行详情'}
      width={DETAIL_DRAWER_WIDTH.EXECUTION}
      destroyOnClose
    >
      {execution == null ? null : (
        <>
        {['FAILED', 'ERROR'].includes(execution.status) && <DefectSourceLinks sourceType="CASE_EXECUTION" sourceId={execution.id} />}
        <ExecContent
          execution={execution}
          isWeb={isWeb}
          steps={steps}
          totalSteps={totalSteps}
          firstFailedStepNo={firstFailedStepNo}
          selectedStep={selectedStep}
          selectedStepInfo={selectedStepInfo}
          traceArtifact={traceArtifact}
          artifacts={snapshot?.artifacts ?? []}
          onViewStep={setSelectedStep}
        />
        </>
      )}
    </DetailDrawer>
  );
}

interface ExecContentProps {
  execution: CaseExecutionLike;
  isWeb: boolean;
  steps: WebStepRecord[];
  totalSteps: number | null;
  firstFailedStepNo: number | null;
  selectedStep: number | null;
  selectedStepInfo: {
    index: number;
    stepNo: number;
    step: WebStepRecord;
    isFailed: boolean;
  } | null;
  traceArtifact: WebArtifactRef | null;
  artifacts: WebArtifactRef[];
  onViewStep: (index: number) => void;
}

/** 内部内容：30% 时间线 + 70% 详情面板 */
function ExecContent({
  execution,
  isWeb,
  steps,
  totalSteps,
  firstFailedStepNo,
  selectedStep,
  selectedStepInfo,
  traceArtifact,
  artifacts,
  onViewStep,
}: ExecContentProps) {
  const { token } = theme.useToken();
  const isFailed = execution.status === 'FAILED' || execution.status === 'ERROR';

  const screenshotsCount = artifacts.filter((a) => a.kind !== 'TRACE').length;
  const hasTrace = !!traceArtifact;

  return (
    <div style={{ display: 'flex', height: '100%', gap: token.marginXS }}>
      {/* 左侧 30%：时间线 */}
      <div
        style={{
          width: '30%',
          display: 'flex',
          flexDirection: 'column',
          gap: token.marginXS,
          borderRight: `1px solid ${token.colorBorderSecondary}`,
          paddingRight: token.marginXS,
          minHeight: 0,
        }}
      >
        <TimelineHeader
          stepCount={steps.length}
          totalSteps={totalSteps}
          firstFailedStepNo={firstFailedStepNo}
        />
        <TimelineBody
          isWeb={isWeb}
          steps={steps}
          totalSteps={totalSteps}
          selectedStep={selectedStep}
          onSelect={onViewStep}
        />
      </div>

      {/* 右侧 70%：详情面板 */}
      <div style={{ width: '70%', overflowY: 'auto', paddingRight: 4 }}>
        <DetailPanel
          execution={execution}
          isWeb={isWeb}
          selectedStepInfo={selectedStepInfo}
          webArtifactCount={artifacts.length}
          screenshotsCount={screenshotsCount}
          hasTrace={hasTrace}
          isFailed={isFailed}
          traceArtifact={traceArtifact}
          artifacts={artifacts}
        />
      </div>
    </div>
  );
}

function TimelineHeader({
  stepCount,
  totalSteps,
  firstFailedStepNo,
}: {
  stepCount: number;
  totalSteps: number | null;
  firstFailedStepNo: number | null;
}) {
  const { token } = theme.useToken();
  // 总数已知且有缺口时显示「已执行 / 总数」，让未执行的步骤一眼可见
  const hasUnreached = totalSteps != null && totalSteps > stepCount;
  const countText = stepCount > 0 ? (hasUnreached ? `${stepCount} / ${totalSteps} 步` : `${stepCount} 步`) : '无';
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: token.marginXS, flexWrap: 'wrap' }}>
      <Typography.Text strong style={{ fontSize: token.fontSize }}>
        执行步骤
      </Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
        {countText}
      </Typography.Text>
      {firstFailedStepNo != null && (
        <Tag color="error" bordered={false} style={{ fontSize: token.fontSizeSM }}>
          第 {firstFailedStepNo} 步失败
        </Tag>
      )}
      {hasUnreached && (
        <Tag bordered={false} style={{ fontSize: token.fontSizeSM }}>
          还有 {totalSteps - stepCount} 步未执行
        </Tag>
      )}
    </div>
  );
}

function TimelineBody({
  isWeb,
  steps,
  totalSteps,
  selectedStep,
  onSelect,
}: {
  isWeb: boolean;
  steps: WebStepRecord[];
  totalSteps: number | null;
  selectedStep: number | null;
  onSelect: (index: number) => void;
}) {
  if (!isWeb) {
    return (
      <Alert
        type="info"
        showIcon
        message="该执行无逐步记录"
        description="API / 业务流程执行不产生步骤日志。右侧展示断言、请求/响应与上下文。"
      />
    );
  }
  if (steps.length === 0) {
    return (
      <Alert
        type="warning"
        showIcon
        message="无步骤日志"
        description="Web 执行器未写入 response_snapshot.web.steps。可能是执行超时或前置错误。"
      />
    );
  }
  return (
    <div style={{ overflowY: 'auto', flex: 1, paddingRight: 4, minHeight: 0 }}>
      <ExecutionTimeline steps={steps} totalSteps={totalSteps} selected={selectedStep} onSelect={onSelect} />
    </div>
  );
}

function DetailPanel({
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
