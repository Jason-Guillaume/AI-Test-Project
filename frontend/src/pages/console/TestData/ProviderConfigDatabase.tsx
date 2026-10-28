import { collectPages } from '@/api/pagination';
// DATABASE_INSERT / DATABASE_PATCH Provider 配置：connection + table + operation + where + values。
//
// §9.6 / §10：被测库直写。connection 从本项目已建连接里选（本模块内）；
// operation 下拉无 DELETE（除非策略允许且单独开关，Phase A 不放开 DELETE 选项，服务端兜底）；
// where / values 为键值 JSON 文本。
import { useState } from 'react';
import { Form, Input, Select } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';

interface ConfigProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: number;
}

const DB_OPERATIONS = [
  { label: '查询 SELECT', value: 'SELECT' },
  { label: '插入 INSERT', value: 'INSERT' },
  { label: '更新 UPDATE', value: 'UPDATE' },
];

function useJsonField(
  value: Record<string, unknown>,
  onChange: (v: Record<string, unknown>) => void,
  key: string,
  initial: unknown,
) {
  const [text, setText] = useState(() => {
    const v = value[key];
    return v == null ? JSON.stringify(initial, null, 2) : JSON.stringify(v, null, 2);
  });
  const handle = (t: string) => {
    setText(t);
    try {
      onChange({ ...value, [key]: JSON.parse(t) });
    } catch {
      /* 非法 JSON 不回传 */
    }
  };
  return { text, handle };
}

/**
 * 被测库 Provider 配置。connection 列表来自本项目（viewer+ 可读）。
 */
export function ProviderConfigDatabase({ value, onChange, projectId }: ConfigProps) {
  const connectionsQuery = useQuery({
    queryKey: ['test-data', 'connections', projectId, { page_size: 200 }],
    queryFn: () => collectPages((page) => testDataApi.listConnections(projectId, { page, page_size: 200 })),
    enabled: projectId != null,
  });
  const where = useJsonField(value, onChange, 'where', {});
  const values = useJsonField(value, onChange, 'values', {});

  const connOptions = (connectionsQuery.data?.items ?? []).map((c) => ({
    label: `${c.name}${c.environment_name ? `（${c.environment_name}）` : ''}`,
    value: c.id,
  }));

  return (
    <>
      <Form.Item
        label="目标库连接"
        required
        tooltip="本项目已建的被测库连接；DATABASE 类 Provider 仅平台管理员可创建"
      >
        <Select
          showSearch
          optionFilterProp="label"
          loading={connectionsQuery.isFetching}
          value={value.connection_id as number | undefined}
          onChange={(v) => onChange({ ...value, connection_id: v })}
          options={connOptions}
          placeholder="选择连接"
        />
      </Form.Item>
      <Form.Item label="表名" required tooltip="提交前由后端表白名单判定">
        <Input
          value={(value.table as string) ?? ''}
          onChange={(e) => onChange({ ...value, table: e.target.value })}
          placeholder="如 users"
        />
      </Form.Item>
      <Form.Item label="操作" required>
        <Select
          value={(value.operation as string) ?? undefined}
          onChange={(v) => onChange({ ...value, operation: v })}
          options={DB_OPERATIONS}
          placeholder="选择操作（DELETE 需策略单独放开）"
        />
      </Form.Item>
      <Form.Item label="where（JSON 键值，可选）" tooltip='如 {"id":1}'>
        <Input.TextArea
          rows={3}
          style={{ fontFamily: 'monospace' }}
          value={where.text}
          onChange={(e) => where.handle(e.target.value)}
          placeholder='{"id":1}'
        />
      </Form.Item>
      <Form.Item label="values（JSON 键值）" tooltip='如 {"name":"alice","age":18}'>
        <Input.TextArea
          rows={3}
          style={{ fontFamily: 'monospace' }}
          value={values.text}
          onChange={(e) => values.handle(e.target.value)}
          placeholder='{"name":"alice"}'
        />
      </Form.Item>
    </>
  );
}
