// STATIC Provider 配置：单个 JSON 对象作为静态值。
//
// §9.5 STATIC：config.values 即产出值。整表作为一个 JSON 文本编辑，
// 提交时由本组件保证解析为对象后再回传。
import { useState } from 'react';
import { Form, Input } from 'antd';

interface ConfigProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: number;
}

/**
 * STATIC 配置：values（JSON 对象）。
 */
export function ProviderConfigStatic({ value, onChange }: ConfigProps) {
  const [text, setText] = useState(() =>
    JSON.stringify(value.values ?? {}, null, 2),
  );
  const handle = (t: string) => {
    setText(t);
    try {
      const parsed = JSON.parse(t);
      onChange({ ...value, values: parsed });
    } catch {
      // 非法 JSON：保留文本，不回传，避免把半成品写回配置。
    }
  };
  return (
    <Form.Item
      label="values（JSON 对象）"
      tooltip='如 {"username":"alice","age":18}'
    >
      <Input.TextArea
        rows={6}
        value={text}
        onChange={(e) => handle(e.target.value)}
        style={{ fontFamily: 'monospace' }}
        placeholder='{"username":"alice"}'
      />
    </Form.Item>
  );
}
