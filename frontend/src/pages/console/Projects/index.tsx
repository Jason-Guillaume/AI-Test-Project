// 用户可见项目列表：当前用户有权访问的项目。
// 本模块导出 ConsoleProjectsPage，由路由 /console/projects 挂载。
import { Button, Input, Space } from 'antd';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { projectsApi } from '@/api/projects';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import { ProjectRoleTag } from '@/components/RoleTag';

/**
 * 用户控制台的项目列表页组件。
 *
 * 用途：分页展示当前用户有权访问的项目，支持按项目名关键字搜索。
 * 数据来源：projectsApi.list，请求参数为分页 + 关键字；接口仅返回当前用户可访问项目。
 * 失败呈现：列表接口失败时整页换成可重试的 ErrorState。
 * 空态：无匹配项目时表格为空。
 */
export function ConsoleProjectsPage() {
  // 分页状态：默认第一页、每页 10 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  // 关键字搜索词；空串等价于不搜索
  const [keyword, setKeyword] = useState('');

  // 分页参数与筛选条件统一拼成一份 query 对象。
  const query = useMemo(
    () => ({
      page: pagination.page,
      page_size: pagination.page_size,
      // 空串转成 undefined，避免向后端发 keyword= 的无意义参数
      keyword: keyword || undefined,
    }),
    [pagination, keyword],
  );

  // 项目列表查询；queryKey 带 query 对象，参数一变就重新请求
  const listQuery = useQuery({
    queryKey: ['projects', query],
    queryFn: () => projectsApi.list(query),
  });

  // 加载中：整页只放一个 LoadingState，避免半渲染的布局跳动
  if (listQuery.isPending) return <LoadingState />;
  // 失败：换成可重试的 ErrorState，不渲染空表格以免误导用户
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  const data = listQuery.data;

  return (
    <PageContainer>
      <Input.Search
        placeholder="按项目名搜索"
        allowClear
        enterButton
        style={{ maxWidth: 320, marginBottom: 16 }}
        onSearch={(v) => {
          setKeyword(v);
          // 换关键词后回到第一页，否则可能停留在已不存在的页码
          setPagination((p) => ({ ...p, page: 1 }));
        }}
      />
      <ResourceTable
        rowKey={(r) => r.id}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          { title: '项目名称', dataIndex: 'name' },
          // 未挂到任何组织时 organization_name 为 null，展示 '-' 占位
          { title: '组织', dataIndex: 'organization_name', render: (v: string | null) => v ?? '-' },
          { title: '负责人', dataIndex: 'owner_username' },
          {
            title: '我的角色',
            dataIndex: 'my_role',
            render: (v: string | null) => <ProjectRoleTag role={v} />,
          },
          {
            title: '操作',
            key: 'actions',
            render: (_: unknown, row: { id: number }) => (
              <Space>
                <Link to={`/console/projects/${row.id}`}>
                  <Button size="small">进入</Button>
                </Link>
              </Space>
            ),
          },
        ]}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
      />
    </PageContainer>
  );
}
