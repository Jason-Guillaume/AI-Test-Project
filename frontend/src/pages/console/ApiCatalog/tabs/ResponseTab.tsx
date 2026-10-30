// 响应结构 Tab：按 status_code 维护响应列表，整体替换保存（PUT /apis/{id}/responses）。
// 每条响应：status_code / description / schema_json（JSON 文本编辑）/ example_json。
import { useEffect, useState } from 'react';
import { App, Button, Card, Empty, Input, InputNumber, Space, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { JsonView } from '../JsonView';
import type { ApiInterfaceDetail, ApiResponseIn } from '@/features/api-catalog/contracts';


// 一条响应的本地编辑态：schema/example 用文本编辑，保存时解析。
interface ResponseRow {
  status_code: number;
  description: string;
  schema_text: string;
  example_text: string;
}

function rowFrom(p: {
  status_code: number;
  description?: string | null;
  schema_json?: Record<string, unknown> | null;
  example_json?: string | null;
}): ResponseRow {
  return {
    status_code: p.status_code,
    description: p.description ?? '',
    schema_text: p.schema_json ? JSON.stringify(p.schema_json, null, 2) : '',
    example_text: p.example_json ?? '',
  };
}

function rowToIn(row: ResponseRow): ApiResponseIn {
  let schema_json: Record<string, unknown> | null = null;
  if (row.schema_text.trim()) {
    try {
      schema_json = JSON.parse(row.schema_text) as Record<string, unknown>;
    } catch {
      // 解析失败时 schema 留空，由调用方在保存前校验；这里不抛，避免阻塞其余条目。
      schema_json = null;
    }
  }
  return {
    status_code: row.status_code,
    description: row.description || null,
    schema_json,
    example_json: row.example_text || null,
  };
}

/**
 * 响应结构 Tab。
 *
 * GET 拉取响应列表 → 本地可编辑副本（增删行）→ PUT 整体替换。
 * 保存前校验 schema_text 是否合法 JSON；非法则 message.error 并中止。
 */
export function ResponseTab({ api }: { api: ApiInterfaceDetail }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<ResponseRow[]>([]);

  const query = useQuery({
    queryKey: ['api-catalog', 'api', api.id, 'responses'],
    queryFn: () => apiCatalogApi.getResponses(api.id),
  });

  // 接口切换或数据刷新时同步本地编辑态。
  useEffect(() => {
    if (query.data) {
      setRows(query.data.responses.map(rowFrom));
    }
  }, [query.data]);

  const saveMutation = useMutation({
    mutationFn: (body: { responses: ApiResponseIn[] }) =>
      apiCatalogApi.saveResponses(api.id, body),
    onSuccess: () => {
      message.success('响应已保存');
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  if (query.isPending) return <LoadingState />;
  if (query.isError)
    return <ErrorState error={query.error} onRetry={query.refetch} />;

  const updateRow = (idx: number, patch: Partial<ResponseRow>) =>
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const addRow = () =>
    setRows((rs) => [
      ...rs,
      { status_code: 200, description: '', schema_text: '', example_text: '' },
    ]);
  const removeRow = (idx: number) =>
    setRows((rs) => rs.filter((_, i) => i !== idx));

  const handleSave = async () => {
    // 校验所有 schema_text 是否合法 JSON（非空时）。
    for (let i = 0; i < rows.length; i++) {
      const t = rows[i].schema_text.trim();
      if (t) {
        try {
          JSON.parse(t);
        } catch {
          message.error(`第 ${i + 1} 条响应的 schema JSON 不合法`);
          return;
        }
      }
    }
    await saveMutation.mutateAsync({
      responses: rows.map(rowToIn),
    });
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space>
        <Button icon={<PlusOutlined />} onClick={addRow}>
          新增响应
        </Button>
        <Button
          type="primary"
          loading={saveMutation.isPending}
          onClick={handleSave}
          disabled={rows.length === 0}
        >
          保存
        </Button>
      </Space>

      {rows.length === 0 ? (
        <Empty description="暂无响应，点击「新增响应」添加" />
      ) : (
        rows.map((row, idx) => (
          <Card
            key={idx}
            size="small"
            title={
              <Space>
                <InputNumber
                  min={100}
                  max={599}
                  value={row.status_code}
                  onChange={(v) =>
                    updateRow(idx, { status_code: v ?? 200 })
                  }
                  style={{ width: 90 }}
                />
                <Input
                  placeholder="响应说明"
                  value={row.description}
                  onChange={(e) =>
                    updateRow(idx, { description: e.target.value })
                  }
                  style={{ width: 260 }}
                />
              </Space>
            }
            extra={
              <Button
                size="small"
                type="text"
                danger
                icon={<MinusCircleOutlined />}
                onClick={() => removeRow(idx)}
              />
            }
          >
            <Typography.Text type="secondary">响应结构（JSON）</Typography.Text>
            <Input.TextArea
              rows={6}
              value={row.schema_text}
              onChange={(e) => updateRow(idx, { schema_text: e.target.value })}
              placeholder='{"type":"object","properties":{...}}'
              style={{ fontFamily: 'monospace', marginBottom: 12 }}
            />
            {row.schema_text.trim() && (() => {
              try {
                return <JsonView data={JSON.parse(row.schema_text)} raw={row.schema_text} height={200} />;
              } catch {
                return <Typography.Text type="danger">schema JSON 不合法</Typography.Text>;
              }
            })()}
            <div style={{ marginTop: 12 }}>
              <Typography.Text type="secondary">示例响应体</Typography.Text>
              <Input.TextArea
                rows={4}
                value={row.example_text}
                onChange={(e) =>
                  updateRow(idx, { example_text: e.target.value })
                }
                placeholder='{"id":1,"title":"..."}'
                style={{ fontFamily: 'monospace' }}
              />
            </div>
          </Card>
        ))
      )}
    </Space>
  );
}
