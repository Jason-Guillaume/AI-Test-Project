// 请求参数 Tab：参数表（PATH/QUERY/HEADER/COOKIE）+ Body（json/form/multipart/raw）。
// 整体替换保存（PUT /apis/{id}/request）：参数全量替换 + body 全量替换。
import { useEffect, useState } from 'react';
import { App, Button, Card, Checkbox, Input, Select, Space, Table, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import { BODY_TYPE_OPTIONS, PARAM_LOCATION_OPTIONS } from '../constants';
import { JsonView } from '../JsonView';
import type {
  ApiBodyIn,
  ApiInterfaceDetail,
  ApiParameterIn,
  BodyType,
  ParamLocation,
} from '@/types';

// 参数本地编辑态：ApiParameterIn 去掉 schema_json（独立处理）+ schema_text 文本。
interface ParamRow {
  name: string;
  location: ParamLocation;
  type: string;
  required: boolean;
  description: string;
  example: string;
  default_value: string;
  schema_text: string;
  sort: number;
}

interface BodyState {
  body_type: BodyType;
  content_type: string;
  schema_text: string;
  raw_text: string;
}

function paramToRow(p: {
  name: string;
  location: ParamLocation;
  type?: string;
  required?: boolean;
  description?: string | null;
  example?: string | null;
  default_value?: string | null;
  schema_json?: Record<string, unknown> | null;
  sort?: number;
}): ParamRow {
  return {
    name: p.name,
    location: p.location,
    type: p.type ?? 'string',
    required: p.required ?? false,
    description: p.description ?? '',
    example: p.example ?? '',
    default_value: p.default_value ?? '',
    schema_text: p.schema_json ? JSON.stringify(p.schema_json, null, 2) : '',
    sort: p.sort ?? 0,
  };
}

function rowToParam(row: ParamRow): ApiParameterIn {
  let schema_json: Record<string, unknown> | null = null;
  if (row.schema_text.trim()) {
    try {
      schema_json = JSON.parse(row.schema_text) as Record<string, unknown>;
    } catch {
      schema_json = null;
    }
  }
  return {
    name: row.name,
    location: row.location,
    type: row.type || 'string',
    required: row.required,
    description: row.description || null,
    example: row.example || null,
    default_value: row.default_value || null,
    schema_json,
    sort: row.sort,
  };
}

/**
 * 请求参数 Tab。
 *
 * GET 拉取参数+body → 本地可编辑副本 → PUT 整体替换。
 * 参数表：行内 Input 编辑，增删行；Body：按类型切换编辑方式。
 */
export function RequestTab({ api }: { api: ApiInterfaceDetail }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [params, setParams] = useState<ParamRow[]>([]);
  const [body, setBody] = useState<BodyState>({
    body_type: 'none',
    content_type: '',
    schema_text: '',
    raw_text: '',
  });

  const query = useQuery({
    queryKey: ['api-catalog', 'api', api.id, 'request'],
    queryFn: () => apiCatalogApi.getRequest(api.id),
  });

  useEffect(() => {
    if (query.data) {
      setParams(query.data.parameters.map(paramToRow));
      const b = query.data.body;
      setBody({
        body_type: b?.body_type ?? 'none',
        content_type: b?.content_type ?? '',
        schema_text: b?.schema_json ? JSON.stringify(b.schema_json, null, 2) : '',
        raw_text: b?.raw_text ?? '',
      });
    }
  }, [query.data]);

  const saveMutation = useMutation({
    mutationFn: (payload: { parameters: ApiParameterIn[]; body: ApiBodyIn }) =>
      apiCatalogApi.saveRequest(api.id, payload),
    onSuccess: () => {
      message.success('请求已保存');
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  if (query.isPending) return <LoadingState />;
  if (query.isError)
    return <ErrorState error={query.error} onRetry={query.refetch} />;

  const updateParam = (idx: number, patch: Partial<ParamRow>) =>
    setParams((ps) => ps.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  const addParam = () =>
    setParams((ps) => [
      ...ps,
      {
        name: '',
        location: 'QUERY',
        type: 'string',
        required: false,
        description: '',
        example: '',
        default_value: '',
        schema_text: '',
        sort: ps.length,
      },
    ]);
  const removeParam = (idx: number) =>
    setParams((ps) => ps.filter((_, i) => i !== idx));

  const handleSave = async () => {
    // 参数名必填校验。
    const emptyName = params.findIndex((p) => !p.name.trim());
    if (emptyName >= 0) {
      message.error(`第 ${emptyName + 1} 个参数名为空`);
      return;
    }
    // schema_text JSON 合法性校验（参数与 body）。
    for (let i = 0; i < params.length; i++) {
      const t = params[i].schema_text.trim();
      if (t) {
        try {
          JSON.parse(t);
        } catch {
          message.error(`第 ${i + 1} 个参数的 schema JSON 不合法`);
          return;
        }
      }
    }
    const bodySchemaText = body.schema_text.trim();
    if (body.body_type !== 'none' && body.body_type !== 'raw' && bodySchemaText) {
      try {
        JSON.parse(bodySchemaText);
      } catch {
        message.error('Body schema JSON 不合法');
        return;
      }
    }

    const bodyIn: ApiBodyIn = {
      body_type: body.body_type,
      content_type: body.content_type || null,
      raw_text: body.body_type === 'raw' ? body.raw_text || null : null,
      schema_json: null,
    };
    if (body.body_type !== 'none' && body.body_type !== 'raw' && bodySchemaText) {
      bodyIn.schema_json = JSON.parse(bodySchemaText) as Record<string, unknown>;
    }

    await saveMutation.mutateAsync({
      parameters: params.map(rowToParam),
      body: bodyIn,
    });
  };

  const paramColumns = [
    {
      title: '参数名',
      dataIndex: 'name',
      width: 160,
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Input
          value={params[idx].name}
          onChange={(e) => updateParam(idx, { name: e.target.value })}
          placeholder="name"
        />
      ),
    },
    {
      title: '位置',
      dataIndex: 'location',
      width: 110,
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Select
          value={params[idx].location}
          onChange={(v: ParamLocation) => updateParam(idx, { location: v })}
          options={PARAM_LOCATION_OPTIONS}
          style={{ width: '100%' }}
        />
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 120,
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Input
          value={params[idx].type}
          onChange={(e) => updateParam(idx, { type: e.target.value })}
          placeholder="string"
        />
      ),
    },
    {
      title: '必填',
      dataIndex: 'required',
      width: 60,
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Checkbox
          checked={params[idx].required}
          onChange={(e) => updateParam(idx, { required: e.target.checked })}
        />
      ),
    },
    {
      title: '说明',
      dataIndex: 'description',
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Input
          value={params[idx].description}
          onChange={(e) => updateParam(idx, { description: e.target.value })}
          placeholder="说明"
        />
      ),
    },
    {
      title: '示例',
      dataIndex: 'example',
      width: 140,
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Input
          value={params[idx].example}
          onChange={(e) => updateParam(idx, { example: e.target.value })}
          placeholder="示例值"
        />
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 48,
      render: (_: unknown, _r: ParamRow, idx: number) => (
        <Button
          type="text"
          danger
          icon={<MinusCircleOutlined />}
          onClick={() => removeParam(idx)}
        />
      ),
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space>
        <Button type="primary" loading={saveMutation.isPending} onClick={handleSave}>
          保存
        </Button>
      </Space>

      <Card
        size="small"
        title="请求参数"
        extra={
          <Button size="small" icon={<PlusOutlined />} onClick={addParam}>
            新增参数
          </Button>
        }
      >
        <Table<ParamRow>
          rowKey={(_r, idx) => String(idx)}
          columns={paramColumns}
          dataSource={params}
          pagination={false}
          size="small"
          locale={{ emptyText: '暂无参数' }}
        />
      </Card>

      <Card size="small" title="请求体">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space wrap>
            <Select
              value={body.body_type}
              onChange={(v: BodyType) => setBody((b) => ({ ...b, body_type: v }))}
              options={BODY_TYPE_OPTIONS}
              style={{ width: 140 }}
            />
            <Input
              value={body.content_type}
              onChange={(e) => setBody((b) => ({ ...b, content_type: e.target.value }))}
              placeholder="application/json"
              style={{ width: 240 }}
            />
          </Space>

          {body.body_type === 'none' && (
            <Typography.Text type="secondary">无请求体</Typography.Text>
          )}

          {body.body_type === 'raw' && (
            <>
              <Typography.Text type="secondary">原始文本</Typography.Text>
              <Input.TextArea
                rows={8}
                value={body.raw_text}
                onChange={(e) => setBody((b) => ({ ...b, raw_text: e.target.value }))}
                placeholder="<raw body>"
                style={{ fontFamily: 'monospace' }}
              />
            </>
          )}

          {body.body_type !== 'none' && body.body_type !== 'raw' && (
            <>
              <Typography.Text type="secondary">
                {body.body_type === 'json' ? 'JSON Schema' : `${body.body_type} 字段结构（JSON）`}
              </Typography.Text>
              <Input.TextArea
                rows={8}
                value={body.schema_text}
                onChange={(e) => setBody((b) => ({ ...b, schema_text: e.target.value }))}
                placeholder={
                  body.body_type === 'json'
                    ? '{"type":"object","properties":{...}}'
                    : '[{"name":"file","type":"string","required":true}]'
                }
                style={{ fontFamily: 'monospace' }}
              />
              {body.schema_text.trim() && (() => {
                try {
                  return (
                    <JsonView
                      data={JSON.parse(body.schema_text)}
                      raw={body.schema_text}
                      height={220}
                    />
                  );
                } catch {
                  return <Typography.Text type="danger">schema JSON 不合法</Typography.Text>;
                }
              })()}
            </>
          )}
        </Space>
      </Card>
    </Space>
  );
}
