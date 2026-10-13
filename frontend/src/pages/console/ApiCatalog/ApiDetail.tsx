// 接口详情右侧面板：拉取接口详情，按 6 个 Tab 分区展示。
// 各 Tab 自行发请求与 mutation；本组件只负责装配与加载态。
import { Tabs } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { ErrorState, EmptyState, LoadingState } from '@/components/PageState';
import { OverviewTab } from './tabs/OverviewTab';
import { RequestTab } from './tabs/RequestTab';
import { ResponseTab } from './tabs/ResponseTab';
import { RelationTab } from './tabs/RelationTab';
import { DebugTab } from './tabs/DebugTab';
import { HistoryTab } from './tabs/HistoryTab';
import type { ApiModule } from '@/types';

/**
 * 接口详情面板。
 *
 * apiId 为 null 时显示空态；否则拉取详情并渲染 Tabs。
 * modules 透传给 OverviewTab（移动模块下拉用）。
 */
export function ApiDetail({
  apiId,
  modules,
  projectId,
}: {
  apiId: number | null;
  modules: ApiModule[];
  projectId: number;
}) {
  const detailQuery = useQuery({
    queryKey: ['api-catalog', 'api', apiId],
    queryFn: () => apiCatalogApi.getApi(apiId!),
    enabled: apiId != null,
  });

  if (apiId == null) {
    return <EmptyState description="请在左侧选择一个接口" />;
  }
  if (detailQuery.isPending) return <LoadingState />;
  if (detailQuery.isError)
    return <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />;

  const api = detailQuery.data;
  return (
    <Tabs
      defaultActiveKey="overview"
      items={[
        {
          key: 'overview',
          label: '基本',
          children: <OverviewTab api={api} modules={modules} />,
        },
        {
          key: 'request',
          label: '请求',
          children: <RequestTab api={api} />,
        },
        {
          key: 'response',
          label: '响应',
          children: <ResponseTab api={api} />,
        },
        {
          key: 'relation',
          label: '关联',
          children: <RelationTab api={api} projectId={projectId} />,
        },
        {
          key: 'debug',
          label: '调试',
          children: <DebugTab api={api} />,
        },
        {
          key: 'history',
          label: '历史',
          children: <HistoryTab api={api} />,
        },
      ]}
    />
  );
}
