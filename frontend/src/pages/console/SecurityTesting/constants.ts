// 安全测试页面的选项与标签常量。
// 取值与后端 features/security_testing/schemas.py 的 Literal 严格对齐。
import type { CoverageCategory, SecurityExpectation, SecurityFindingStatus, SecurityResult, SecuritySeverity } from '@/features/security-testing/contracts';


/** 严重级别 / 风险级别：颜色按级别递进。 */
export const SEVERITY_OPTIONS: { value: SecuritySeverity; label: string; color: string }[] = [
  { value: 'INFO', label: '提示', color: 'default' },
  { value: 'LOW', label: '低', color: 'blue' },
  { value: 'MEDIUM', label: '中', color: 'orange' },
  { value: 'HIGH', label: '高', color: 'red' },
  { value: 'CRITICAL', label: '严重', color: 'volcano' },
];

export const severityLabel = (v: string) =>
  SEVERITY_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const severityColor = (v: string) =>
  SEVERITY_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

/** 安全结论五态：POTENTIAL_ISSUE 用红，其余按语义着色。 */
export const RESULT_OPTIONS: { value: SecurityResult; label: string; color: string }[] = [
  { value: 'PASS', label: '通过', color: 'green' },
  { value: 'POTENTIAL_ISSUE', label: '疑似问题', color: 'red' },
  { value: 'FAILED_EXECUTION', label: '执行失败', color: 'magenta' },
  { value: 'INCONCLUSIVE', label: '不确定', color: 'orange' },
  { value: 'SKIPPED', label: '已跳过', color: 'default' },
];

export const resultLabel = (v: string) =>
  RESULT_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const resultColor = (v: string) =>
  RESULT_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

/** Finding 状态：FALSE_POSITIVE 用蓝（误报已澄清），RESOLVED 用绿。 */
export const FINDING_STATUS_OPTIONS: {
  value: SecurityFindingStatus;
  label: string;
  color: string;
}[] = [
  { value: 'OPEN', label: '待处理', color: 'red' },
  { value: 'CONFIRMED', label: '已确认', color: 'volcano' },
  { value: 'FALSE_POSITIVE', label: '误报', color: 'blue' },
  { value: 'RESOLVED', label: '已修复', color: 'green' },
  { value: 'IGNORED', label: '已忽略', color: 'default' },
];

export const findingStatusLabel = (v: string) =>
  FINDING_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const findingStatusColor = (v: string) =>
  FINDING_STATUS_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

/**
 * Finding 状态合法迁移（与后端 FINDING_STATUS_TRANSITIONS 一致）。
 * 处置下拉只给这些目标——否则用户选一个后端 400 拒绝的迁移，只会收到错误 toast。
 */
export const FINDING_STATUS_TRANSITIONS: Record<SecurityFindingStatus, SecurityFindingStatus[]> = {
  OPEN: ['CONFIRMED', 'FALSE_POSITIVE', 'RESOLVED', 'IGNORED'],
  CONFIRMED: ['RESOLVED', 'FALSE_POSITIVE'],
  FALSE_POSITIVE: ['OPEN'],
  IGNORED: ['OPEN'],
  RESOLVED: ['OPEN'],
};

/** 安全期望。 */
export const EXPECTATION_OPTIONS: { value: SecurityExpectation; label: string }[] = [
  { value: 'EXPECTED_DENY', label: '应拒绝' },
  { value: 'EXPECTED_ALLOW', label: '应放行' },
  { value: 'EXPECTED_VALIDATION_ERROR', label: '应校验失败' },
  { value: 'EXPECTED_IDEMPOTENT', label: '应幂等' },
];

export const expectationLabel = (v: string) =>
  EXPECTATION_OPTIONS.find((o) => o.value === v)?.label ?? v;

/** 报告概览六类覆盖口径（与后端 COVERAGE_CATEGORIES 一致）。 */
export const COVERAGE_OPTIONS: { value: CoverageCategory; label: string }[] = [
  { value: 'AUTHENTICATION', label: '鉴权' },
  { value: 'AUTHORIZATION', label: '授权' },
  { value: 'IDOR', label: '越权访问' },
  { value: 'PARAMETER', label: '参数' },
  { value: 'REPLAY', label: '重放' },
  { value: 'BUSINESS', label: '业务' },
];

/**
 * 把后端策略 category 映射到六类覆盖口径。
 * 后端 14 个 category 中，前 10 个可执行 + 后 4 个预留；这里只归并到概览六类，
 * 未归并的（METHOD / DUPLICATE_SUBMIT 等）归到最接近的一类或显示原名。
 */
export function categoryToCoverage(category: string): CoverageCategory | null {
  const map: Record<string, CoverageCategory> = {
    AUTHENTICATION: 'AUTHENTICATION',
    AUTHORIZATION: 'AUTHORIZATION',
    IDOR: 'IDOR',
    PARAMETER: 'PARAMETER',
    HEADER: 'PARAMETER',
    METHOD: 'PARAMETER',
    REPLAY: 'REPLAY',
    DUPLICATE_SUBMIT: 'REPLAY',
    BUSINESS_STATE: 'BUSINESS',
    SEQUENCE_BYPASS: 'BUSINESS',
  };
  return map[category] ?? null;
}
