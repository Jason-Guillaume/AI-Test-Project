// 导入预览：以摘要、可筛选的接口清单和固定操作栏呈现解析结果。
import { useMemo, useState } from 'react';
import { SearchOutlined } from '@ant-design/icons';
import { Button, Checkbox, Input, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import type { ApiImportPreviewItem, ApiImportPreviewResponse, ApiModule, ImportClassification } from '@/features/api-catalog/contracts';

import { CLASSIFICATION_COLOR, CLASSIFICATION_LABEL, METHOD_COLOR } from './constants';
import './ImportPreview.css';

type PreviewRow = ApiImportPreviewItem & { _idx: number };
type ClassificationFilter = ImportClassification | 'ALL';

const IMPORTABLE_CLASSIFICATIONS: ImportClassification[] = ['NEW', 'CHANGED'];

/**
 * 导入预览表。
 * 默认勾选新增和有变更项；已存在、无变化项仅供查看，不参与确认导入。
 */
export function ImportPreview({
  preview,
  modules,
  onConfirm,
  onClose,
  confirming,
}: {
  preview: ApiImportPreviewResponse;
  modules: ApiModule[];
  onConfirm: (selected: number[] | null, overrideModuleId: number | null) => void;
  onClose: () => void;
  confirming: boolean;
}) {
  const rows = useMemo(
    () => preview.items.map((item, idx) => ({ ...item, _idx: idx })),
    [preview.items],
  );
  const defaultSelected = useMemo(
    () => rows.filter((row) => IMPORTABLE_CLASSIFICATIONS.includes(row.classification)).map((row) => row._idx),
    [rows],
  );
  const [selected, setSelected] = useState<Set<number>>(() => new Set(defaultSelected));
  const [overrideModuleId, setOverrideModuleId] = useState<number | null>(null);
  const [searchText, setSearchText] = useState('');
  const [classificationFilter, setClassificationFilter] = useState<ClassificationFilter>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const visibleRows = useMemo(() => {
    const keyword = searchText.trim().toLocaleLowerCase();
    return rows.filter((row) => {
      if (classificationFilter !== 'ALL' && row.classification !== classificationFilter) return false;
      if (!keyword) return true;
      return [row.schema.name, row.schema.path, row.schema.method, row.proposed_module_name]
        .some((value) => String(value ?? '').toLocaleLowerCase().includes(keyword));
    });
  }, [rows, searchText, classificationFilter]);

  const visibleImportable = visibleRows.filter((row) => IMPORTABLE_CLASSIFICATIONS.includes(row.classification));
  const selectedVisibleCount = visibleImportable.filter((row) => selected.has(row._idx)).length;
  const allVisibleSelected = visibleImportable.length > 0 && selectedVisibleCount === visibleImportable.length;
  const someVisibleSelected = selectedVisibleCount > 0;

  const toggleVisible = (checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous);
      visibleImportable.forEach((row) => {
        if (checked) next.add(row._idx);
        else next.delete(row._idx);
      });
      return next;
    });
  };

  const toggleRow = (idx: number, checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (checked) next.add(idx);
      else next.delete(idx);
      return next;
    });
  };

  const selectedArr = Array.from(selected).sort((a, b) => a - b);
  const selectedForConfirm =
    selectedArr.length === defaultSelected.length && defaultSelected.every((idx) => selected.has(idx))
      ? null
      : selectedArr;

  const moduleOptions = modules.map((module) => ({
    label: module.is_default ? `${module.name}（默认）` : module.name,
    value: module.id,
  }));

  const columns: TableColumnsType<PreviewRow> = [
    {
      title: (
        <Checkbox
          aria-label="选择当前可导入项"
          checked={allVisibleSelected}
          indeterminate={!allVisibleSelected && someVisibleSelected}
          disabled={visibleImportable.length === 0}
          onChange={(event) => toggleVisible(event.target.checked)}
        />
      ),
      dataIndex: '_idx',
      width: 54,
      align: 'center',
      render: (_value, row) => {
        const importable = IMPORTABLE_CLASSIFICATIONS.includes(row.classification);
        return (
          <Checkbox
            aria-label={`选择 ${row.schema.method} ${row.schema.path}`}
            checked={selected.has(row._idx)}
            disabled={!importable}
            onChange={(event) => toggleRow(row._idx, event.target.checked)}
          />
        );
      },
    },
    {
      title: '处理结果',
      dataIndex: 'classification',
      width: 112,
      render: (value: ImportClassification) => (
        <Tag className="api-import-status" color={CLASSIFICATION_COLOR[value]}>
          {CLASSIFICATION_LABEL[value]}
        </Tag>
      ),
    },
    {
      title: '请求',
      key: 'request',
      width: 360,
      render: (_value, row) => (
        <div className="api-import-request-cell">
          <Tag color={METHOD_COLOR[row.schema.method] || 'default'}>{row.schema.method}</Tag>
          <Tooltip title={row.schema.path} placement="topLeft">
            <Typography.Text code className="api-import-path">{row.schema.path}</Typography.Text>
          </Tooltip>
        </div>
      ),
    },
    {
      title: '接口名称',
      dataIndex: ['schema', 'name'],
      width: 290,
      render: (_value, row) => (
        <Tooltip title={row.schema.name || '未命名接口'} placement="topLeft">
          <Typography.Text className="api-import-name" strong>
            {row.schema.name || '未命名接口'}
          </Typography.Text>
        </Tooltip>
      ),
    },
    {
      title: '推荐模块',
      dataIndex: 'proposed_module_name',
      width: 190,
      render: (value: string) => value
        ? <Tag className="api-import-module">{value}</Tag>
        : <Typography.Text type="secondary">未分类</Typography.Text>,
    },
    {
      title: '解析提示',
      dataIndex: 'warnings',
      width: 210,
      render: (warnings: string[]) => warnings?.length ? (
        <Tooltip title={warnings.join('；')} placement="topLeft">
          <Typography.Text className="api-import-warning" type="warning">
            {warnings.length === 1 ? warnings[0] : `${warnings[0]} 等 ${warnings.length} 条提示`}
          </Typography.Text>
        </Tooltip>
      ) : <Typography.Text type="secondary">—</Typography.Text>,
    },
  ];

  const summary = [
    { label: '新增', value: preview.new_count, kind: 'new' },
    { label: '有变更', value: preview.changed_count, kind: 'changed' },
    { label: '已存在', value: preview.existing_count, kind: 'existing' },
    { label: '无变化', value: preview.unchanged_count, kind: 'unchanged' },
  ];

  return (
    <div className="api-import-preview">
      <div className="api-import-preview-heading">
        <div>
          <Typography.Title level={5}>解析结果</Typography.Title>
          <Typography.Text type="secondary">
            检查接口与处理方式；预览不会写入，确认后才会保存。
          </Typography.Text>
        </div>
        <div className="api-import-preview-total">
          <span>本次识别</span>
          <strong>{preview.total}</strong>
          <span>个接口</span>
        </div>
      </div>

      <div className="api-import-summary" aria-label="解析结果统计">
        {summary.map((item) => (
          <div className={`api-import-summary-card is-${item.kind}`} key={item.kind}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      <div className="api-import-toolbar">
        <Space size={10} wrap>
          <Input
            allowClear
            value={searchText}
            onChange={(event) => {
              setSearchText(event.target.value);
              setPage(1);
            }}
            prefix={<SearchOutlined />}
            placeholder="搜索接口名称、路径或模块"
            className="api-import-search"
          />
          <Select<ClassificationFilter>
            value={classificationFilter}
            onChange={(value) => {
              setClassificationFilter(value);
              setPage(1);
            }}
            className="api-import-filter"
            options={[
              { label: '全部结果', value: 'ALL' },
              ...Object.entries(CLASSIFICATION_LABEL).map(([value, label]) => ({
                label,
                value: value as ImportClassification,
              })),
            ]}
          />
        </Space>
        <Typography.Text type="secondary" className="api-import-visible-count">
          显示 {visibleRows.length} / {preview.total} 条 · 已选 {selected.size} 条可导入项
        </Typography.Text>
      </div>

      <Table<PreviewRow>
        className="api-import-preview-table"
        rowKey={(row) => String(row._idx)}
        dataSource={visibleRows}
        columns={columns}
        pagination={preview.total > 25 ? {
          current: page,
          pageSize,
          showSizeChanger: true,
          pageSizeOptions: [25, 50, 100],
          showTotal: (total, range) => `${range[0]}–${range[1]} / ${total} 条`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPage);
            if (nextPageSize !== pageSize) setPageSize(nextPageSize);
          },
        } : false}
        scroll={{ x: 1216, y: Math.min(window.innerHeight * 0.46, 520) }}
        size="middle"
        locale={{ emptyText: searchText || classificationFilter !== 'ALL' ? '没有符合条件的接口' : '没有解析到接口' }}
      />

      <div className="api-import-preview-footer">
        <div className="api-import-module-override">
          <Select
            allowClear
            placeholder="覆盖所有已选项的目标模块"
            value={overrideModuleId ?? undefined}
            onChange={(value: number | undefined) => setOverrideModuleId(value ?? null)}
            options={moduleOptions}
            showSearch
            optionFilterProp="label"
          />
          <Typography.Text type="secondary">可选</Typography.Text>
        </div>
        <Space size={10}>
          <Button onClick={onClose}>返回</Button>
          <Button
            type="primary"
            loading={confirming}
            disabled={selected.size === 0}
            onClick={() => onConfirm(selectedForConfirm, overrideModuleId)}
          >
            确认导入 <span className="api-import-confirm-count">{selected.size}</span>
          </Button>
        </Space>
      </div>
    </div>
  );
}
