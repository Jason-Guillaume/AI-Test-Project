/** 对当前工作区中的显式选择去重；空集或已失效 ID 均不可提交。 */
export function explicitSelection(selectedIds: readonly number[], availableIds: readonly number[]): number[] | null;
/** 切换全选/取消全选，范围始终来自当前会话快照。 */
export function toggleAllSelection(selectedIds: readonly number[], availableIds: readonly number[]): number[];
