// OWASP ZAP Scan Job Status Badge 面板。
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { JOB_STATUS_BADGE_OPTIONS } from './constants';

export function ScanJobStatusBadge({ status }: { status: string }) {
  return <StatusBadge value={status} options={JOB_STATUS_BADGE_OPTIONS} />;
}
