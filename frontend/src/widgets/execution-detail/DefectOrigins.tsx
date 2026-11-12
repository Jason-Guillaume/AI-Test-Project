// 缺陷来源详情：按授权来源定位测试执行或安全疑似问题。
import { Alert, Space, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { bugsApi } from '@/features/defects/api/defects';
import type { DefectSourceLink, DefectSourceType } from '@/features/defects/contracts';

/** 展示缺陷的持久来源；已删除来源会由外键移除关联。 */
export function DefectOrigins({ bugId }: { bugId: number }) {
  const query = useQuery({ queryKey: ['bug-sources', bugId], queryFn: () => bugsApi.bugSources(bugId) });
  if (query.isLoading) return <Typography.Text>正在读取来源…</Typography.Text>;
  if (query.isError) return <Alert type="warning" message="无法读取缺陷来源" />;
  if (!query.data?.length) return <Typography.Text type="secondary">暂无关联来源</Typography.Text>;
  return <Space direction="vertical">{query.data.map(link => <Origin key={link.id} link={link} />)}</Space>;
}

/** 只用后端授权返回的项目和运行信息构造来源链接。 */
function Origin({ link }: { link: DefectSourceLink }) {
  const type: DefectSourceType = link.case_execution_id != null ? 'CASE_EXECUTION' : 'SECURITY_FINDING';
  const id = link.case_execution_id ?? link.security_finding_id!;
  const query = useQuery({ queryKey: ['defect-source-context', type, id], queryFn: () => bugsApi.sourceContext(type, id) });
  if (query.isLoading) return <Typography.Text>正在读取来源 #{id}…</Typography.Text>;
  if (query.isError || !query.data) return <Typography.Text type="secondary">来源 #{id} 不可用或无访问权限</Typography.Text>;
  const context = query.data;
  const href = type === 'CASE_EXECUTION' && context.test_run_id != null
    ? `/console/execution-history?runId=${context.test_run_id}&caseExecutionId=${id}&projectId=${context.project_id}`
    : `/console/security-testing?tab=findings&findingId=${id}&projectId=${context.project_id}`;
  return <Link to={href}>{type === 'CASE_EXECUTION' ? '用例执行' : '安全疑似问题'} #{id}</Link>;
}
