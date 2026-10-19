// Mock Management 页面的选项与标签常量。
// 取值与后端 features/mock_management/schemas.py 的 Literal 严格对齐。
import type {
  MockBehaviorType,
  MockMatcherOperator,
  MockMatcherSource,
  MockScope,
} from '@/types';

/** 行为类型：决定依赖服务在本次调用中如何表现。 */
export const BEHAVIOR_OPTIONS: { value: MockBehaviorType; label: string; color: string }[] = [
  { value: 'STATIC_RESPONSE', label: '正常返回', color: 'green' },
  { value: 'EMPTY_RESPONSE', label: '空数据', color: 'orange' },
  { value: 'DELAY_RESPONSE', label: '延迟返回', color: 'gold' },
  { value: 'TIMEOUT', label: '超时 / 504', color: 'red' },
];

export const behaviorLabel = (v: string) =>
  BEHAVIOR_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const behaviorColor = (v: string) =>
  BEHAVIOR_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

/** 匹配规则来源。 */
export const MATCHER_SOURCE_OPTIONS: { value: MockMatcherSource; label: string }[] = [
  { value: 'METHOD', label: 'HTTP 方法' },
  { value: 'PATH', label: '路径 / 路径参数' },
  { value: 'QUERY', label: '查询参数' },
  { value: 'HEADER', label: '请求头' },
  { value: 'BODY', label: '请求体' },
];

/** 匹配规则操作符。needValue=false 表示无期望值（存在性判断）。 */
export const MATCHER_OPERATOR_OPTIONS: {
  value: MockMatcherOperator;
  label: string;
  needValue: boolean;
}[] = [
  { value: 'EQ', label: '等于', needValue: true },
  { value: 'NE', label: '不等于', needValue: true },
  { value: 'EXISTS', label: '存在', needValue: false },
  { value: 'NOT_EXISTS', label: '不存在', needValue: false },
  { value: 'CONTAINS', label: '包含', needValue: true },
  { value: 'IN', label: '属于集合', needValue: true },
  { value: 'JSON_PATH_EQ', label: 'JSONPath 等于', needValue: true },
  { value: 'JSON_PATH_EXISTS', label: 'JSONPath 存在', needValue: false },
];

export const operatorNeedValue = (v: string) =>
  MATCHER_OPERATOR_OPTIONS.find((o) => o.value === v)?.needValue ?? true;

/** 用例 required_mocks 作用域。 */
export const MOCK_SCOPE_OPTIONS: { value: MockScope; label: string }[] = [
  { value: 'SETUP', label: 'SETUP 阶段' },
  { value: 'EXECUTION', label: 'EXECUTION 阶段' },
  { value: 'BOTH', label: '全程' },
];

/** API Catalog 一键创建时的推荐场景模板。 */
export const API_MOCK_TEMPLATES: { value: string; label: string }[] = [
  { value: 'NORMAL', label: '正常返回（200）' },
  { value: 'BAD_REQUEST_400', label: '参数错误（400）' },
  { value: 'UNAUTHORIZED_401', label: '未授权（401）' },
  { value: 'FORBIDDEN_403', label: '禁止访问（403）' },
  { value: 'NOT_FOUND_404', label: '资源不存在（404）' },
  { value: 'SERVER_ERROR_500', label: '服务端错误（500）' },
  { value: 'EMPTY_DATA', label: '空数据' },
  { value: 'DELAY', label: '延迟响应' },
  { value: 'TIMEOUT', label: '超时（504）' },
];

/** 支持 Mock 的 HTTP 方法。 */
export const HTTP_METHOD_OPTIONS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map(
  (m) => ({ value: m, label: m }),
);

/** 服务键 / 场景键规则：首字母大写 + 字母数字下划线。 */
export const MOCK_KEY_PATTERN = /^[A-Z][A-Z0-9_]{0,99}$/;

/** 响应状态码的展示色：2xx 绿、3xx 蓝、4xx 橙、5xx 红。 */
export function statusCodeColor(code: number | null): string {
  if (code == null) return 'default';
  if (code < 300) return 'green';
  if (code < 400) return 'blue';
  if (code < 500) return 'orange';
  return 'red';
}

/** 把任意 JSON 值压成稳定可读的字符串，用于快照展示。 */
export function fmtJson(v: unknown): string {
  if (v === null || v === undefined) return '-';
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}
