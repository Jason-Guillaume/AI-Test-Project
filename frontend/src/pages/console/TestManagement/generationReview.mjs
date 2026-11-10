// 生成审核工作台的纯逻辑：可被 node --test 直接验证，不依赖 React。
// 约定与 agentHierarchy.mjs 一致：同源 .d.mts 提供类型。

/** 待审核草稿数。 */
export function pendingCount(drafts) {
  return (drafts ?? []).filter((draft) => draft.status === 'PENDING').length;
}

/** 有待审核草稿的模块名（去重，保持出现顺序）。 */
export function pendingModules(drafts) {
  const seen = new Set();
  for (const draft of drafts ?? []) {
    if (draft.status === 'PENDING') seen.add(draft.module);
  }
  return Array.from(seen);
}

/** 是否存在失败的生成模块（SKIPPED 不算失败，不可再生成）。 */
export function hasFailedModule(moduleErrors) {
  return (moduleErrors ?? []).some((item) => item.status === 'FAILED');
}

/** 构造批量审核请求体；confirm 恒为 true（调用方必须先经二次确认）。 */
export function buildReviewBody({ action, scope, module, comment }) {
  if (action !== 'accept' && action !== 'reject') throw new Error('非法批量审核动作');
  if (scope === 'module' && !module) throw new Error('按模块批量审核必须指定 module');
  const body = { action, scope, confirm: true };
  if (scope === 'module') body.module = module;
  if (comment) body.comment = comment;
  return body;
}

/** 质量标记按级别计数：{ error, warning, info }。 */
export function summarizeQuality(quality) {
  const summary = { error: 0, warning: 0, info: 0 };
  for (const issue of quality ?? []) {
    if (issue.level in summary) summary[issue.level] += 1;
  }
  return summary;
}

/** 单条模块指标展示文本：「api · SUCCEEDED · 1.2s · prompt_tokens=10」。 */
export function formatMetric(item) {
  const seconds = item?.duration_ms != null ? `${(item.duration_ms / 1000).toFixed(1)}s` : '-';
  const usage = item?.usage && Object.keys(item.usage).length
    ? Object.entries(item.usage).map(([key, value]) => `${key}=${value}`).join(' ')
    : 'token 未上报';
  return `${item?.module ?? '模块'} · ${item?.status ?? '-'} · ${seconds} · ${usage}`;
}
