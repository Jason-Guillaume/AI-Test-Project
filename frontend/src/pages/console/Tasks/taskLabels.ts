/**
 * 统一任务页共用的状态文案。
 * 导出任务、阶段、事件、角色与工具状态映射，供列表和详情页协作使用；未知状态由调用方回退显示原值。
 */
export const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中', RUNNING: '运行中', WAITING_CONFIRMATION: '待确认',
  READY: '就绪', WAITING_APPROVAL: '待确认', WAITING_DEPENDENCY: '等待前置节点',
  PAUSE_REQUESTED: '暂停中', PAUSED: '已暂停', CANCEL_REQUESTED: '取消中',
  WAITING_EXTERNAL: '等待外部处理',
  SUCCEEDED: '已完成', SUCCEEDED_WITH_ISSUES: '完成但有问题', FAILED: '失败',
  CANCELLED: '已取消', SUPERSEDED: '已被新目标替代', RECONCILIATION_REQUIRED: '待核对',
};

export const STAGE_LABEL: Record<string, string> = {
  MODEL_RETRY: '模型重试中', WAITING_MODEL: '等待修复模型配置',
  SECURITY_EXECUTION: '安全变异执行中',
};

export const EVENT_LABEL: Record<string, string> = {
  'llm.primary_succeeded': '主模型调用成功',
  'llm.fallback_succeeded': '备用模型接手成功',
  'llm.retry_scheduled': '模型路由失败，已安排自动重试',
  'llm.fallback_exhausted': '模型路由耗尽，任务等待配置修复',
};

export const ROLE_LABEL: Record<string, string> = {
  MAIN: '任务主 Agent', PLANNER: 'Planner', API_WORKER: 'API Worker',
  UI_WORKER: 'UI Worker', SECURITY_WORKER: '安全 Worker', REVIEWER: '审阅 Agent',
  REPORT_AGENT: '报告 Agent', SUB_AGENT: '子 Agent',
};

export const TOOL_CALL_STATUS: Record<string, string> = {
  STARTED: '调用中', SUCCEEDED: '成功', FAILED: '失败', CANCELLED: '未调用', NEEDS_RECONCILIATION: '待核对',
};

export const TERMINAL = new Set(['SUCCEEDED', 'SUCCEEDED_WITH_ISSUES', 'FAILED', 'CANCELLED', 'SUPERSEDED']);
export const STOP_POLLING = new Set([...TERMINAL, 'RECONCILIATION_REQUIRED', 'PAUSED']);
