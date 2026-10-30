// 统一列表筛选工具栏。
//
// 背景：现状 8 处内联筛选工具栏（Defects、ReportList、admin/Projects、admin/Organizations、
// admin/ModelConfigs、admin/Users、console/Projects、SecurityTesting/StrategyTab），
// 宽度取值不统一（maxWidth 240/260、minWidth 120~280）。
// 重构计划 §3.D「用例表格支持搜索、状态筛选、优先级筛选」就是它。

import { useEffect, useState } from 'react';
import { Button, Flex, Input, Select, Space, theme, Typography } from 'antd';
import type { ReactNode } from 'react';
import type { Option } from '@/shared/lib/options';

/** 一个下拉筛选器的声明。 */
export interface FilterSelectField {
  /** 字段 key，用于把选中值组装进 onFilterChange */
  key: string;
  /** 中文标签，渲染为筛选项前缀 */
  label: string;
  /** 选项列表 */
  options: Option[];
  /** 占位符，默认取 label */
  placeholder?: string;
  /** 控件最小宽度 */
  minWidth?: number;
  /** 是否可清除 */
  allowClear?: boolean;
}

/**
 * 列表筛选工具栏：搜索框 + N 个下拉筛选 + 操作区。
 *
 * 受控组件：筛选值变化时通过 onFilterChange 抛回调用方，调用方负责重新拉取接口。
 * 搜索框内部持有输入草稿，只在按下回车或点击「查询」时才调用 onSearch——
 * 关键词搜索都是服务端分页查询，每敲一个字符打一次接口不可接受。
 *
 * @param search 已提交的搜索关键词（不含未回车的草稿）
 * @param searchPlaceholder 搜索占位符
 * @param selects 下拉筛选器列表
 * @param values 当前各下拉的选中值，key 为字段名
 * @param onSearch 搜索触发
 * @param onFilterChange 下拉筛选变化
 * @param onReset 重置（调用方负责清空所有筛选）
 * @param actions 左侧操作区（新建、导入等）
 * @param showReset 是否显示「重置」按钮
 * @param showSearch 是否显示搜索框；只有服务端下拉筛选、没有关键词搜索的列表可关闭
 */
export function FilterToolbar({
  search = '',
  searchPlaceholder = '搜索',
  selects = [],
  values = {},
  onSearch,
  onFilterChange,
  onReset,
  actions,
  showReset = true,
  showSearch = true,
}: {
  /** 已提交的搜索关键词；仅 showSearch 时有效 */
  search?: string;
  searchPlaceholder?: string;
  selects?: FilterSelectField[];
  values?: Record<string, string | undefined>;
  onSearch?: (keyword: string) => void;
  onFilterChange?: (key: string, value: string | undefined) => void;
  onReset?: () => void;
  actions?: ReactNode;
  showReset?: boolean;
  /** 是否显示搜索框；只有服务端筛选器、没有关键词搜索的列表可关闭 */
  showSearch?: boolean;
}) {
  const { token } = theme.useToken();

  // 输入草稿与已提交关键词分离：只按回车/点查询才提交。
  const [draft, setDraft] = useState(search);
  // 调用方重置或外部改写 search 时同步清空输入框，否则受控值会卡在旧草稿上。
  useEffect(() => setDraft(search), [search]);

  const hasFilters = selects.length > 0 || search.trim() !== '' || Object.values(values).some(Boolean);

  return (
    <Flex align="flex-start" justify="space-between" gap={token.margin} wrap="wrap" style={{ marginBottom: token.marginMD }}>
      <Space size="small" wrap align="center">
        {actions}
        {showSearch ? (
          <Input.Search
            allowClear
            placeholder={searchPlaceholder}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onSearch={(v) => onSearch?.(v.trim())}
            style={{ width: 240 }}
            size="small"
          />
        ) : null}
        {selects.map((f) => (
          <Flex key={f.key} align="center" gap={token.marginXXS}>
            <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM, whiteSpace: 'nowrap' }}>
              {f.label}
            </Typography.Text>
            <Select
              allowClear={f.allowClear ?? true}
              size="small"
              placeholder={f.placeholder ?? '全部'}
              options={f.options}
              value={values[f.key]}
              onChange={(v) => onFilterChange?.(f.key, v)}
              style={{ minWidth: f.minWidth ?? 140 }}
            />
          </Flex>
        ))}
        {showReset && hasFilters ? (
          <Button size="small" type="link" onClick={onReset}>
            重置
          </Button>
        ) : null}
      </Space>
    </Flex>
  );
}
