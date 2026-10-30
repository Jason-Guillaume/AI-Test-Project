import type { MockContextStatus } from '@/features/mocking/contracts';

export const STATUS_OPTIONS: { value: MockContextStatus; label: string }[] = [
  { value: 'ACTIVE', label: 'ACTIVE' },
  { value: 'CLOSED', label: 'CLOSED' },
  { value: 'EXPIRED', label: 'EXPIRED' },
];

/** 时间标签：把 ISO 字符串压成 HH:mm:ss。 */
export function fmtTs(v: string | null): string {
  if (!v) return '-';
  const m = v.match(/T(\d{2}:\d{2}:\d{2})/);
  return m ? m[1] : v.slice(0, 19);
}
