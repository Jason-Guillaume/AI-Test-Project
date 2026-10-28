// 测试数据中心页（ConsoleTestDataPage）。
//
// §7.1 页壳：顶部沿用 useConsoleScope 的当前项目（不单独做项目切换器），
// 另加一个环境 Select（复用 environmentsApi）——环境只影响「试跑 / 生成」按钮，
// 不作为列表过滤的强制条件；列表始终按项目隔离。
//
// Tabs：测试数据 | Fixture | 数据工厂 | 执行记录。
// 未选项目时用空状态组件占位，不发请求。
//
// Phase B：顶部环境同时驱动「Fixture 生成/清理」「Provider 试跑」，
// 三者的结果都开进 ExecutionDetailDrawer（每步 input/output/error）。
import { useMemo, useState } from 'react';
import { Select, Space, Tabs } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/api/projects';
import { EmptyState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { TestDataTab } from './TestDataTab';
import { FixtureTab } from './FixtureTab';
import { ProviderTab } from './ProviderTab';
import { ExecutionTab } from './ExecutionTab';
import type { Environment } from '@/types';

/**
 * 测试数据中心页。
 *
 * 依赖当前项目作用域：未选项目时整页空态。切换组织/项目由 useConsoleScope
 * 失效 ['test-data']，四个 Tab 的列表都会按新项目重拉。
 */
export function ConsoleTestDataPage() {
  const { currentProjectId } = useConsoleScope();
  // 执行环境：驱动 Fixture 的「生成/清理」与 Provider 的「试跑」，列表不过滤。
  const [environmentId, setEnvironmentId] = useState<number | null>(null);

  // 环境列表：只取启用的，供试跑选择；不阻塞页面渲染。
  const envsQuery = useQuery({
    queryKey: ['project-environments', currentProjectId],
    queryFn: () => projectsApi.listEnvironments(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const environments: Environment[] = useMemo(() => envsQuery.data?.items ?? [], [envsQuery.data?.items]);
  const currentEnv = useMemo(
    () => environments.find((e) => e.id === environmentId) ?? null,
    [environments, environmentId],
  );

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <Space style={{ marginBottom: 16 }} size="middle">
        <span style={{ color: '#888' }}>执行环境：</span>
        <Select
          style={{ width: 220 }}
          placeholder="选择环境（生成 / 清理 / 试跑用）"
          value={environmentId ?? undefined}
          onChange={(v) => setEnvironmentId(v ?? null)}
          options={environments.map((e) => ({
            value: e.id,
            label: e.display_name || e.name,
          }))}
          showSearch
          optionFilterProp="label"
          allowClear
        />
      </Space>

      <Tabs
        defaultActiveKey="assets"
        destroyInactiveTabPane
        items={[
          {
            key: 'assets',
            label: '测试数据',
            children: <TestDataTab projectId={currentProjectId} />,
          },
          {
            key: 'fixtures',
            label: 'Fixture',
            children: (
              <FixtureTab
                projectId={currentProjectId}
                environmentId={environmentId}
                environmentName={currentEnv ? currentEnv.display_name || currentEnv.name : null}
              />
            ),
          },
          {
            key: 'providers',
            label: '数据工厂',
            children: (
              <ProviderTab
                projectId={currentProjectId}
                environmentId={environmentId}
                environmentName={currentEnv ? currentEnv.display_name || currentEnv.name : null}
              />
            ),
          },
          {
            key: 'executions',
            label: '执行记录',
            children: <ExecutionTab projectId={currentProjectId} />,
          },
        ]}
      />
    </PageContainer>
  );
}
