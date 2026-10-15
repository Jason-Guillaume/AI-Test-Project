// 测试管理页常量：下拉选项与文案标签，与后端 test_management 枚举字面量严格对齐。
// 仅放纯静态选项，不放业务逻辑。§27：source_type 预留 AI，当前仅 MANUAL（不在此暴露 AI 选项）。

import type {
  CaseExecutionStatus,
  TestCaseType,
  TestAssertionType,
  TestDataSourceType,
  TestExecutionMode,
  TestOperator,
  TestPlanStatus,
  TestPreconditionType,
  TestPriority,
  TestRunStatus,
  TestStatus,
  TestStepType,
  TestStrategyCategory,
  TestSuiteType,
  TestTargetType,
  TestValueType,
} from '@/types';

export const TEST_STRATEGY_CATEGORY_OPTIONS = [
  { value: 'FUNCTIONAL' as TestStrategyCategory, label: '功能测试 FUNCTIONAL' },
  { value: 'PARAMETER' as TestStrategyCategory, label: '参数测试 PARAMETER' },
  { value: 'BOUNDARY' as TestStrategyCategory, label: '边界测试 BOUNDARY' },
  { value: 'AUTH' as TestStrategyCategory, label: '鉴权测试 AUTH' },
  { value: 'PERMISSION' as TestStrategyCategory, label: '权限测试 PERMISSION' },
  { value: 'BUSINESS' as TestStrategyCategory, label: '业务测试 BUSINESS' },
  { value: 'EXCEPTION' as TestStrategyCategory, label: '异常测试 EXCEPTION' },
  { value: 'IDEMPOTENCY' as TestStrategyCategory, label: '幂等测试 IDEMPOTENCY' },
  { value: 'SECURITY' as TestStrategyCategory, label: '安全测试 SECURITY' },
  { value: 'DATA_CONSISTENCY' as TestStrategyCategory, label: '数据一致性 DATA_CONSISTENCY' },
];

export const TEST_PRIORITY_OPTIONS = [
  { value: 'P0' as TestPriority, label: 'P0 冒烟阻塞' },
  { value: 'P1' as TestPriority, label: 'P1 主流程' },
  { value: 'P2' as TestPriority, label: 'P2 分支' },
  { value: 'P3' as TestPriority, label: 'P3 低频' },
];

export const TEST_TARGET_TYPE_OPTIONS = [
  { value: 'API' as TestTargetType, label: '接口 API' },
  { value: 'BUSINESS_FLOW' as TestTargetType, label: '业务流程 BUSINESS_FLOW' },
  { value: 'BUSINESS_ACTION' as TestTargetType, label: '业务动作 BUSINESS_ACTION' },
];

export const TEST_STATUS_OPTIONS = [
  { value: 'DRAFT' as TestStatus, label: '草稿 DRAFT' },
  { value: 'ACTIVE' as TestStatus, label: '生效 ACTIVE' },
  { value: 'DEPRECATED' as TestStatus, label: '已废弃 DEPRECATED' },
];

export const TEST_CASE_TYPE_OPTIONS = [
  { value: 'FUNCTIONAL' as TestCaseType, label: '功能用例 FUNCTIONAL' },
  { value: 'BUSINESS' as TestCaseType, label: '业务用例 BUSINESS' },
  { value: 'NEGATIVE' as TestCaseType, label: '异常用例 NEGATIVE' },
  { value: 'BOUNDARY' as TestCaseType, label: '边界用例 BOUNDARY' },
  { value: 'PERMISSION' as TestCaseType, label: '权限用例 PERMISSION' },
  { value: 'SECURITY' as TestCaseType, label: '安全用例 SECURITY' },
  { value: 'EXCEPTION' as TestCaseType, label: '异常用例 EXCEPTION' },
];

export const TEST_PRECONDITION_TYPE_OPTIONS = [
  { value: 'VARIABLE' as TestPreconditionType, label: '变量 VARIABLE' },
  { value: 'TEXT' as TestPreconditionType, label: '文本说明 TEXT' },
  { value: 'FIXTURE' as TestPreconditionType, label: '夹具 FIXTURE' },
  { value: 'API' as TestPreconditionType, label: '接口 API' },
  { value: 'BUSINESS_ACTION' as TestPreconditionType, label: '业务动作 BUSINESS_ACTION' },
  { value: 'BUSINESS_FLOW' as TestPreconditionType, label: '业务流程 BUSINESS_FLOW' },
];

export const TEST_OPERATOR_OPTIONS = [
  { value: 'EQ' as TestOperator, label: '等于 EQ' },
  { value: 'NE' as TestOperator, label: '不等于 NE' },
  { value: 'GT' as TestOperator, label: '大于 GT' },
  { value: 'GE' as TestOperator, label: '大于等于 GE' },
  { value: 'LT' as TestOperator, label: '小于 LT' },
  { value: 'LE' as TestOperator, label: '小于等于 LE' },
  { value: 'IN' as TestOperator, label: '属于 IN' },
  { value: 'CONTAINS' as TestOperator, label: '包含 CONTAINS' },
  { value: 'EXISTS' as TestOperator, label: '存在 EXISTS' },
  { value: 'NOT_EXISTS' as TestOperator, label: '不存在 NOT_EXISTS' },
];

