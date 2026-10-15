// Fixture 依赖树：递归展示该 Fixture 的依赖（含子依赖）。
//
// §7.3：循环依赖在保存时被后端拒绝，因此依赖关系是 DAG，前端可安全递归展开。
// 数据来自 GET /fixtures/{id}/dependencies，返回 FixtureTreeNode[]（已含 children）。
import { useMemo } from 'react';
import { Empty, Spin, Tag, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { useQuery } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { ErrorState } from '@/components/PageState';
import { FIXTURE_SCOPE_OPTIONS, FIXTURE_STATUS_OPTIONS, labelOf } from './constants';
import type { FixtureTreeNode } from '@/types';

/** 把后端树节点转成 antd Tree DataNode；title 用 name + fixture_key + 状态标签。 */
function toDataNodes(nodes: FixtureTreeNode[]): DataNode[] {
  return nodes.map((n) => ({
    key: `${n.id}:${n.depth}`,
    title: (
      <span>
        <span style={{ marginRight: 8 }}>{n.name}</span>
        <span style={{ color: '#999', fontSize: 12 }}>{n.fixture_key}</span>
        <Tag style={{ marginLeft: 8 }}>{labelOf(FIXTURE_SCOPE_OPTIONS, n.scope)}</Tag>
        <Tag>{labelOf(FIXTURE_STATUS_OPTIONS, n.status)}</Tag>
      </span>
    ),
    children: n.children?.length ? toDataNodes(n.children) : undefined,
  }));
}

/**
 * 依赖树 Tab。
 */
export function FixtureDependencyTree({ fixtureId }: { fixtureId: number }) {
  const query = useQuery({
    queryKey: ['test-data', 'fixture', fixtureId, 'dependencies'],
    queryFn: () => testDataApi.dependencyTree(fixtureId),
    enabled: fixtureId != null,
  });

  const treeData = useMemo(
    () => (query.data ? toDataNodes(query.data) : []),
    [query.data],
  );

  if (query.isPending) return <Spin />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (treeData.length === 0) return <Empty description="该 Fixture 暂无依赖" />;

  return (
    <Tree
      treeData={treeData}
      defaultExpandAll
      showLine
      selectable={false}
    />
  );
}
