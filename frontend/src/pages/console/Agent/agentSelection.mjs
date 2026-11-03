/** 对当前工作区中的显式选择去重；空集或已失效 ID 均不可提交。 */
export function explicitSelection(selectedIds, availableIds) {
  if (!selectedIds.length) return null;
  const allowed = new Set(availableIds);
  if (selectedIds.some((id) => !allowed.has(id))) return null;
  return [...new Set(selectedIds)];
}

/** 切换全选/取消全选，范围始终来自当前会话快照。 */
export function toggleAllSelection(selectedIds, availableIds) {
  if (!availableIds.length) return [];
  const selected = new Set(selectedIds);
  const allSelected = availableIds.every((id) => selected.has(id));
  return allSelected ? [] : [...availableIds];
}