export const TEST_VALUE_TYPE_OPTIONS = [
  { value: 'STRING' as TestValueType, label: '字符串 STRING' },
  { value: 'INTEGER' as TestValueType, label: '整数 INTEGER' },
  { value: 'NUMBER' as TestValueType, label: '数字 NUMBER' },
  { value: 'BOOLEAN' as TestValueType, label: '布尔 BOOLEAN' },
  { value: 'OBJECT' as TestValueType, label: '对象 OBJECT' },
  { value: 'ARRAY' as TestValueType, label: '数组 ARRAY' },
];

export const TEST_DATA_SOURCE_OPTIONS = [
  { value: 'STATIC' as TestDataSourceType, label: '静态 STATIC' },
  { value: 'ENVIRONMENT' as TestDataSourceType, label: '环境变量 ENVIRONMENT' },
  { value: 'VARIABLE' as TestDataSourceType, label: '上下文变量 VARIABLE' },
  { value: 'RUNTIME' as TestDataSourceType, label: '运行时 RUNTIME' },
  { value: 'FAKER' as TestDataSourceType, label: '伪造 FAKER' },
  { value: 'FIXTURE' as TestDataSourceType, label: '夹具 FIXTURE' },
];

// FAKER 生成器白名单：与后端 variable_resolver.FAKER_GENERATORS 严格对齐（不开放任意方法名）。
export const TEST_FAKER_GENERATOR_OPTIONS = [
  { value: 'uuid', label: 'UUID' },
  { value: 'name', label: '姓名 name' },
  { value: 'phone', label: '手机号 phone' },
  { value: 'email', label: '邮箱 email' },
  { value: 'string', label: '随机串 string' },
  { value: 'integer', label: '整数 integer' },
  { value: 'timestamp', label: '时间戳 timestamp' },
  { value: 'date', label: '日期 date' },
  { value: 'url', label: 'URL url' },
  { value: 'ip', label: 'IP ip' },
  { value: 'random_choice', label: '候选随机 random_choice（需候选值）' },
  { value: 'project_name', label: '项目名 project_name' },
];

export const TEST_FAKER_LOCALE_OPTIONS = [
  { value: 'zh_CN', label: '中文 zh_CN' },
  { value: 'en_US', label: '英文 en_US' },
];

export const TEST_STEP_TYPE_OPTIONS = [
  { value: 'SETUP' as TestStepType, label: '前置 SETUP' },
  { value: 'ACTION' as TestStepType, label: '动作 ACTION' },
  { value: 'ASSERT' as TestStepType, label: '断言 ASSERT' },
  { value: 'CLEANUP' as TestStepType, label: '清理 CLEANUP' },
];

export const TEST_ASSERTION_TYPE_OPTIONS = [
  { value: 'STATUS_CODE' as TestAssertionType, label: '状态码 STATUS_CODE' },
  { value: 'JSON_PATH' as TestAssertionType, label: 'JSONPath JSON_PATH' },
  { value: 'HEADER' as TestAssertionType, label: '响应头 HEADER' },
  { value: 'RESPONSE_TIME' as TestAssertionType, label: '响应时间 RESPONSE_TIME' },
  { value: 'CONTAINS' as TestAssertionType, label: '包含 CONTAINS' },
  { value: 'NOT_CONTAINS' as TestAssertionType, label: '不包含 NOT_CONTAINS' },
];

export const TEST_SUITE_TYPE_OPTIONS = [
  { value: 'SMOKE' as TestSuiteType, label: '冒烟 SMOKE' },
  { value: 'REGRESSION' as TestSuiteType, label: '回归 REGRESSION' },
  { value: 'BUSINESS' as TestSuiteType, label: '业务 BUSINESS' },
  { value: 'CUSTOM' as TestSuiteType, label: '自定义 CUSTOM' },
];

export const TEST_PLAN_STATUS_OPTIONS = [
  { value: 'DRAFT' as TestPlanStatus, label: '草稿 DRAFT' },
  { value: 'ACTIVE' as TestPlanStatus, label: '生效 ACTIVE' },
  { value: 'DISABLED' as TestPlanStatus, label: '停用 DISABLED' },
];

export const TEST_EXECUTION_MODE_OPTIONS = [
  { value: 'MANUAL' as TestExecutionMode, label: '手动 MANUAL' },
  { value: 'SCHEDULED' as TestExecutionMode, label: '定时 SCHEDULED' },
  { value: 'CI' as TestExecutionMode, label: 'CI 流水线 CI' },
];

export const TEST_RUN_STATUS_OPTIONS = [
  { value: 'PENDING' as TestRunStatus, label: '等待 PENDING' },
  { value: 'RUNNING' as TestRunStatus, label: '执行中 RUNNING' },
  { value: 'SUCCESS' as TestRunStatus, label: '成功 SUCCESS' },
  { value: 'FAILED' as TestRunStatus, label: '失败 FAILED' },
  { value: 'CANCELLED' as TestRunStatus, label: '取消 CANCELLED' },
];

export const CASE_EXECUTION_STATUS_OPTIONS = [
  { value: 'PENDING' as CaseExecutionStatus, label: '等待 PENDING' },
  { value: 'RUNNING' as CaseExecutionStatus, label: '执行中 RUNNING' },
  { value: 'PASSED' as CaseExecutionStatus, label: '通过 PASSED' },
  { value: 'FAILED' as CaseExecutionStatus, label: '失败 FAILED' },
  { value: 'SKIPPED' as CaseExecutionStatus, label: '跳过 SKIPPED' },
  { value: 'ERROR' as CaseExecutionStatus, label: '错误 ERROR' },
];

// 通用：用例/套件/计划启用开关。
export const ENABLED_OPTIONS = [
  { value: true, label: '启用' },
  { value: false, label: '停用' },
];
