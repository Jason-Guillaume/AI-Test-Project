// 用例级断言列表。
//
// 字段契约逐生产者核对过，不靠猜：
// - assertion_engine.py:142-151 → {id, assertion_type, operator, passed, actual, expected, required, message}
// - playwright_executor.py:232  → assertion_type 形如 "WEB_URL"，message 为「页面断言通过/失败」
// - security_testing/runtime/runner.py:975 → {"name": "security", passed, message}，无 operator/expected/actual
//
// 没有任何生产者写 path：历史版本渲染的「断言路径」列恒为空却带着列头，比不显示更误导。
// 真正有区分力的是 assertion_type（STATUS_CODE / JSON_PATH / HEADER / RESPONSE_TIME / WEB_*），
// 安全扫描行退回 name。message 是三个生产者唯一都有的字段，安全行只有它携带内容，
// 所以必须单独成列而不是塞进 tooltip。
//
// 字典里没有 step 索引，无法确证断言归属哪一步，因此只能作为「用例级断言列表」展示，
// 不能挂到某个具体步骤上。
//
// 失败行：整行红底 + 实际值红色高亮，让人一眼看出差异。

import { Empty, Table, Tag, theme, Typography } from 'antd';
import type { TableColumnsType } from 'antd';

interface AssertionRow {
  /** 断言类型：引擎与 Web 写 assertion_type，安全扫描写 name */
  type: string;
  operator: string;
  expected: unknown;
  actual: unknown;
  /** 生产者写入的可读说明；可能为空字符串 */
  message: string;
  /** required === false 表示软断言，不阻断用例最终状态 */
  soft: boolean;
  passed: boolean;
}

interface AssertionViewerProps {
  /** 断言结果；为空或 null 时显示空态 */
  rows: Array<Record<string, unknown>> | null | undefined;
  /** 空态文案 */
  emptyText?: string;
}

/**
 * 把一行断言记录安全转成 UI 展示结构。
 *
 * type 优先取 assertion_type，缺失时退回 name（安全扫描行只有 name）；
 * operator 缺失退回 '-'；expected / actual 可能任意类型（含 null）用 `?? '-'` 兜底，
 * 注意 expected 可能是合法的空串（CONTAINS 断言），`??` 不会吞掉它。
 * soft 只在后端显式写 required: false 时为真；缺字段不推断成硬断言。
 */
function toRow(row: Record<string, unknown>): AssertionRow {
  return {
    type: typeof row.assertion_type === 'string'
      ? row.assertion_type
      : typeof row.name === 'string'
        ? row.name
        : '-',
    operator: typeof row.operator === 'string' ? row.operator : '-',
    expected: row.expected ?? '-',
    actual: row.actual ?? '-',
    message: typeof row.message === 'string' ? row.message : '',
    soft: row.required === false,
    passed: row.passed === true,
  };
}

function toDisplay(v: unknown): string {
  if (v == null) return '-';
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/**
 * 断言查看器。
 *
 * 列顺序按排障动线排列：先认断言类型（状态码 / JSON 路径 / 响应时间 / Web 页面断言），
 * 再看操作符与期望/实际，最后是生产者写的可读说明。
 * 期望/实际列使用 <code> 展示；失败行整行红底、实际值红色高亮以突出差异。
 * 断言字典里没有 step 索引，所以只做「用例级列表」展示，不做归属推断。
 */
export function AssertionViewer({ rows, emptyText = '无断言结果' }: AssertionViewerProps) {
  const { token } = theme.useToken();
  const list = (rows ?? []).map(toRow);

  if (list.length === 0) {
    return (
      <div style={{ padding: token.padding }}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
      </div>
    );
  }

  const columns: TableColumnsType<AssertionRow> = [
    {
      title: '类型',
      dataIndex: 'type',
      width: 124,
      render: (v: string) => (
        <Typography.Text code style={{ fontSize: token.fontSizeSM, wordBreak: 'break-all' }}>
          {v}
        </Typography.Text>
      ),
    },
    {
      title: '操作符',
      dataIndex: 'operator',
      width: 84,
      render: (v: string) => <Typography.Text code style={{ fontSize: token.fontSizeSM }}>{v}</Typography.Text>,
    },
    {
      title: '期望',
      dataIndex: 'expected',
      render: (v: unknown) => (
        <Typography.Text code style={{ fontSize: token.fontSizeSM, wordBreak: 'break-all' }}>
          {toDisplay(v)}
        </Typography.Text>
      ),
    },
    {
      title: '实际',
      dataIndex: 'actual',
      render: (v: unknown, record: AssertionRow) => {
        // 期望与实际不同且断言失败：把实际值标红，作为差异线索。
        const failedAndDiff = !record.passed && toDisplay(v) !== toDisplay(record.expected);
        return (
          <Typography.Text
            code
            style={{
              fontSize: token.fontSizeSM,
              wordBreak: 'break-all',
              color: failedAndDiff ? token.colorError : undefined,
            }}
          >
            {toDisplay(v)}
          </Typography.Text>
        );
      },
    },
    {
      title: '说明',
      dataIndex: 'message',
      render: (v: string) => (
        <Typography.Text
          type="secondary"
          title={v || undefined}
          style={{ fontSize: token.fontSizeSM, wordBreak: 'break-all' }}
        >
          {v || '-'}
        </Typography.Text>
      ),
    },
    {
      title: '结果',
      dataIndex: 'passed',
      width: 96,
      render: (v: boolean, record: AssertionRow) => (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: token.marginXXS }}>
          {v ? (
            <span style={{ color: token.colorSuccess, fontSize: token.fontSizeSM }}>通过</span>
          ) : (
            <span style={{ color: token.colorError, fontSize: token.fontSizeSM }}>失败</span>
          )}
          {/* 软断言不阻断用例状态（后端 required_all_passed 只看 required 为真的项） */}
          {record.soft && (
            <Tag bordered={false} color="default" style={{ fontSize: token.fontSizeSM, paddingInline: 4 }}>
              软
            </Tag>
          )}
        </span>
      ),
    },
  ];

  return (
    <Table
      rowKey={(_, index) => String(index)}
      size="small"
      pagination={false}
      columns={columns}
      dataSource={list}
      onRow={(record) => ({
        style: record.passed ? undefined : { background: token.colorErrorBg },
      })}
    />
  );
}

/**
 * 断言差异展示：把期望与实际并排列出。
 *
 * 断言字典里没有 step 索引，无法确证归属，所以只在整个用例层面渲染。
 */
export function AssertionDiff({ expected, actual }: { expected: unknown; actual: unknown }) {
  const { token } = theme.useToken();
  const text = (v: unknown): string => {
    if (v == null) return '-';
    if (typeof v === 'string') return v;
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  };

  const e = text(expected);
  const a = text(actual);
  const diff = e !== a;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '48px 1fr',
        gap: token.marginXS,
        fontSize: token.fontSizeSM,
        padding: token.paddingXS,
        background: diff ? token.colorErrorBg : token.colorFillQuaternary,
        borderRadius: token.borderRadiusSM,
        border: `1px solid ${diff ? token.colorErrorBorder : token.colorBorderSecondary}`,
      }}
    >
      <span style={{ color: token.colorTextTertiary }}>期望</span>
      <Typography.Text code style={{ wordBreak: 'break-all' }}>{e}</Typography.Text>
      <span style={{ color: token.colorTextTertiary }}>实际</span>
      <Typography.Text
        code
        style={{ wordBreak: 'break-all', color: diff ? token.colorError : undefined }}
      >
        {a}
      </Typography.Text>
    </div>
  );
}

export type { AssertionViewerProps, AssertionRow };
