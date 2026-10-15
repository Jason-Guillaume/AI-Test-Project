// Fixture 左树：按 entity_type 分组，节点标题 name，副标题 fixture_key。
//
// §7.3：数据来自列表接口，前端分组，不要求后端返回树。选中节点加载右栏详情。
import { useMemo } from 'react';
import { Empty, Input, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';
import { FIXTURE_STATUS_OPTIONS, labelOf } from './constants';
import type { FixtureBrief, FixtureStatus } from '@/types';

/** 把列表按 entity_type 分组并转成 antd Tree DataNode。 */
function buildTreeData(briefs: FixtureBrief[], keyword: string): DataNode[] {
  const kw = keyword.trim().toLowerCase();
  const filtered = kw
    ? briefs.filter(
        (b) =>
          b.name.toLowerCase().includes(kw) ||
          b.fixture_key.toLowerCase().includes(kw) ||
          b.entity_type.toLowerCase().includes(kw),
      )
    : briefs;
  const groups = new Map<string, FixtureBrief[]>();
  for (const b of filtered) {
    if (!groups.has(b.entity_type)) groups.set(b.entity_type, []);
    groups.get(b.entity_type)!.push(b);
  }
  return Array.from(groups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([type, items]) => ({
      key: `group:${type}`,
      title: `${type}（${items.length}）`,
      selectable: false,
      children: items
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((b) => ({
          key: `f:${b.id}`,
          title: (
            <span>
              <span style={{ marginRight: 8 }}>{b.name}</span>
              <span style={{ color: '#999', fontSize: 12 }}>{b.fixture_key}</span>
              <span style={{ color: '#bbb', fontSize: 12, marginLeft: 8 }}>
                {labelOf(FIXTURE_STATUS_OPTIONS, b.status as FixtureStatus)}
              </span>
            </span>
          ),
          isLeaf: true,
        })),
    }));
}

/**
 * Fixture 左树。selectedId 控制高亮；onSelect 传出 fixture id。
 */
export function FixtureTree({
  briefs,
  selectedId,
  onSelect,
  keyword,
  setKeyword,
}: {
  briefs: FixtureBrief[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  keyword: string;
  setKeyword: (v: string) => void;
}) {
  const treeData = useMemo(() => buildTreeData(briefs, keyword), [briefs, keyword]);

  const selectedKeys = selectedId != null ? [`f:${selectedId}`] : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Input.Search
        allowClear
        placeholder="搜索 Fixture"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        style={{ marginBottom: 8 }}
      />
      {treeData.length === 0 ? (
        <Empty description="暂无 Fixture" style={{ marginTop: 32 }} />
      ) : (
        <Tree
          treeData={treeData}
          selectedKeys={selectedKeys}
          defaultExpandAll
          onSelect={(keys) => {
            const k = keys[0] as string | undefined;
            if (k && k.startsWith('f:')) onSelect(Number(k.slice(2)));
          }}
        />
      )}
    </div>
  );
}
