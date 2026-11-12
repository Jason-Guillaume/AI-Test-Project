// 自动化测试中心页面的共用状态色和空项目提示。
import { Alert, Tag } from 'antd';
import { Link } from 'react-router-dom';

const STATUS_COLOR: Record<string, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'success',
  FAILED: 'error',
  CANCELLED: 'warning',
  TIMEOUT: 'orange',
};

const STATUS_LABEL: Record<string, string> = {
  PENDING: '等待中',
  RUNNING: '执行中',
  SUCCESS: '成功',
  FAILED: '失败',
  CANCELLED: '已取消',
  TIMEOUT: '超时',
};

/** 执行状态标签。未知状态原样显示。 */
export function StatusTag({ status }: { status?: string | null }) {
  if (!status) return <span>-</span>;
  return <Tag color={STATUS_COLOR[status] || 'default'}>{STATUS_LABEL[status] || status}</Tag>;
}

/** 当前控制台没有选中业务项目时的提示。 */
export function ProjectRequired({ projectId }: { projectId: number | null }) {
  if (projectId) return null;
  return <Alert type="info" showIcon style={{ marginBottom: 16 }} message="请先在顶部选择业务项目。自动化项目、报告和通知都挂在这个项目的权限下。" />;
}

/** 进入 Allure 报告页的链接。 */
export function ReportLink({ reportId }: { reportId: number | null }) {
  if (!reportId) return <span>报告未回传</span>;
  return <Link to={`/console/automation-reports/${reportId}`}>查看 Allure 报告</Link>;
}
