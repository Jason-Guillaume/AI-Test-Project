// 列表“序号”列计算。
// 序号只取决于当前筛选、排序和分页后的展示顺序，不落库、不跨页累加重复偏移。
// 行键、勾选、详情、编辑和删除仍必须使用真实资源 ID，不能拿序号替代。
import type { ColumnType } from 'antd/es/table';

export interface SequenceOptions<T> {
  page?: number; // 服务端分页当前页，从 1 开始
  pageSize?: number; // 服务端分页每页条数
  rows?: readonly T[]; // 前端分页/排序后的完整结果；传入时按记录在结果中的位置编号
  width?: number; // 列宽，默认 70
  title?: string; // 列标题，默认“序号”
}

/**
 * 计算服务端分页下的展示序号。
 * 页码和每页条数都做下限兜底，避免异常分页参数把序号算成 0 或负数。
 */
export function sequenceNumber(rowIndex: number, page = 1, pageSize = 10): number {
  const safePage = Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1;
  const safePageSize = Number.isFinite(pageSize) ? Math.max(1, Math.floor(pageSize)) : 10;
  return (safePage - 1) * safePageSize + rowIndex + 1;
}

/**
 * 生成可复用的“序号”列。
 *
 * 服务端分页列表传 page/pageSize；前端分页或自行排序的列表传 rows，
 * 这样翻页、筛选、排序和删除后都会按完整结果重新编号。
 */
export function sequenceColumn<T>(options: SequenceOptions<T> = {}): ColumnType<T> {
  const { page = 1, pageSize = 10, rows, width = 70, title = '序号' } = options;
  return {
    title,
    key: '__sequence',
    width,
    align: 'center',
    render: (_value: unknown, record: T, index: number) => {
      if (rows) {
        const position = rows.indexOf(record);
        return position >= 0 ? position + 1 : index + 1;
      }
      return sequenceNumber(index, page, pageSize);
    },
  };
}