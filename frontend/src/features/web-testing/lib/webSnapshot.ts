// Web 用例执行快照的安全读取层。
//
// 背景：CaseExecution / CaseExecutionSummary 的 response_snapshot 类型是
// Record<string, unknown>，而只有 WebExecution.response_snapshot 被显式收窄成
// { web?: { steps?, artifacts? } }。Web 执行器（playwright_executor.py）把逐步执行
// 日志写进 response_snapshot.web.steps，把附件清单写进 response_snapshot.web.artifacts。
//
// 这里提供唯一的收窄入口，避免各页面各自手写类型断言。
//
// 安全边界（来自后端，前端不得突破）：
// - 逐步 value / expected 不入库，FILL/SELECT 的参数被 scrub 成 ***；
// - Playwright trace 的 frame-snapshot / screencast-frame / resource-snapshot 被丢弃，
//   因此 Trace 只能做动作时序，不能做 DOM 回放；
// - 截图 content 加密落库，GET /web-artifacts/{id} 强制 Content-Disposition: attachment，
//   所以 artifacts 里的 url 不能直接当 <img src>，必须走 webUIApi.artifact(id) 取 blob。

/**
 * Playwright 定位器。
 *
 * 与后端 Locator（schemas.py）的 model_dump 结果对齐；name 可空（TEST_ID / CSS 等
 * 没有可访问名称的定位器），exact 为严格匹配标记。
 */
export interface WebLocator {
  strategy?: string;
  value?: string;
  name?: string | null;
  exact?: boolean;
}

/**
 * 定位器的紧凑展示形态。
 *
 * 用 `[ROLE] button "登录"` 而不是裸 JSON：更易读，也不泄露执行值，
 * 不触碰脱敏红线。无法识别形态时回退到 JSON 字符串，保证不丢信息。
 */
export function formatLocator(locator: WebStepRecord['locator']): string | null {
  if (locator == null) return null;
  if (typeof locator === 'string') return locator || null;
  const { strategy, value, name, exact } = locator;
  if (!strategy && !value) return null;
  const head = value ?? '';
  const suffix = name ? ` "${name}"` : '';
  return `[${strategy ?? 'UNKNOWN'}]${exact ? ' exact' : ''} ${head}${suffix}`.trim();
}

/** Web 执行记录里的逐步日志条目。字段名与后端 safe_trace 输出对齐。 */
export interface WebStepRecord {
  /** 步骤序号，从 1 开始 */
  step?: number;
  /** 步骤名称 */
  name?: string;
  /** 操作类型：GOTO / CLICK / FILL / SELECT / ASSERT 等 */
  operation?: string;
  /**
   * 定位器信息。
   *
   * 后端写的是 Locator.model_dump() 的对象（playwright_executor.py:140），
   * 不是字符串——用 typeof === 'string' 判空会恒为 false，导致定位器整行不渲染。
   * NAVIGATE / URL / TITLE 断言等无定位器的步骤为 null。
   * 注意：脱敏的是 FILL/SELECT 的参数值，不是定位器本身。
   */
  locator?: WebLocator | string | null;
  /** 步骤状态：仅 PASSED / FAILED / ERROR 三种 */
  status?: string;
  /** 步骤耗时，毫秒 */
  duration_ms?: number;
  /** 断言类型：TEXT / VALUE / VISIBLE / COUNT / URL / TITLE */
  assertion?: string;
  /** 执行参数（value 等敏感值已被 scrub 成 ***） */
  params?: Record<string, unknown>;
  /** 非步骤的事件条目标记（如「截图未采集」），与 step 互斥 */
  event?: string;
  /** 其它透传字段 */
  [key: string]: unknown;
}

/** Web 附件引用：附件清单的唯一来源。 */
export interface WebArtifactRef {
  /** 不透明附件 ID，下载与 Trace 事件都靠它 */
  id: string;
  /** SCREENSHOT / FAILURE_SCREENSHOT / TRACE */
  kind: string;
  /** 受 JWT 保护的下载地址；仅展示用，不可作为 img src */
  url: string;
}

/** 收窄后的 Web 执行快照。 */
export interface WebExecutionSnapshot {
  steps?: WebStepRecord[];
  artifacts?: WebArtifactRef[];
}

/**
 * 从 response_snapshot 安全读取 Web 执行快照。
 *
 * 结构不符或字段缺失时返回 null，调用方按空态处理，不抛错。
 */
export function readWebSnapshot(
  snapshot: Record<string, unknown> | null | undefined,
): WebExecutionSnapshot | null {
  if (!snapshot || typeof snapshot !== 'object') return null;
  const web = snapshot.web;
  if (!web || typeof web !== 'object') return null;
  const w = web as Record<string, unknown>;

  const steps = Array.isArray(w.steps)
    ? w.steps.filter((s): s is WebStepRecord => !!s && typeof s === 'object')
    : undefined;
  const artifacts = Array.isArray(w.artifacts)
    ? w.artifacts.filter(
        (a): a is WebArtifactRef =>
          !!a && typeof a === 'object' && typeof (a as Record<string, unknown>).id === 'string',
      )
    : undefined;

  if (!steps && !artifacts) return null;
  return { steps, artifacts };
}

/**
 * 判断一条日志是否真正的步骤记录。
 *
 * 后端在截图未采集等情况会写入 {"event": "...", "status": "ERROR"} 这类事件条目，
 * 它们没有 step 序号，不能混进步骤时间线。
 */
export function isWebStepEntry(entry: WebStepRecord): boolean {
  return typeof entry.step === 'number' || typeof entry.operation === 'string';
}

/**
 * 取首个失败步骤：最后一条非 PASSED 的步骤。
 *
 * 后端在首个失败步骤即 break（playwright_executor.py:152），所以日志里最后一条
 * 非 PASSED 条目就是失败点，无需向前搜索猜测。
 */
export function firstFailedStep(steps: WebStepRecord[]): WebStepRecord | null {
  const filtered = steps.filter(isWebStepEntry);
  for (let i = filtered.length - 1; i >= 0; i--) {
    const s = filtered[i];
    if (s.status && s.status !== 'PASSED') return s;
  }
  return null;
}

/**
 * 取未执行的步骤序号集合。
 *
 * 后端没有 SKIPPED / PENDING 步骤态：未出现在日志里的步骤表示未执行
 * （超时或前序失败 break），必须与「跳过」区分开。
 */
export function unreachedStepIndexes(steps: WebStepRecord[], totalSteps: number | null): Set<number> {
  const reached = new Set(steps.filter(isWebStepEntry).map((s) => s.step));
  const result = new Set<number>();
  if (totalSteps == null) return result;
  for (let i = 1; i <= totalSteps; i++) {
    if (!reached.has(i)) result.add(i);
  }
  return result;
}
