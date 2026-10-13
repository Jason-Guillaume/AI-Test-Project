// 导入预览表：展示四分类（新增/已存在/有变更/无变化）+ 推荐模块 + 勾选确认。
// 确认时把选中序号（0-based）与可选覆盖模块回传给 ImportDialog 发起 confirm。
import { useMemo, useState } from 'react';
import { Alert, Button, Checkbox, Select, Space, Table, Tag, Typography } from 'antd';
import type { ApiImportPreviewItem, ApiImportPreviewResponse, ApiModule } from '@/types';
import { CLASSIFICATION_COLOR, CLASSIFICATION_LABEL } from './constants';

// 预览行：原始预览项 + 行序号（0-based，对应 confirm 的 selected_items）。
type PreviewRow = ApiImportPreviewItem & { _idx: number };

/**
 * 导入预览表。
 *
 * 默认勾选全部 NEW + CHANGED 项；UNCHANGED/EXISTING 不可勾选（确认时本就跳过）。
 * onConfirm 回传 selected（选中序号数组；null 表示全部 NEW+CHANGED）与 overrideModuleId。
 */
export function ImportPreview({
  preview,
  modules,
  onConfirm,
  confirming,
}: {
  preview: ApiImportPreviewResponse;
  modules: ApiModule[];
  onConfirm: (selected: number[] | null, overrideModuleId: number | null) => void;
  confirming: boolean;
}) {
  // 默认选中所有可导入项（NEW / CHANGED）。
  const defaultSelected = useMemo(
    () =>
      preview.items
        .map((item, idx) => ({ item, idx }))
        .filter(({ item }) => item.classification === 'NEW' || item.classification === 'CHANGED')
        .map(({ idx }) => idx),
    [preview],
  );
  const [selected, setSelected] = useState<Set<number>>(new Set(defaultSelected));
  const [overrideModuleId, setOverrideModuleId] = useState<number | null>(null);

  const toggle = (idx: number, checked: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(idx);
      else next.delete(idx);
      return next;
    });

  const moduleOptions = modules.map((m) => ({
    label: m.is_default ? `${m.name}（默认）` : m.name,
    value: m.id,
  }));

  const selectedArr = Array.from(selected).sort((a, b) => a - b);
  // 选中集合与默认一致时传 null（= 全部 NEW+CHANGED），语义更稳。
  const selectedForConfirm =
    selectedArr.length === defaultSelected.length &&
    defaultSelected.every((i) => selected.has(i))
      ? null
      : selectedArr;

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space>
        <Tag color="green">新增 {preview.new_count}</Tag>
        <Tag color="orange">有变更 {preview.changed_count}</Tag>
        <Tag>已存在 {preview.existing_count}</Tag>
        <Tag>无变化 {preview.unchanged_count}</Tag>
        <Typography.Text type="secondary">共 {preview.total} 条</Typography.Text>
      </Space>

      <Table<PreviewRow>
        rowKey={(r) => String(r._idx)}
        dataSource={preview.items.map((item, idx) => ({ ...item, _idx: idx }))}
        pagination={false}
        size="small"
        scroll={{ y: 320 }}
        columns={[
          {
            title: '选',
            dataIndex: '_idx',
            width: 50,
            render: (_: unknown, row: PreviewRow) => {
              const importable =
                row.classification === 'NEW' || row.classification === 'CHANGED';
              if (!importable) {
                return <Checkbox disabled />;
              }
              return (
                <Checkbox
                  checked={selected.has(row._idx)}
                  onChange={(e) => toggle(row._idx, e.target.checked)}
                />
              );
            },
          },
          {
            title: '分类',
            dataIndex: 'classification',
            width: 90,
            render: (v: PreviewRow['classification']) => (
              <Tag color={CLASSIFICATION_COLOR[v]}>
                {CLASSIFICATION_LABEL[v]}
              </Tag>
            ),
          },
          {
            title: '接口',
            key: 'api',
            render: (_: unknown, row: PreviewRow) => (
              <Space size={4}>
                <Tag>{row.schema.method}</Tag>
                <Typography.Text code>{row.schema.path}</Typography.Text>
                <Typography.Text type="secondary">{row.schema.name}</Typography.Text>
              </Space>
            ),
          },
          {
            title: '推荐模块',
            dataIndex: 'proposed_module_name',
            width: 140,
          },
          {
            title: '告警',
            dataIndex: 'warnings',
            render: (v: string[]) =>
              v && v.length ? (
                <Typography.Text type="warning">{v.join('；')}</Typography.Text>
              ) : (
                '-'
              ),
          },
        ]}
      />

      <Alert
        type="info"
        showIcon
        message="确认将重新解析并入库（幂等）：新建/更新选中项，其余跳过。"
      />

      <Space>
        <Select
          allowClear
          placeholder="覆盖目标模块（可选）"
          value={overrideModuleId ?? undefined}
          onChange={(v: number | undefined) => setOverrideModuleId(v ?? null)}
          options={moduleOptions}
          showSearch
          optionFilterProp="label"
          style={{ minWidth: 220 }}
        />
        <Button
          type="primary"
          loading={confirming}
          disabled={selected.size === 0}
          onClick={() => onConfirm(selectedForConfirm, overrideModuleId)}
        >
          确认导入（{selected.size}）
        </Button>
      </Space>
    </Space>
  );
}
