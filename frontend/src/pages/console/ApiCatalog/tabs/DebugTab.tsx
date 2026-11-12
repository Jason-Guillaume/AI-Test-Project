// 调试 Tab：仅平台管理员可用。使用项目 Environment 发送真实请求，强制校验出站白名单。
// 失败（403 目标不在白名单 / 404）由 message.error 展示；成功展示 status/body/headers/耗时。
import { useMemo, useState } from 'react';
import { Alert, App, Button, Card, Input, InputNumber, Select, Space, Tag, Typography } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useQuery } from '@tanstack/react-query';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { projectsApi } from '@/features/projects/api/projects';
import { getErrorMessage } from '@/shared/api/client';
import { useAuth } from '@/app/providers/AuthProvider';
import { LoadingState } from '@/shared/ui/PageState';
import { JsonView } from '../JsonView';
import type { ApiDebugRequest, ApiDebugResult, ApiInterfaceDetail } from '@/features/api-catalog/contracts';


interface KV {
  key: string;
  value: string;
}

// 把接口的 PATH/QUERY 参数预填为键值对，供用户覆盖。
function prefillKv(
  api: ApiInterfaceDetail,
  location: 'PATH' | 'QUERY',
): KV[] {
  return api.parameters
    .filter((p) => p.location === location)
    .map((p) => ({ key: p.name, value: p.example ?? p.default_value ?? '' }));
}

/**
 * 调试 Tab。
 *
 * 权限：非平台管理员只读提示，不展示表单。
 * 查询：当前项目已启用的环境列表（不包含项目默认请求头）。
 * 发送：拼装 override_* 入参 → POST /apis/{id}/debug；白名单未命中由后端 403。
 */
