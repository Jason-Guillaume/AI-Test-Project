// 通用分页表格：统一 page/page_size 参数与后端 Paginated 信封对齐。
import { Table, type TableProps } from 'antd';
import type { CSSProperties, ReactNode } from 'react';

// 前端使用的分页状态：字段名与后端分页信封一致，避免转换出错。
export interface PaginationState {
  page: number; // 当前页码，从 1 开始
  page_size: number; // 每页条数
}

/**
 * 通用资源分页表格。
 *
 * 纯展示组件，自身不发请求：数据由调用方通过 dataSource/total 传入，
 * 翻页或修改每页条数时通过 onPaginationChange 回调把新的分页状态抛出去，
 * 由调用方负责重新拉取接口。
 *
 * 空态显示 emptyText 文案，加载中显示 antd Table 自带的 loading 遮罩。
 */
export function ResourceTable<T>({
  rowKey,
  columns,
  dataSource,
  loading,
  total,
  pagination,
  onPaginationChange,
  emptyText = '暂无数据',
  expandedRowRender,
  onRowClick,
  rowStyle,
}: {
  rowKey: (row: T) => string | number; // 每行唯一键，优先用后端主键 id
  columns: TableProps<T>['columns']; // 列定义，由调用方按业务拼装
  dataSource: T[]; // 当前页数据
  loading?: boolean; // 是否显示加载遮罩（接口请求中）
  total: number; // 后端返回的总条数，用于计算总页数
  pagination: PaginationState; // 当前分页状态，驱动 current/pageSize
  onPaginationChange: (next: PaginationState) => void; // 翻页或改每页条数时的回调
  emptyText?: string; // 空态文案
  expandedRowRender?: (row: T) => ReactNode; // 可选的展开行渲染函数
  onRowClick?: (row: T) => void; // 可选的行点击回调（打开详情抽屉等）
  rowStyle?: CSSProperties; // 可选的行样式（如 cursor: pointer）
}) {
  return (
    <Table<T>
      rowKey={rowKey}
      columns={columns}
      dataSource={dataSource}
      loading={loading}
      locale={{ emptyText }}
      expandable={expandedRowRender ? { expandedRowRender } : undefined}
      onRow={(record) => ({
        ...(rowStyle ? { style: rowStyle } : {}),
        ...(onRowClick ? { onClick: () => onRowClick(record) } : {}),
      })}
      pagination={{
        current: pagination.page,
        pageSize: pagination.page_size,
        total,
        showSizeChanger: true,
        showTotal: (t) => `共 ${t} 条`,
        pageSizeOptions: [10, 20, 50],
        onChange: (page, pageSize) => onPaginationChange({ page, page_size: pageSize }),
      }}
      size="middle"
    />
  );
}
