// 安全测试 · 安全扫描（ZAP）Tab。
//
// 五个顶层 Tab 之外的第 5 个：内部四个嵌套子 Tab。
//   - 扫描目标：目标 CRUD，列表带授权状态徽标；
//   - 扫描策略与认证：扫描策略 + 认证配置两块；平台内置策略全字段只读；
//   - 扫描任务：任务列表 + 四步向导（选目标 → 选策略与认证 → 授权确认 → 计划预览并提交）；
//   - 扫描结果：按任务看事件时间线 / 告警 / 覆盖率 / 报告。
//
// 安全红线：主动扫描必须由人在「计划预览」之后显式勾选确认（confirmed + approval_note），
// 后端仍会独立校验批准行为；生产环境目标由后端 gate 直接拒绝。
import { Tabs } from 'antd';
import { JobsSubTab } from './zap/jobs';
import { PoliciesSubTab } from './zap/policies';
import { ResultsSubTab } from './zap/results';
import { TargetsSubTab } from './zap/targets';

/** 安全扫描 Tab。projectId 由父页传入（已确保非空）。 */
export function ZapScanTab({ projectId, initialJobId }: { projectId: number; initialJobId?: number }) {
  return (
    <Tabs
      type="card"
      size="small"
      defaultActiveKey={initialJobId ? 'jobs' : 'targets'}
      items={[
        {
          key: 'targets',
          label: '扫描目标',
          children: <TargetsSubTab projectId={projectId} />,
        },
        {
          key: 'policies',
          label: '扫描策略与认证',
          children: <PoliciesSubTab projectId={projectId} />,
        },
        {
          key: 'jobs',
          label: '扫描任务',
          children: <JobsSubTab projectId={projectId} initialJobId={initialJobId} />,
        },
        {
          key: 'results',
          label: '扫描结果',
          children: <ResultsSubTab projectId={projectId} />,
        },
      ]}
    />
  );
}
