// EXISTING_POOL Provider 配置：选择 pool_key。
//
// §9.7 EXISTING_POOL：从既有数据池取一个可用项。
import { Form, Input } from 'antd';

interface ConfigProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: number;
}

/**
 * EXISTING_POOL 配置：pool_key。
 */
export function ProviderConfigPool({ value, onChange }: ConfigProps) {
  return (
    <Form.Item
      label="pool_key"
      required
      tooltip="目标数据池的 pool_key（在数据池 Tab 创建）"
    >
      <Input
        value={(value.pool_key as string) ?? ''}
        onChange={(e) => onChange({ ...value, pool_key: e.target.value })}
        placeholder="如 USERS_POOL"
      />
    </Form.Item>
  );
}
