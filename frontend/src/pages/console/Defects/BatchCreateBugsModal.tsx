// 批量创建缺陷弹窗组件。
// 提供结构化可编辑表格录入全部缺陷字段（标题、前后端划分、严重度、状态、描述、复现步骤、环境、处理人），
// 同时支持顶部统一预设默认值、复制行，以及粘贴多行文本一键拆分为结构化表格行后再微调。
// 提交走 POST /bugs/batch 原子事务接口，任意一行出错整批不入库并精确高亮出错行号与原因。

import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Collapse,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useMemo, useRef, useState } from 'react';
import { bugsApi } from '@/features/defects/api/defects';
import {
  applyDefaultsToRows,
  createDraftRow,
  extractServerRowErrors,
  isPristineEmptyRow,
  MAX_BATCH_BUG_ROWS,
  parseBatchDefectLines,
  validateBatchDefectRows,
  type BatchDefectDefaults,
  type BatchDefectDraftRow,
} from '@/features/defects/batchCreateUtils.mjs';
import type {
  BugBatchCreate,
  BugBatchRowError,
  BugCategory,
  BugSeverity,
  BugStatus,
} from '@/features/defects/contracts';
import { projectsApi } from '@/features/projects/api/projects';
import { extractErrorBody, getErrorMessage } from '@/shared/api/client';
import { collectPages } from '@/shared/api/pagination';
import { CATEGORY_OPTIONS, SEVERITY_OPTIONS, STATUS_OPTIONS } from './constants';

interface BatchCreateBugsModalProps {
  initialProjectId?: number;
  initialCategory?: BugCategory;
  projectOptions: { label: string; value: number }[];
  onClose: () => void;
  onCreated: (createdCount: number) => void;
}

/**
 * 批量创建缺陷弹窗（挂载即全新状态，关闭即销毁）。
 *
 * 会发请求：
 *   - useQuery ['project', selectedProjectId, 'members'] 拉当前选定项目的成员列表（供处理人选择）；
 *   - useMutation bugsApi.createBatch 整批原子提交；成功后 invalidate ['bugs']。
 * 失败呈现：保留全部当前编辑行，按行号展示校验提示，不丢失用户输入。
 */
