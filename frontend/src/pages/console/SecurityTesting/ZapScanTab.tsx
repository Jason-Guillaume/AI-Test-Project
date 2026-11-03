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
import { Alert, Tabs } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import { JobsSubTab } from './zap/jobs';
import { PoliciesSubTab } from './zap/policies';
import { ResultsSubTab } from './zap/results';
import { TargetsSubTab } from './zap/targets';

/** 安全扫描 Tab。projectId 由父页传入（已确保非空）。 */
export function ZapScanTab({ projectId, initialJobId }: { projectId: number; initialJobId?: number }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSubTab = searchParams.get('zapTab');
  const activeKey = ['targets', 'policies', 'jobs', 'results'].includes(requestedSubTab ?? '')
    ? requestedSubTab! : initialJobId ? 'jobs' : 'targets';
  const statusQuery = useQuery({
    queryKey: ['zap-status', projectId],
    queryFn: () => zapApi.getProjectZapStatus(projectId),
    retry: false,
    refetchInterval: 30000,
  });
  const scanAvailable = statusQuery.data?.available === true;
  return (
    <>
    {statusQuery.isPending && <Alert type="info" showIcon message="正在检查 ZAP 服务状态；扫描任务入口暂不可用。" />}
    {statusQuery.isError && <Alert type="warning" showIcon message="无法确认 ZAP 服务状态，已停用发起扫描入口。请重试状态检查或联系平台管理员。" action={<a onClick={() => void statusQuery.refetch()}>重试</a>} />}
    {!statusQuery.isPending && !statusQuery.isError && !scanAvailable && <Alert type="warning" showIcon message={statusQuery.data?.message ?? 'ZAP 服务未启用。可浏览已有扫描记录；启动扫描前请管理员配置 ZAP 服务。'} />}
    <Tabs
      type="card"
      size="small"
      activeKey={activeKey}
      onChange={(key) => {
        const next = new URLSearchParams(searchParams);
        next.set('tab', 'zap'); next.set('zapTab', key);
        if (initialJobId) next.set('jobId', String(initialJobId));
        setSearchParams(next, { replace: true });
      }}
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
          children: <JobsSubTab projectId={projectId} initialJobId={initialJobId} scanAvailable={scanAvailable} />,
        },
        {
          key: 'results',
          label: '扫描结果',
          children: <ResultsSubTab projectId={projectId} initialJobId={initialJobId} />,
        },
      ]}
    />
    </>
  );
}
