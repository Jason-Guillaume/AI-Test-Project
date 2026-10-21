// Web 用例的逐步执行时间线：左侧 30% 面板。
//
// 数据契约（来自 src/shared/webSnapshot.ts）：
// - 步骤状态只有 PASSED / FAILED / ERROR 三种，后端在首个失败步骤即 break；
// - 后端只在步骤被触碰时才写日志（playwright_executor.py:140），未执行到的步骤
//   没有任何字段——所以未执行行只能显示序号与「未执行」，不能假造名称或操作类型；
// - 未执行与「跳过」必须区分：后端没有 SKIPPED 步骤态；
// - 步骤的 value / timeout / wait_state 不入库，FILL/SELECT 的参数被 scrub 成 ***，
//   因此本组件只展示 locator 与 operation，不显示执行值。
//
// 失败时自动定位首个失败步骤：调用方通过 selected 与 onSelect 控制选中态，
// 本组件负责计算 firstFailedIndex 并作为初始选中值供默认渲染。
// selected 始终是 steps 数组下标；未执行占位行不可选中。

import { theme, Typography } from 'antd';
import { DownOutlined } from '@ant-design/icons';
import type { WebStepRecord } from '@/shared/webSnapshot';
import { firstFailedStep, unreachedStepIndexes } from '@/shared/webSnapshot';
import { WEB_STEP_STATUS_COLOR, WEB_STEP_STATUS_LABEL } from '@/shared/status';
import { fmtDuration } from '@/shared/format';
import { StatusBadge } from '@/components/StatusBadge';

/** 未执行步骤的中文标签；后端没有 SKIPPED 步骤态，必须与之区分。 */
const LABEL_UNREACHED = '未执行';

interface ExecutionTimelineProps {
  /** Web 执行快照里的逐步日志（已用 isWebStepEntry 过滤） */
  steps: WebStepRecord[];
  /** 用例配置的总步骤数，用于补出未执行占位行；null 表示未知 */
  totalSteps: number | null;
  /** 当前选中的步骤索引（steps 数组下标）；null 表示无选中 */
  selected: number | null;
  /** 选中回调 */
  onSelect: (index: number) => void;
}

/** 时间线一行：真实步骤或未执行占位。 */
interface TimelineRow {
  key: string;
  /** 真实步骤；占位行为 null */
  step: WebStepRecord | null;
  /** steps 数组下标；占位行为 null */
  stepIndex: number | null;
  /** 步骤号（展示用，与后端 step 字段一致） */
  stepNo: number;
  unreached: boolean;
}

/**
 * 逐步执行时间线。
 *
 * 每项显示序号、名称、操作类型、状态与耗时。失败步骤红边框高亮，
 * 未执行步骤以灰底占位行补出，两者都不会被折叠或隐藏。
 *
 * 只有 totalSteps 已知时才推断未执行：总数未知时无法区分「未执行」与
 * 「日志未收录该步」，强行推断会把日志缺口谎报成未执行。
 */
export function ExecutionTimeline({ steps, totalSteps, selected, onSelect }: ExecutionTimelineProps) {
  const { token } = theme.useToken();
  const firstFailed = firstFailedStep(steps);
  const firstFailedIndex = firstFailed ? steps.indexOf(firstFailed) : null;
  const unreachedSet = unreachedStepIndexes(steps, totalSteps);

  if (steps.length === 0) {
    return (
      <div style={{ padding: token.padding, color: token.colorTextTertiary, fontSize: token.fontSizeSM }}>
        无逐步记录
      </div>
    );
  }

  // 按步骤号建索引，用于把日志条目对回「用例第几步」。
  const stepNoOf = (s: WebStepRecord, fallback: number) =>
    typeof s.step === 'number' ? s.step : fallback;
  const byStepNo = new Map<number, WebStepRecord>();
  steps.forEach((s, i) => {
    const n = stepNoOf(s, i + 1);
    if (!byStepNo.has(n)) byStepNo.set(n, s);
  });
  const maxLogged = steps.reduce((mx, s, i) => Math.max(mx, stepNoOf(s, i + 1)), 0);

  // totalSteps 已知时以步骤号为骨架补齐占位行；未知时按日志顺序渲染，不推断。
  const knownTotal = typeof totalSteps === 'number' && totalSteps > 0;
  const upper = knownTotal ? Math.max(totalSteps as number, maxLogged) : maxLogged;

  const rows: TimelineRow[] = knownTotal
    ? Array.from({ length: upper }, (_, i) => {
        const stepNo = i + 1;
        const step = byStepNo.get(stepNo) ?? null;
        return {
          key: step ? `s${stepNo}` : `u${stepNo}`,
          step,
          stepIndex: step ? steps.indexOf(step) : null,
          stepNo,
          unreached: unreachedSet.has(stepNo),
        };
      })
    : steps.map((step, index) => ({
        key: `s${index}`,
        step,
        stepIndex: index,
        stepNo: stepNoOf(step, index + 1),
        unreached: false,
      }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: token.marginXS }}>
      {rows.map((row) => (
        <TimelineItem
          key={row.key}
          step={row.step}
          stepNo={row.stepNo}
          isFailed={row.step != null && !!row.step.status && row.step.status !== 'PASSED'}
          isUnreached={row.unreached}
          isSelected={row.stepIndex != null && selected === row.stepIndex}
          isFirstFailed={row.stepIndex != null && firstFailedIndex === row.stepIndex}
          onClick={row.stepIndex != null ? () => onSelect(row.stepIndex as number) : undefined}
        />
      ))}
    </div>
  );
}

