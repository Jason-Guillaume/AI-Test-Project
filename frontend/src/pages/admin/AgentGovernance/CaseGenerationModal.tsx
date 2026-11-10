import { useState } from 'react';
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Typography } from 'antd';
import type { AgentDefinition } from '@/features/agent-governance/contracts';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import { getErrorMessage } from '@/shared/api/client';

const MODULES = { api: '接口', web: 'Web UI', security: '安全', asr: 'ASR', ai: 'AI 质量' };
export function CaseGenerationModal({ agent, agents, models, onClose }: {
  agent: AgentDefinition | null; agents: AgentDefinition[];
  models: { label: string; value: number }[]; onClose: () => void;
}) {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState('');
  const availableModules = Object.entries(MODULES).filter(([key]) => agents.some((child) => agent?.child_agent_ids.includes(child.id) && child.tool_keys.includes(`case_generation.generate_${key}`)));
  const fixed = agent?.settings_json.model_binding === 'agent';
  const run = async () => {
    if (!agent) return;
    try {
      const values = await form.validateFields();
      setBusy(true); setResult(undefined); setError('');
      setResult(await agentGovernanceApi.generateCases(agent.id, { ...values, model_config_id: fixed ? agent.model_config_id : values.model_config_id }));
    } catch (err) { setError(getErrorMessage(err)); }
    finally { setBusy(false); }
  };
  return <Modal title={`${agent?.name ?? ''} · 分模块生成用例`} open={Boolean(agent)} width={900} onCancel={busy ? undefined : onClose} closable={!busy} maskClosable={!busy}
    footer={<Button type="primary" loading={busy} onClick={run} disabled={!agent?.is_enabled}>生成用例草稿</Button>}>
    <Alert type="info" showIcon message="主 Agent 调度所选模块子 Agent，再汇总审阅。将调用授权模型并消耗额度；结果需人工审核，不自动保存或执行。" style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical" initialValues={{ cases_per_module: 5, modules: availableModules.map(([key]) => key) }}>
      <Form.Item name="project_id" label="项目 ID" rules={[{ required: true }]}><InputNumber min={1} precision={0} /></Form.Item>
      <Form.Item name="modules" label="生成模块" rules={[{ required: true, type: 'array', min: 1 }]}><Select mode="multiple" options={availableModules.map(([value, label]) => ({ value, label }))} /></Form.Item>
      <Form.Item name="model_config_id" label={fixed ? '主 Agent 已固定模型' : '本次主模型（子 Agent 未固定模型时继承）'}><Select allowClear disabled={fixed} placeholder={fixed ? models.find((m) => m.value === agent?.model_config_id)?.label ?? `模型 #${agent?.model_config_id}` : '使用全局授权默认模型'} options={models} /></Form.Item>
      <Form.Item name="cases_per_module" label="每模块最多生成条数" rules={[{ required: true }]}><InputNumber min={1} max={20} precision={0} /></Form.Item>
      <Form.Item name="requirements" label="需求与已确认上下文" rules={[{ required: true, whitespace: true, max: 20000 }]}><Input.TextArea rows={8} maxLength={20000} showCount placeholder="填写业务需求、接口契约、页面流程、模型评测目标及验收条件；不要包含真实密钥或个人信息。" /></Form.Item>
    </Form>
    {error && <Alert type="error" message={error} />}
    {result !== undefined && <Typography.Paragraph><pre style={{ maxHeight: 500, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(result, null, 2)}</pre></Typography.Paragraph>}
  </Modal>;
}
