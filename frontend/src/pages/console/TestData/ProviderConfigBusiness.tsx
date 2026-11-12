// BUSINESS_ACTION / BUSINESS_FLOW Provider 配置：复用同一组件，按 mode 区分。
//
// §9.2 BUSINESS_ACTION：选流程 + action_key；§9.3 BUSINESS_FLOW：选流程。
// Phase A：流程选择暂用数字 ID 输入（跨模块下拉为后续优化）。
import { Form, Input } from 'antd';

interface ConfigProps {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: number;
}

/**
 * 业务配置。mode='action' 渲染 action_key；mode='flow' 只需流程。
 */
export function ProviderConfigBusiness({
  value,
  onChange,
  mode,
}: ConfigProps & { mode: 'action' | 'flow' }) {
  return (
    <>
      <Form.Item
        label="流程 ID"
        required
        tooltip="本项目业务流程的 id（业务管理页可查）"
      >
        <Input
          value={value.flow_id == null ? '' : String(value.flow_id)}
          onChange={(e) => {
            const n = e.target.value.trim();
            onChange({ ...value, flow_id: n ? Number(n) : null });
          }}
          placeholder="如 8"
        />
      </Form.Item>
      {mode === 'action' && (
        <Form.Item label="action_key" required tooltip="流程内的 action_key">
          <Input
            value={(value.action_key as string) ?? ''}
            onChange={(e) => onChange({ ...value, action_key: e.target.value })}
            placeholder="如 createOrder"
          />
        </Form.Item>
      )}
      <Form.Item label="输出映射（JSON，可选）" tooltip='变量 ← JSONPath，如 {"order_id":"$.data.id"}'>
        <Input.TextArea
          rows={3}
          style={{ fontFamily: 'monospace' }}
          value={value.output_mappings == null ? '' : JSON.stringify(value.output_mappings)}
          onChange={(e) => {
            const t = e.target.value;
            try {
              onChange({ ...value, output_mappings: t ? JSON.parse(t) : {} });
            } catch {
              /* 非法 JSON 不回传 */
            }
          }}
          placeholder='{"order_id":"$.data.id"}'
        />
      </Form.Item>
    </>
  );
}