export function BatchCreateBugsModal({
  initialProjectId,
  initialCategory,
  projectOptions,
  onClose,
  onCreated,
}: BatchCreateBugsModalProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const rowSeqRef = useRef(1);
  const nextRowKey = () => {
    rowSeqRef.current += 1;
    return `batch-bug-${rowSeqRef.current}`;
  };

  const [selectedProjectId, setSelectedProjectId] = useState<number | undefined>(
    initialProjectId ?? projectOptions[0]?.value,
  );
  const [defaults, setDefaults] = useState<BatchDefectDefaults>({
    category: initialCategory,
    severity: 2,
    status: '待确认',
    environment: '',
    assignee_id: null,
  });
  const [rows, setRows] = useState<BatchDefectDraftRow[]>(() => [
    createDraftRow(
      {
        category: initialCategory,
        severity: 2,
        status: '待确认',
        environment: '',
        assignee_id: null,
      },
      'batch-bug-1',
    ),
  ]);
  const [pasteText, setPasteText] = useState('');
  const [pastePanelKeys, setPastePanelKeys] = useState<string[]>([]);
  const [rowErrors, setRowErrors] = useState<BugBatchRowError[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // 拉取目标项目的成员列表，用于「默认处理人」与逐行「处理人」下拉。
  const membersQuery = useQuery({
    queryKey: ['project', selectedProjectId, 'members'],
    queryFn: () =>
      collectPages((page) =>
        projectsApi.listMembers(selectedProjectId!, { page, page_size: 200 }),
      ),
    enabled: selectedProjectId != null,
  });

  const memberOptions = useMemo(
    () =>
      (membersQuery.data?.items ?? []).map((member) => {
        const item = member as { user_id: number; username?: string };
        return {
          label: item.username ?? `用户 ${item.user_id}`,
          value: item.user_id,
        };
      }),
    [membersQuery.data],
  );

  // 批量创建：成功刷新缺陷列表；失败保留表单并高亮服务端返回的行号错误。
  const batchMutation = useMutation({
    mutationFn: (body: BugBatchCreate) => bugsApi.createBatch(body),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['bugs'] }); // 批量入库后刷新所有筛选分页列表
      message.success(`已成功批量创建 ${result.created_count} 条缺陷`);
      onCreated(result.created_count);
    },
    onError: (error) => {
      const body = extractErrorBody(error);
      const serverErrors = extractServerRowErrors(body);
      if (serverErrors.length > 0) {
        setRowErrors(serverErrors);
      }
      setSubmitError(getErrorMessage(error, '批量创建失败'));
    },
  });

  /** 切换目标项目时清空处理人绑定，防止把旧项目成员带入新项目校验失败。 */
  const handleProjectChange = (nextProjectId: number) => {
    setSelectedProjectId(nextProjectId);
    setDefaults((prev) => ({ ...prev, assignee_id: null }));
    setRows((prev) => prev.map((row) => ({ ...row, assignee_id: null })));
    setRowErrors([]);
    setSubmitError(null);
  };

  /** 更新单行字段，同时清除该行该字段的历史错误提示。 */
  const updateRow = <K extends keyof BatchDefectDraftRow>(
    rowKey: string,
    rowIndex: number,
    field: K,
    value: BatchDefectDraftRow[K],
  ) => {
    setRows((prev) =>
      prev.map((row) => (row.key === rowKey ? { ...row, [field]: value } : row)),
    );
    const rowNo = rowIndex + 1;
    setRowErrors((prev) =>
      prev.filter((err) => !(err.row === rowNo && err.field === field)),
    );
    setSubmitError(null);
  };

  /** 在表格末尾追加指定数量的新行（受单次 100 条上限约束）。 */
  const appendEmptyRows = (count: number) => {
    const remaining = MAX_BATCH_BUG_ROWS - rows.length;
    if (remaining <= 0) {
      message.warning(`单次最多批量创建 ${MAX_BATCH_BUG_ROWS} 条缺陷`);
      return;
    }
    const actualCount = Math.min(count, remaining);
    const additions = Array.from({ length: actualCount }, () =>
      createDraftRow(defaults, nextRowKey()),
    );
    setRows((prev) => [...prev, ...additions]);
  };

  /** 复制指定行到其紧邻下方，方便快速录入同模块/同环境缺陷。 */
  const duplicateRow = (index: number) => {
    if (rows.length >= MAX_BATCH_BUG_ROWS) {
      message.warning(`单次最多批量创建 ${MAX_BATCH_BUG_ROWS} 条缺陷`);
      return;
    }
    const source = rows[index];
    if (!source) return;
    const cloned: BatchDefectDraftRow = { ...source, key: nextRowKey() };
    setRows((prev) => [
      ...prev.slice(0, index + 1),
      cloned,
      ...prev.slice(index + 1),
    ]);
    setRowErrors([]);
    setSubmitError(null);
  };

  /** 删除指定行（至少保留 1 行以便继续编辑）。 */
  const removeRow = (rowKey: string) => {
    if (rows.length <= 1) return;
    setRows((prev) => prev.filter((row) => row.key !== rowKey));
    setRowErrors([]);
    setSubmitError(null);
  };

  /** 把多行粘贴文本解析成结构化表格行；若当前仅有一行空白行则自动替换掉。 */
  const handleParseText = () => {
    const parsed = parseBatchDefectLines(pasteText, defaults, () => nextRowKey());
    if (parsed.length === 0) {
      message.warning('请先粘贴至少一行有效内容');
      return;
    }
    const baseRows =
      rows.length === 1 && isPristineEmptyRow(rows[0]) ? [] : rows;
    if (baseRows.length + parsed.length > MAX_BATCH_BUG_ROWS) {
      message.error(
        `拆分后共 ${baseRows.length + parsed.length} 条，超过单次 ${MAX_BATCH_BUG_ROWS} 条上限，请分批录入`,
      );
      return;
    }
    setRows([...baseRows, ...parsed]);
    setPasteText('');
    setPastePanelKeys([]); // 拆分完成后收起粘贴区，突出下方结构化表格
    setRowErrors([]);
    setSubmitError(null);
    message.success(`已拆分为 ${parsed.length} 行，请在下方表格补充或微调字段`);
  };

  /** 将顶部默认配置应用到全部行。 */
  const handleApplyDefaults = (mode: 'fillEmpty' | 'overwrite') => {
    setRows((prev) => applyDefaultsToRows(prev, defaults, mode));
    setRowErrors([]);
    setSubmitError(null);
    message.success(
      mode === 'overwrite' ? '已将预设默认值应用到全部行' : '已为未填写归属/环境/处理人的行补齐默认值',
    );
  };

  /** 提交前先在前端校验全部行，通过后再触发原子批量请求。 */
  const handleSubmit = () => {
    if (selectedProjectId == null) {
      message.error('请先选择所属项目');
      return;
    }
    const validation = validateBatchDefectRows(rows);
    if (!validation.valid) {
      setRowErrors(validation.errors);
      setSubmitError('请先修正下方标红行的必填项或长度限制后再提交');
      return;
    }
    setRowErrors([]);
    setSubmitError(null);
    batchMutation.mutate({
      project_id: selectedProjectId,
      items: validation.items,
    });
  };

  const errorsByRow = useMemo(() => {
    const map = new Map<number, BugBatchRowError[]>();
    for (const err of rowErrors) {
      const list = map.get(err.row) ?? [];
      list.push(err);
      map.set(err.row, list);
    }
    return map;
  }, [rowErrors]);

  const hasFieldError = (rowNo: number, field: string) =>
    (errorsByRow.get(rowNo) ?? []).some((err) => err.field === field);

  const columns: ColumnsType<BatchDefectDraftRow> = [
    {
      title: '行',
      key: 'index',
      width: 56,
      fixed: 'left',
      render: (_value, _row, index) => {
        const rowNo = index + 1;
        const rowErrs = errorsByRow.get(rowNo);
        return rowErrs?.length ? (
          <Tag color="red" title={rowErrs.map((e) => e.message).join('；')}>
            #{rowNo}
          </Tag>
        ) : (
          <Typography.Text type="secondary">#{rowNo}</Typography.Text>
        );
      },
    },
    {
      title: '前后端 *',
      key: 'category',
      width: 108,
      render: (_value, row, index) => (
        <Select<BugCategory>
          aria-label={`第 ${index + 1} 行前后端划分`}
          placeholder="必选"
          options={CATEGORY_OPTIONS}
          value={row.category}
          status={hasFieldError(index + 1, 'category') ? 'error' : undefined}
          onChange={(val) => updateRow(row.key, index, 'category', val)}
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '标题 *',
      key: 'title',
      width: 220,
      render: (_value, row, index) => (
        <Input
          aria-label={`第 ${index + 1} 行标题`}
          placeholder="一句话描述问题"
          maxLength={200}
          value={row.title}
          status={hasFieldError(index + 1, 'title') ? 'error' : undefined}
          onChange={(event) =>
            updateRow(row.key, index, 'title', event.target.value)
          }
        />
      ),
    },
    {
      title: '严重度',
      key: 'severity',
      width: 110,
      render: (_value, row, index) => (
        <Select<BugSeverity>
          aria-label={`第 ${index + 1} 行严重度`}
          options={SEVERITY_OPTIONS}
          value={row.severity}
          onChange={(val) => updateRow(row.key, index, 'severity', val)}
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 108,
      render: (_value, row, index) => (
        <Select<BugStatus>
          aria-label={`第 ${index + 1} 行状态`}
          options={STATUS_OPTIONS}
          value={row.status}
          onChange={(val) => updateRow(row.key, index, 'status', val)}
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '缺陷描述',
      key: 'description',
      width: 210,
      render: (_value, row, index) => (
        <Input.TextArea
          aria-label={`第 ${index + 1} 行缺陷描述`}
          placeholder="详细描述问题现象"
          autoSize={{ minRows: 1, maxRows: 3 }}
          maxLength={1000}
          value={row.description}
          status={hasFieldError(index + 1, 'description') ? 'error' : undefined}
          onChange={(event) =>
            updateRow(row.key, index, 'description', event.target.value)
          }
        />
      ),
    },
    {
      title: '复现步骤',
      key: 'steps_to_reproduce',
      width: 210,
      render: (_value, row, index) => (
        <Input.TextArea
          aria-label={`第 ${index + 1} 行复现步骤`}
          placeholder={'1. 打开页面\n2. 触发异常'}
          autoSize={{ minRows: 1, maxRows: 3 }}
          value={row.steps_to_reproduce}
          onChange={(event) =>
            updateRow(row.key, index, 'steps_to_reproduce', event.target.value)
          }
        />
      ),
    },
    {
      title: '发现环境',
      key: 'environment',
      width: 120,
      render: (_value, row, index) => (
        <Input
          aria-label={`第 ${index + 1} 行发现环境`}
          placeholder="dev / test"
          maxLength={200}
          value={row.environment}
          status={hasFieldError(index + 1, 'environment') ? 'error' : undefined}
          onChange={(event) =>
            updateRow(row.key, index, 'environment', event.target.value)
          }
        />
      ),
    },
    {
      title: '处理人',
      key: 'assignee_id',
      width: 140,
      render: (_value, row, index) => (
        <Select<number | null>
          aria-label={`第 ${index + 1} 行处理人`}
          placeholder="未分配"
          allowClear
          showSearch
          optionFilterProp="label"
          loading={membersQuery.isPending}
          options={memberOptions}
          value={row.assignee_id ?? undefined}
          status={hasFieldError(index + 1, 'assignee_id') ? 'error' : undefined}
          onChange={(val) =>
            updateRow(row.key, index, 'assignee_id', val ?? null)
          }
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 84,
      fixed: 'right',
      render: (_value, row, index) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<CopyOutlined />}
            title="复制此行到下方"
            aria-label={`复制第 ${index + 1} 行`}
            disabled={rows.length >= MAX_BATCH_BUG_ROWS}
            onClick={() => duplicateRow(index)}
          />
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            title="删除此行"
            aria-label={`删除第 ${index + 1} 行`}
            disabled={rows.length <= 1}
            onClick={() => removeRow(row.key)}
          />
        </Space>
      ),
    },
  ];

  return (
    <Modal
      open
      centered
      title="批量创建缺陷"
      width="min(1260px, 96vw)"
      styles={{ body: { maxHeight: 'calc(100dvh - 180px)', overflowY: 'auto' } }}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={batchMutation.isPending}
      okText={`确认批量创建（${rows.length} 条）`}
      cancelText="取消"
      maskClosable={false}
      keyboard={false}
      closable={!batchMutation.isPending}
      destroyOnHidden
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {/* 顶部项目选择与统一默认值预设区 */}
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            background: 'rgba(0, 0, 0, 0.02)',
            border: '1px solid rgba(0, 0, 0, 0.06)',
          }}
        >
          <Space wrap size={[12, 8]} style={{ width: '100%' }}>
            <Space size={6}>
              <Typography.Text strong>所属项目：</Typography.Text>
              <Select
                aria-label="批量创建所属项目"
                showSearch
                optionFilterProp="label"
                placeholder="请选择项目"
                options={projectOptions}
                value={selectedProjectId}
                onChange={handleProjectChange}
                style={{ minWidth: 180 }}
              />
            </Space>
            <Space size={6}>
              <Typography.Text type="secondary">默认前后端：</Typography.Text>
              <Select<BugCategory>
                aria-label="默认前后端划分"
                allowClear
                placeholder="不预设"
                options={CATEGORY_OPTIONS}
                value={defaults.category}
                onChange={(val) =>
                  setDefaults((prev) => ({ ...prev, category: val }))
                }
                style={{ width: 108 }}
              />
            </Space>
            <Space size={6}>
              <Typography.Text type="secondary">默认严重度：</Typography.Text>
              <Select<BugSeverity>
                aria-label="默认严重度"
                options={SEVERITY_OPTIONS}
                value={defaults.severity}
                onChange={(val) =>
                  setDefaults((prev) => ({ ...prev, severity: val }))
                }
                style={{ width: 96 }}
              />
            </Space>
            <Space size={6}>
              <Typography.Text type="secondary">默认状态：</Typography.Text>
              <Select<BugStatus>
                aria-label="默认状态"
                options={STATUS_OPTIONS}
                value={defaults.status}
                onChange={(val) =>
                  setDefaults((prev) => ({ ...prev, status: val }))
                }
                style={{ width: 106 }}
              />
            </Space>
            <Space size={6}>
              <Typography.Text type="secondary">默认环境：</Typography.Text>
              <Input
                aria-label="默认环境"
                placeholder="如 test"
                maxLength={200}
                value={defaults.environment}
                onChange={(event) =>
                  setDefaults((prev) => ({
                    ...prev,
                    environment: event.target.value,
                  }))
                }
                style={{ width: 110 }}
              />
            </Space>
            <Space size={6}>
              <Typography.Text type="secondary">默认处理人：</Typography.Text>
              <Select<number | null>
                aria-label="默认处理人"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="未分配"
                loading={membersQuery.isPending}
                options={memberOptions}
                value={defaults.assignee_id ?? undefined}
                onChange={(val) =>
                  setDefaults((prev) => ({ ...prev, assignee_id: val ?? null }))
                }
                style={{ width: 136 }}
              />
            </Space>
            <Space size={6}>
              <Button size="small" onClick={() => handleApplyDefaults('fillEmpty')}>
                仅补齐空字段
              </Button>
              <Button size="small" onClick={() => handleApplyDefaults('overwrite')}>
                覆盖应用到全部行
              </Button>
            </Space>
          </Space>
        </div>

        {/* 可折叠的文本快速拆分辅助区：避免退化成“只有标题框”，拆分后仍在下方表格逐字段编辑 */}
        <Collapse
          size="small"
          activeKey={pastePanelKeys}
          onChange={(keys) =>
            setPastePanelKeys(Array.isArray(keys) ? keys.map(String) : [String(keys)])
          }
          items={[
            {
              key: 'quick-paste',
              label:
                '粘贴多行文本快速拆分（可选：支持纯标题逐行粘贴，或用「|」/ Tab 分隔：标题 | 前端/后端 | 严重度 | 描述 | 复现步骤 | 环境）',
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Input.TextArea
                    aria-label="多行文本快速拆分输入"
                    rows={4}
                    value={pasteText}
                    onChange={(event) => setPasteText(event.target.value)}
                    placeholder={
                      '示例 1（仅标题，自动套用上方默认配置）：\n登录按钮点击无响应\n\n示例 2（多字段「|」分隔）：\n下单接口返回 500 | 后端 | 严重 | 提交订单报空指针 | 1. 加入购物车\\n2. 提交订单 | test'
                    }
                  />
                  <Space>
                    <Button type="primary" size="small" onClick={handleParseText}>
                      拆分为下方表格行
                    </Button>
                    <Typography.Text type="secondary">
                      拆分后可在下方表格继续补充或逐行修改全部字段（步骤中可用 \n 表示换行）
                    </Typography.Text>
                  </Space>
                </Space>
              ),
            },
          ]}
        />

        {/* 错误提示区：展示原子校验定位信息 */}
        {(submitError || rowErrors.length > 0) && (
          <Alert
            type="error"
            showIcon
            message={submitError || '存在未通过校验的缺陷行'}
            description={
              rowErrors.length > 0 ? (
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {rowErrors.slice(0, 8).map((err, idx) => (
                    <li key={`${err.row}-${err.field}-${idx}`}>
                      第 {err.row} 行：{err.message}
                    </li>
                  ))}
                  {rowErrors.length > 8 && (
                    <li>另有 {rowErrors.length - 8} 项错误，请检查标红行</li>
                  )}
                </ul>
              ) : undefined
            }
          />
        )}

        {/* 主体结构化可编辑表格 */}
        <Table<BatchDefectDraftRow>
          size="small"
          rowKey="key"
          pagination={false}
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1400 }}
        />

        {/* 表格底部增行控制栏 */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <Space wrap>
            <Button
              icon={<PlusOutlined />}
              disabled={rows.length >= MAX_BATCH_BUG_ROWS}
              onClick={() => appendEmptyRows(1)}
            >
              添加一行
            </Button>
            <Button
              disabled={rows.length >= MAX_BATCH_BUG_ROWS}
              onClick={() => appendEmptyRows(5)}
            >
              批量添加 5 行
            </Button>
          </Space>
          <Typography.Text type="secondary">
            当前共 {rows.length} / {MAX_BATCH_BUG_ROWS} 条；整批原子提交，任一行失败则整批不入库
          </Typography.Text>
        </div>
      </Space>
    </Modal>
  );
}
