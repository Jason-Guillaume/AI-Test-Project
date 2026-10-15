// API_CREATE Provider 配置：选本项目接口 + 输入映射 + 输出映射 + Cleanup 绑定。
//
// §9.1 API_CREATE：调本项目接口造数。输入映射（目标字段 ← 来源表达式）、
// 输出映射（变量 ← JSONPath）、Cleanup 绑定（方法 + 路径模板，路径里只允许已声明输出）。
//
// Phase A：接口选择暂用数字 ID 输入（跨模块下拉为后续优化），映射表用 JSON 文本编辑，
// 解析成功才回传，避免半成品写回配置。
import { useState } from 'react';
import { Form, Input, Select } from 'antd';

interface ConfigProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: number;
}

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

/** JSON 文本字段：本地维护字符串，解析成功才回传对象。 */
function useJsonField(value: Record<string, unknown>, onChange: (v: Record<string, unknown>) => void, key: string, initial: unknown) {
  const [text, setText] = useState(() => {
    const v = value[key];
    return v == null ? JSON.stringify(initial, null, 2) : JSON.stringify(v, null, 2);
  });
  const handle = (t: string) => {
    setText(t);
    try {
      onChange({ ...value, [key]: JSON.parse(t) });
    } catch {
      // 非法 JSON：保留文本，不回传。
    }
  };
  return { text, handle };
}

/**
 * API_CREATE 配置。
 */
export function ProviderConfigApi({ value, onChange }: ConfigProps) {
  const inputMappings = useJsonField(value, onChange, 'input_mappings', {});
  const outputMappings = useJsonField(value, onChange, 'output_mappings', {});
  return (
    <>
      <Form.Item
        label="接口 ID"
        required
        tooltip="本项目接口的 id（接口管理页可查）；后续可改为下拉选择"
      >
        <Input
          value={value.api_id == null ? '' : String(value.api_id)}
          onChange={(e) => {
            const n = e.target.value.trim();
            onChange({ ...value, api_id: n ? Number(n) : null });
          }}
          placeholder="如 12"
        />
      </Form.Item>
      <Form.Item
        label="输入映射（JSON）"
        tooltip='目标字段 ← 来源表达式，如 {"username":"${USER.username}","age":18}'
      >
        <Input.TextArea
          rows={4}
          value={inputMappings.text}
          onChange={(e) => inputMappings.handle(e.target.value)}
          style={{ fontFamily: 'monospace' }}
          placeholder='{"username":"${USER.username}"}'
        />
      </Form.Item>
      <Form.Item
        label="输出映射（JSON）"
        tooltip='变量 ← JSONPath，如 {"id":"$.data.id"}'
      >
        <Input.TextArea
          rows={4}
          value={outputMappings.text}
          onChange={(e) => outputMappings.handle(e.target.value)}
          style={{ fontFamily: 'monospace' }}
          placeholder='{"id":"$.data.id"}'
        />
      </Form.Item>
      <Form.Item label="Cleanup 方法" tooltip="清理时调用的 HTTP 方法">
        <Select
          allowClear
          value={(value.cleanup_method as string) ?? undefined}
          onChange={(v) => onChange({ ...value, cleanup_method: v ?? '' })}
          options={HTTP_METHODS.map((m) => ({ label: m, value: m }))}
        />
      </Form.Item>
      <Form.Item
        label="Cleanup 路径模板"
        tooltip="路径里只允许引用已声明输出，如 /users/${id}"
      >
        <Input
          value={(value.cleanup_path as string) ?? ''}
          onChange={(e) => onChange({ ...value, cleanup_path: e.target.value })}
          placeholder="/users/${id}"
        />
      </Form.Item>
    </>
  );
}