interface TimelineItemProps {
  step: WebStepRecord | null;
  stepNo: number;
  isFailed: boolean;
  isUnreached: boolean;
  isSelected: boolean;
  isFirstFailed: boolean;
  /** 未执行占位行为 undefined，此时该行不可交互 */
  onClick?: () => void;
}

function TimelineItem({ step, stepNo, isFailed, isUnreached, isSelected, isFirstFailed, onClick }: TimelineItemProps) {
  const { token } = theme.useToken();
  const operation = typeof step?.operation === 'string' ? step.operation : '-';
  const duration = step != null && !isUnreached ? fmtDuration(step.duration_ms) : '-';

  // 左侧色条：失败红色、选中主色、默认边框色，把「定位哪个」与「谁失败」一次看出。
  const borderLeftColor = isFailed
    ? token.colorError
    : isSelected
      ? token.colorPrimary
      : token.colorBorderSecondary;
  const bg = isFailed
    ? token.colorErrorBg
    : isSelected
      ? token.colorPrimaryBg
      : token.colorBgContainer;

  // 名称：优先取 name，其次取 operation，都缺就退回操作名占位。
  const name = typeof step?.name === 'string' && step.name.length > 0 ? step.name : null;

  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : -1}
      onClick={onClick}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onClick();
        }
      }}
      aria-label={`步骤 ${stepNo}${isFailed ? '（失败）' : ''}${isUnreached ? `（${LABEL_UNREACHED}）` : ''}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: token.marginXS,
        padding: `${token.marginXS}px ${token.paddingXS}px`,
        borderRadius: token.borderRadiusSM,
        cursor: onClick ? 'pointer' : 'default',
        borderLeft: `3px solid ${borderLeftColor}`,
        background: bg,
        opacity: isUnreached ? 0.55 : 1,
        transition: 'background 0.15s',
      }}
    >
      {/* 序号 */}
      <span
        style={{
          flexShrink: 0,
          minWidth: 24,
          height: 24,
          borderRadius: '50%',
          background: isFailed ? token.colorError : isSelected ? token.colorPrimary : token.colorFillTertiary,
          color: isFailed || isSelected ? token.colorWhite : token.colorTextSecondary,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: token.fontSizeSM,
          fontWeight: token.fontWeightStrong,
          lineHeight: 1,
        }}
      >
        {stepNo}
      </span>

      {/* 主内容：名称 + 操作标签 */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {name ? (
          <Typography.Text
            ellipsis
            style={{
              fontSize: token.fontSize,
              color: isUnreached ? token.colorTextTertiary : token.colorText,
              lineHeight: 1.3,
            }}
          >
            {name}
          </Typography.Text>
        ) : null}
        <span
          style={{
            fontSize: token.fontSizeSM,
            color: token.colorTextTertiary,
            fontFamily: token.fontFamilyCode,
            lineHeight: 1.3,
          }}
        >
          {operation}
        </span>
      </div>

      {/* 状态徽标 */}
      <StatusBadge
        value={isUnreached ? undefined : step?.status}
        colors={WEB_STEP_STATUS_COLOR}
        labels={WEB_STEP_STATUS_LABEL}
        nullRender={<span style={{ color: token.colorTextTertiary }}>{LABEL_UNREACHED}</span>}
      />

      {/* 耗时 */}
      <span
        style={{
          fontSize: token.fontSizeSM,
          color: token.colorTextSecondary,
          minWidth: 56,
          textAlign: 'right',
          fontFamily: token.fontFamilyCode,
        }}
      >
        {duration}
      </span>

      {/* 折叠指示：首行或选中行显示 */}
      {(isSelected || isFirstFailed) && (
        <DownOutlined style={{ fontSize: 10, color: token.colorTextTertiary }} />
      )}
    </div>
  );
}
