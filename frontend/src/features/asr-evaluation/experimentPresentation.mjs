const EXPERIMENT_STATUS_LABELS = {
  DRAFT: '待复跑', PENDING: '等待提交', QUEUED: '排队中', SUBMITTING: '提交中',
  RUNNING: '复跑中', REMOTE_RUNNING: '远端处理中', SUCCEEDED: '已完成', COMPLETED: '已完成',
  PARTIAL_FAILED: '部分失败', FAILED: '失败', CANCELLED: '已取消',
  RECONCILIATION_REQUIRED: '状态待核实',
};

export function experimentStatusLabel(status) {
  return EXPERIMENT_STATUS_LABELS[status] ?? status;
}

export function parameterDiffs(baseline, candidate, prefix = '') {
  const before = baseline ?? {};
  const keys = new Set([...Object.keys(before), ...Object.keys(candidate)]);
  return [...keys].sort().flatMap((key) => {
    const path = `${prefix}/${key}`;
    const oldValue = before[key];
    const newValue = candidate[key];
    const isObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
    if (isObject(oldValue) && isObject(newValue)) return parameterDiffs(oldValue, newValue, path);
    return JSON.stringify(oldValue) === JSON.stringify(newValue)
      ? [] : [{ path, baseline: oldValue, candidate: newValue }];
  });
}

export function parameterChangeSummary(baseline, candidate) {
  if (baseline == null) return '缺少基线快照';
  const changes = parameterDiffs(baseline, candidate);
  return changes.length
    ? `${changes.length} 项 · ${changes.slice(0, 2).map((item) => item.path).join('、')}`
    : '无参数差异';
}