export function DebugTab({
  api,
  projectId,
}: {
  api: ApiInterfaceDetail;
  projectId: number;
}) {
  const { isPlatformAdmin } = useAuth();
  const { message } = App.useApp();

  const [envName, setEnvName] = useState<string | undefined>();
  const [headers, setHeaders] = useState<KV[]>([]);
  const [pathParams, setPathParams] = useState<KV[]>(() => prefillKv(api, 'PATH'));
  const [query, setQuery] = useState<KV[]>(() => prefillKv(api, 'QUERY'));
  const [bodyText, setBodyText] = useState('');
  const [timeout, setTimeoutSec] = useState(30);
  const [result, setResult] = useState<ApiDebugResult | null>(null);

  const envsQuery = useQuery({
    queryKey: ['project-environments', projectId],
    queryFn: () => projectsApi.listEnvironments(projectId),
  });

  const sendMutation = useMutation({
    mutationFn: (body: ApiDebugRequest) => apiCatalogApi.debug(api.id, body),
    onSuccess: (data) => {
      setResult(data);
      message.success(`请求完成：${data.status_code}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '调试失败')),
  });

  const toRecord = (kvs: KV[]): Record<string, string> => {
    const rec: Record<string, string> = {};
    for (const { key, value } of kvs) {
      if (key.trim()) rec[key.trim()] = value;
    }
    return rec;
  };

  const kvEditor = (
    label: string,
    kvs: KV[],
    setKvs: (v: KV[]) => void,
  ) => (
    <Card className="api-debug-kv-card" size="small" title={label}>
      {kvs.length === 0 ? (
        <Typography.Text type="secondary">（空）</Typography.Text>
      ) : (
        kvs.map((kv, idx) => (
          <div key={idx} className="api-debug-kv-row">
            <Input
              value={kv.key}
              onChange={(e) =>
                setKvs(kvs.map((k, i) => (i === idx ? { ...k, key: e.target.value } : k)))
              }
              placeholder="key"
              aria-label={`${label} key ${idx + 1}`}
            />
            <Input
              value={kv.value}
              onChange={(e) =>
                setKvs(kvs.map((k, i) => (i === idx ? { ...k, value: e.target.value } : k)))
              }
              placeholder="value"
              aria-label={`${label} value ${idx + 1}`}
            />
            <Button
              type="text"
              danger
              icon={<MinusCircleOutlined />}
              aria-label={`删除${label}第 ${idx + 1} 行`}
              onClick={() => setKvs(kvs.filter((_, i) => i !== idx))}
            />
          </div>
        ))
      )}
      <Button
        size="small"
        type="dashed"
        icon={<PlusOutlined />}
        onClick={() => setKvs([...kvs, { key: '', value: '' }])}
      >
        添加
      </Button>
    </Card>
  );

  const handleSend = async () => {
    if (!envName) {
      message.error('请选择环境');
      return;
    }
    let overrideBody: unknown = undefined;
    const trimmed = bodyText.trim();
    if (trimmed) {
      try {
        overrideBody = JSON.parse(trimmed);
      } catch {
        // 非 JSON 时按原始文本发送。
        overrideBody = trimmed;
      }
    }
    const payload: ApiDebugRequest = {
      environment_name: envName,
      override_headers: headers.length ? toRecord(headers) : null,
      override_path_params: pathParams.length ? toRecord(pathParams) : null,
      override_query: query.length ? toRecord(query) : null,
      override_body: overrideBody ?? null,
      timeout,
    };
    await sendMutation.mutateAsync(payload);
  };

  const statusColor = useMemo(() => {
    if (!result) return 'default';
    if (result.status_code < 300) return 'green';
    if (result.status_code < 400) return 'blue';
    if (result.status_code < 500) return 'orange';
    return 'red';
  }, [result]);

  if (!isPlatformAdmin) {
    return (
      <Alert
        type="warning"
        showIcon
        message="需要平台管理员权限"
        description="调试发送真实请求仅对平台管理员开放，请联系管理员或前往个人中心切换身份。"
      />
    );
  }

  if (envsQuery.isPending) return <LoadingState tip="加载环境..." />;

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="调试仅发送一次真实请求，不生成用例、不落库。"
        description="请求目标必须命中项目「出站白名单」（项目管理 → 出站目标），未命中将返回 403。"
      />

      <Card size="small" title="环境与超时">
        <Space wrap align="center">
          <Select
            placeholder="选择环境"
            value={envName}
            onChange={setEnvName}
            showSearch
            optionFilterProp="label"
            style={{ width: 240 }}
            options={(envsQuery.data?.items ?? []).map((e) => ({
              label: `${e.display_name} (${e.name})`,
              value: e.name,
            }))}
            notFoundContent={envsQuery.isPending ? '加载中...' : '暂无可用环境'}
          />
          <Typography.Text>超时（秒）</Typography.Text>
          <InputNumber
            min={1}
            max={120}
            value={timeout}
            onChange={(v) => setTimeoutSec(v ?? 30)}
          />
          <Button
            type="primary"
            loading={sendMutation.isPending}
            onClick={handleSend}
          >
            发送
          </Button>
        </Space>
      </Card>

      {kvEditor('路径参数覆盖', pathParams, setPathParams)}
      {kvEditor('Query 参数覆盖', query, setQuery)}
      {kvEditor('请求头覆盖', headers, setHeaders)}

      <Card size="small" title="请求体覆盖">
        <Input.TextArea
          rows={5}
          value={bodyText}
          onChange={(e) => setBodyText(e.target.value)}
          placeholder='{"key":"value"}  （留空则不覆盖 body）'
          style={{ fontFamily: 'monospace' }}
        />
      </Card>

      {result && (
        <Card
          size="small"
          title={
            <Space>
              <Tag color={statusColor}>{result.status_code}</Tag>
              <Typography.Text type="secondary">
                {result.response_time_ms}ms
              </Typography.Text>
            </Space>
          }
        >
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <div>
              <Typography.Text type="secondary">请求 URL</Typography.Text>
              <div>
                <Typography.Text code copyable>
                  {result.request_url}
                </Typography.Text>
              </div>
              {result.outbound_target_id != null && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  命中出站白名单 #{result.outbound_target_id}
                </Typography.Text>
              )}
            </div>
            <div>
              <Typography.Text type="secondary">响应头</Typography.Text>
              <JsonView data={result.response_headers} height={180} />
            </div>
            <div>
              <Typography.Text type="secondary">响应体</Typography.Text>
              {(() => {
                const trimmed = result.response_body.trim();
                if (!trimmed) {
                  return <Typography.Text type="secondary">（空）</Typography.Text>;
                }
                try {
                  return <JsonView data={JSON.parse(trimmed)} raw={trimmed} height={280} />;
                } catch {
                  return (
                    <Input.TextArea
                      value={result.response_body}
                      readOnly
                      rows={8}
                      style={{ fontFamily: 'monospace' }}
                    />
                  );
                }
              })()}
            </div>
          </Space>
        </Card>
      )}
    </Space>
  );
}
