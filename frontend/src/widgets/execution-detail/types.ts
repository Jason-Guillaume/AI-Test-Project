// 用例执行详情组件共享的接口定义。
//
// 背景：报告页拿到的是 CaseExecutionSummary，测试执行页拿到的是 CaseExecution；
// 两者在 response_snapshot / assertion_results 上完全同型，只是字段口径不同
// （报告页多出 case_name/priority/case_type/failure_type 供展示，测试执行页
// 多出 test_run_id/executor_type 供导航）。
//
// 本文件定义组件间的最小公共接口，避免详情组件反过来 import 两个业务类型
// 造成耦合，也让调用方可以自由地传其中任一种。

/**
 * 用例执行条目的公共结构。
 *
 * 同时兼容 `CaseExecution` 与 `CaseExecutionSummary`。
 *
 * 注意 response_snapshot / assertion_results 都是 `Record<string, unknown>`：
 * 只有 Web 执行器（playwright_executor.py）才会在 response_snapshot.web 下写逐步
 * 日志与附件清单，因此组件必须通过 `readWebSnapshot()` 收窄，不能自行断言结构。
 */
export interface CaseExecutionLike {
  /** 用例执行 ID */
  id: number;
  /** 后端字面量：PENDING / RUNNING / PASSED / FAILED / SKIPPED / ERROR */
  status: string;
  /** 执行器类型：API / WEB / BUSINESS_FLOW / BUSINESS_ACTION */
  executor_type: string | null;
  /** 请求快照。API 用例存真实 HTTP 请求；WEB 用例只有 { step_count: N } */
  request_snapshot: Record<string, unknown> | null;
  /** 响应快照。Web 执行器把 steps / artifacts 写在 response_snapshot.web 下 */
  response_snapshot: Record<string, unknown> | null;
  /** 断言结果；每项含 path / operator / expected / actual / passed */
  assertion_results: Array<Record<string, unknown>> | null;
  /** 运行时上下文 */
  context_json: Record<string, unknown> | null;
  /** 开始时间（ISO 8601） */
  started_at: string | null;
  /** 结束时间（ISO 8601） */
  finished_at: string | null;
  /** 总耗时，毫秒 */
  duration_ms: number | null;
  /** 失败错误码 */
  error_code: string | null;
  /** 失败错误信息（中文定位） */
  error_message: string | null;
  /** 关联用例 ID；业务流驱动的执行可能为空 */
  test_case_id: number | null;
  // ---- 报告页扩展字段：CaseExecutionSummary 独有 ----
  /** 用例名称 */
  case_name?: string;
  /** 用例优先级 */
  priority?: string;
  /** 用例类型 */
  case_type?: string | null;
  /** 失败分类 */
  failure_type?: string | null;
}
