// 飞书通知域常量：通知条件、发送状态的选项列表与状态色。
//
// 为什么放在 notifications feature，而不是 Reports/constants.ts：
// 这组常量同时被「测试报告页」（报告通知 Tab）与「飞书通知渠道页」消费，
// 属于通知域而非报告域。原先挂在 Reports/constants.ts 下，导致
// NotificationChannels 反向 import 兄弟模块（../Reports/constants），
// 报告模块改名或拆分会静默打断通知模块，因此由通知域持有这些常量。
//
// 字面量与后端 features/notifications/schemas_channel.py 严格对齐。

import type { NotifyCondition, NotifyStatus } from '@/features/notifications/contracts';

import type { Option } from '@/shared/lib/options';

export const NOTIFY_CONDITION_OPTIONS: Option<NotifyCondition>[] = [
  { value: 'ALWAYS', label: '总是发送 ALWAYS' },
  { value: 'ONLY_FAILED', label: '仅失败时 ONLY_FAILED' },
  { value: 'ONLY_HIGH_RISK', label: '仅高风险时 ONLY_HIGH_RISK' },
];

export const NOTIFY_STATUS_OPTIONS: Option<NotifyStatus>[] = [
  { value: 'PENDING', label: '待发送' },
  { value: 'SUCCESS', label: '发送成功' },
  { value: 'FAILED', label: '发送失败' },
];

/** 通知发送状态色：报告页与通知渠道页共用这一份。 */
export const NOTIFY_STATUS_COLOR: Record<NotifyStatus, string> = {
  PENDING: 'processing',
  SUCCESS: 'green',
  FAILED: 'red',
};
