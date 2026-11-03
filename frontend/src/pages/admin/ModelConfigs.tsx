import { ConsoleScopeProvider, useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { ModelCenterPage } from '@/pages/console/ModelCenterPage';
import { useQuery } from '@tanstack/react-query';
import { Flex, Select, Typography } from 'antd';
import { projectsApi } from '@/features/projects/api/projects';
import { collectPages } from '@/shared/api/pagination';

function AdminModelCenterContent() {
  const { currentProjectId, setProjectId } = useConsoleScope();
  const projectsQuery = useQuery({
    queryKey: ['model-center', 'admin-project-options'],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })),
  });

  return (
    <>
      <Flex justify="flex-end" align="center" gap="small" style={{ marginBottom: 12 }}>
        <Typography.Text type="secondary">项目范围</Typography.Text>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="全部模型"
          loading={projectsQuery.isPending}
          value={currentProjectId ?? undefined}
          onChange={(projectId: number | undefined) => setProjectId(projectId ?? null)}
          options={(projectsQuery.data?.items ?? []).map((project) => ({
            value: project.id,
            label: `${project.name} · #${project.id}`,
          }))}
          style={{ width: 280 }}
        />
      </Flex>
      <ModelCenterPage />
    </>
  );
}

/** 管理端提供统一模型中心，并允许管理员选择项目维护项目私有资源。 */
export function AdminModelConfigsPage() {
  return (
    <ConsoleScopeProvider>
      <AdminModelCenterContent />
    </ConsoleScopeProvider>
  );
}
