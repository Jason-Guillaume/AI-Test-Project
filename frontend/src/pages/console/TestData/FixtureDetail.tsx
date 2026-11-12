// Fixture 详情：右栏，内嵌 Tabs。
//
// §7.3 右详情 Tabs：基本信息、依赖、生成流程、输出、Cleanup、引用关系。
// 数据来自 GET /fixtures/{id}（FixtureDetail，含 steps/outputs/dependencies/referenced_cases）。
// 各子表保存后失效 ['test-data','fixture',id]，本组件自动重拉。
import { Alert, Descriptions, Tabs } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { testDataApi } from '@/features/test-data/api/testData';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import {
  FIXTURE_CLEANUP_POLICY_OPTIONS,
  FIXTURE_SCOPE_OPTIONS,
  FIXTURE_STATUS_OPTIONS,
  labelOf,
} from './constants';
import { FixtureBasicForm } from './FixtureBasicForm';
import { FixtureDependencyTree } from './FixtureDependencyTree';
import { FixtureStepList } from './FixtureStepList';
import { FixtureOutputTable } from './FixtureOutputTable';
import { FixtureCleanupList } from './FixtureCleanupList';
import { FixtureReferenceList } from './FixtureReferenceList';

/**
 * Fixture 详情。fixtureId 为 null 时由调用方渲染空态。
 */
export function FixtureDetail({ fixtureId }: { fixtureId: number | null }) {
  const query = useQuery({
    queryKey: ['test-data', 'fixture', fixtureId],
    queryFn: () => testDataApi.getFixture(fixtureId!),
    enabled: fixtureId != null,
  });

  if (fixtureId == null) {
    return <Alert type="info" showIcon message="请先在左侧选择一个 Fixture" />;
  }
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const fixture = query.data;
  return (
    <div>
      <Descriptions
        size="small"
        column={3}
        bordered
        style={{ marginBottom: 16 }}
        items={[
          { key: 'name', label: '名称', children: fixture.name },
          { key: 'key', label: 'fixture_key', children: fixture.fixture_key },
          { key: 'entity', label: '实体类型', children: fixture.entity_type },
          { key: 'scope', label: '作用域', children: labelOf(FIXTURE_SCOPE_OPTIONS, fixture.scope) },
          { key: 'status', label: '状态', children: labelOf(FIXTURE_STATUS_OPTIONS, fixture.status) },
          {
            key: 'cleanup',
            label: '清理策略',
            children: labelOf(FIXTURE_CLEANUP_POLICY_OPTIONS, fixture.cleanup_policy),
          },
          { key: 'cache', label: '缓存', children: fixture.cache_enabled ? '是' : '否' },
          {
            key: 'deps',
            label: '依赖数',
            children: fixture.dependency_count,
          },
          {
            key: 'refs',
            label: '被引用',
            children: fixture.referenced_case_count,
          },
        ]}
      />
      <Tabs
        defaultActiveKey="basic"
        items={[
          {
            key: 'basic',
            label: '基本信息',
            children: <FixtureBasicForm fixture={fixture} />,
          },
          {
            key: 'deps',
            label: '依赖',
            children: <FixtureDependencyTree fixtureId={fixture.id} />,
          },
          {
            key: 'generate',
            label: '生成流程',
            children: <FixtureStepList fixture={fixture} phase="GENERATE" />,
          },
          {
            key: 'outputs',
            label: '输出',
            children: <FixtureOutputTable fixture={fixture} />,
          },
          {
            key: 'cleanup',
            label: 'Cleanup',
            children: <FixtureCleanupList fixture={fixture} />,
          },
          {
            key: 'refs',
            label: '引用关系',
            children: <FixtureReferenceList references={fixture.referenced_cases} />,
          },
        ]}
      />
    </div>
  );
}
