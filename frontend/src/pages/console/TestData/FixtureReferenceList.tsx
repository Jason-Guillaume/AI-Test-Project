// Fixture 引用关系：列出引用该 Fixture 的用例。
//
// §7.3：用例名称列表，点进去跳转 /console/test-asset 并带 case id。
// 现有 TestAsset 页不支持深链状态机，Phase A 先只展示 case id，不新做路由状态机。
import { Empty, Table } from 'antd';
import type { FixtureDetail } from '@/features/test-data/contracts';


/**
 * 引用关系 Tab：只读展示 referenced_cases（仅含 test_case_id 与 sort）。
 */
export function FixtureReferenceList({
  references,
}: {
  references: FixtureDetail['referenced_cases'];
}) {
  if (!references || references.length === 0) {
    return <Empty description="暂无用例引用该 Fixture" />;
  }
  return (
    <Table
      rowKey={(r) => r.test_case_id}
      dataSource={references}
      pagination={false}
      size="middle"
      columns={[
        {
          title: '用例 ID',
          dataIndex: 'test_case_id',
          render: (v: number) => `#${v}`,
        },
        { title: '排序', dataIndex: 'sort', width: 100 },
      ]}
    />
  );
}
