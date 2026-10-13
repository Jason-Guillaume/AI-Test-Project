// 轻量 JSON 双视图：树（antd Tree）+ 原始文本（Typography.Text copyable）。
// 不引入 monaco/codemirror 等重依赖；树由本组件自渲染。
import { useMemo, useState, type ReactNode } from 'react';
import { Segmented, Tree, Typography } from 'antd';
import { CopyOutlined } from '@ant-design/icons';

interface DataNode {
  key: string;
  title: ReactNode;
  children?: DataNode[];
}

/**
 * 把任意 JS 值转成 antd Tree 的 treeData。
 * - 对象/数组递归展开；
 * - 标量叶子显示「键: 值」，值用可复制 Typography.Text。
 */
function toTreeData(value: unknown, keyPrefix: string): DataNode[] {
  if (value === null || typeof value !== 'object') {
    return [
      {
        key: keyPrefix || 'root',
        title: (
          <Typography.Text code copyable>
            {String(value)}
          </Typography.Text>
        ),
      },
    ];
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return [{ key: keyPrefix, title: <Typography.Text type="secondary">[]（空数组）</Typography.Text> }];
    }
    return value.map((item, i) => {
      const k = `${keyPrefix}[${i}]`;
      const isBranch = item !== null && typeof item === 'object';
      const node: DataNode = {
        key: k,
        title: isBranch ? (
          <Typography.Text type="secondary">[{i}]</Typography.Text>
        ) : (
          <Typography.Text code copyable>
            {String(item)}
          </Typography.Text>
        ),
      };
      if (isBranch) node.children = toTreeData(item, k);
      return node;
    });
  }
  // 普通对象
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) {
    return [{ key: keyPrefix, title: <Typography.Text type="secondary">{'{}'}（空对象）</Typography.Text> }];
  }
  return entries.map(([k, v]) => {
    const childKey = keyPrefix ? `${keyPrefix}.${k}` : k;
    const isBranch = v !== null && typeof v === 'object';
    const node: DataNode = { key: childKey, title: <Typography.Text strong>{k}</Typography.Text> };
    if (isBranch) {
      node.title = (
        <span>
          <Typography.Text strong>{k}</Typography.Text>
          <Typography.Text type="secondary">: {Array.isArray(v) ? `[${(v as unknown[]).length}]` : '{…}'}</Typography.Text>
        </span>
      );
      node.children = toTreeData(v, childKey);
    } else {
      node.title = (
        <span>
          <Typography.Text strong>{k}</Typography.Text>
          <Typography.Text type="secondary">: </Typography.Text>
          <Typography.Text code copyable={{ text: String(v) }}>
            {String(v)}
          </Typography.Text>
        </span>
      );
    }
    return node;
  });
}

/**
 * JSON 双视图。
 *
 * 纯展示组件，不发请求：调用方传入已解析的 data 与可选 raw 文本。
 * 默认树视图，可切换为原始 JSON 文本（可复制）。
 * 解析失败时回退到原始文本视图并提示。
 */
export function JsonView({
  data,
  raw,
  height = 320,
}: {
  data: unknown; // 已解析的 JS 值
  raw?: string; // 原始 JSON 文本（用于复制与 raw 视图）
  height?: number; // 可视区高度，超出滚动
}) {
  const [mode, setMode] = useState<'tree' | 'raw'>('tree');
  const rawText = useMemo(() => raw ?? (data == null ? '' : JSON.stringify(data, null, 2)), [raw, data]);
  const treeData = useMemo(() => toTreeData(data, 'root'), [data]);

  return (
    <div>
      <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'flex-end' }}>
        <Segmented
          size="small"
          value={mode}
          onChange={(v) => setMode(v as 'tree' | 'raw')}
          options={[
            { label: '树', value: 'tree' },
            { label: '原始', value: 'raw' },
          ]}
        />
      </div>
      <div style={{ height, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
        {mode === 'tree' ? (
          treeData.length === 0 ? (
            <Typography.Text type="secondary">（空）</Typography.Text>
          ) : (
            <Tree treeData={treeData} defaultExpandAll showLine blockNode />
          )
        ) : (
          <Typography.Paragraph>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{rawText}</pre>
            <Typography.Text copyable={{ text: rawText }} style={{ fontSize: 12 }}>
              <CopyOutlined /> 复制
            </Typography.Text>
          </Typography.Paragraph>
        )}
      </div>
    </div>
  );
}
