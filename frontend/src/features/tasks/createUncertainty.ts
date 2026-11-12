const STORAGE_KEY = 'task-create-uncertain-v1';

export interface TaskCreateUncertainty {
  kind: 'task' | 'verification' | 'defect';
  project_id: number;
  request_key: string;
  recorded_at: number;
}

export function rememberTaskCreateUncertainty(value: TaskCreateUncertainty): void {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch { /* storage is optional */ }
}

export function readTaskCreateUncertainty(): TaskCreateUncertainty | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null');
    if (typeof value !== 'object' || value === null) return null;
    const item = value as Partial<TaskCreateUncertainty>;
    return Number.isInteger(item.project_id) && Number(item.project_id) > 0
      && (item.kind === 'task' || item.kind === 'verification' || item.kind === 'defect')
      && typeof item.request_key === 'string' && item.request_key.length > 0
      && typeof item.recorded_at === 'number'
      ? item as TaskCreateUncertainty
      : null;
  } catch { return null; }
}

export function clearTaskCreateUncertainty(requestKey: string): void {
  try {
    if (readTaskCreateUncertainty()?.request_key === requestKey) sessionStorage.removeItem(STORAGE_KEY);
  } catch { /* storage is optional */ }
}
