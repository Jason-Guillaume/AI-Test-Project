import { useEffect, useState } from 'react';
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Typography } from 'antd';
import type { AgentDefinition } from '@/features/agent-governance/contracts';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import { getErrorMessage } from '@/shared/api/client';

const EXAMPLES: Record<string, { label: string; arguments: object }> = {
  'asr.score_transcript': { label: '标准答案 CER/WER', arguments: { reference: '今天北京天气很好', hypothesis: '今天北京天气好', unit: 'character', ignore_case: false, ignore_punctuation: false } },
  'asr.get_job_summary': { label: 'ASR 批次状态', arguments: { job_id: 1 } },
  'asr.get_comparison_summary': { label: 'ASR 对比摘要', arguments: { comparison_id: 1 } },
  'ai.check_output': { label: 'AI 输出规则', arguments: { output: '{"answer":"北京"}', required_phrases: ['北京'], forbidden_phrases: [], require_json_object: true } },
};

export function EvaluationToolModal({ agent, onClose }: { agent: AgentDefinition | null; onClose: () => void }) {
  const [form] = Form.useForm();
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const toolKey = Form.useWatch('tool_key', form) as string | undefined;
  useEffect(() => {
    if (agent) form.setFieldsValue({ tool_key: agent.tool_keys.find((key) => key in EXAMPLES) });
    setResult(undefined); setError('');
  }, [agent, form]);
  useEffect(() => {
    if (toolKey && EXAMPLES[toolKey]) form.setFieldsValue({ arguments: JSON.stringify(EXAMPLES[toolKey].arguments, null, 2) });
    setResult(undefined); setError('');
  }, [toolKey, form]);
  const invoke = async () => {
    if (!agent) return;
    try {
      const values = await form.validateFields();
      const args = JSON.parse(values.arguments);
      if (!args || Array.isArray(args) || typeof args !== 'object') throw new Error('参数必须为 JSON 对象');
      setBusy(true); setError(''); setResult(undefined);
      setResult(await agentGovernanceApi.invokeEvaluation(agent.id, values.tool_key, values.project_id, args));
    } catch (err) { setError(getErrorMessage(err)); }
    finally { setBusy(false); }
  };
  return <Modal title={`${agent?.name ?? ''} · 评测工具`} open={Boolean(agent)} onCancel={onClose} width={760} footer={<Button type="primary" loading={busy} disabled={!agent?.is_enabled} onClick={invoke}>运行评测</Button>} destroyOnClose>
    <Alert type="info" showIcon message="只读评测，不启动外部推理。项目与资产 ID 请替换为实际值；参数样例仅用于说明输入格式。" style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical">
      <Form.Item name="project_id" label="项目 ID" rules={[{ required: true }]}><InputNumber min={1} precision={0} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="tool_key" label="已授权工具" rules={[{ required: true }]}><Select options={(agent?.tool_keys ?? []).filter((key) => key in EXAMPLES).map((key) => ({ value: key, label: EXAMPLES[key].label }))} /></Form.Item>
      <Form.Item name="arguments" label="工具参数（JSON）" rules={[{ required: true }]}><Input.TextArea rows={10} spellCheck={false} /></Form.Item>
    </Form>
    {error && <Alert type="error" showIcon message={error} />}
    {result !== undefined && <Typography.Paragraph><pre style={{ maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{JSON.stringify(result, null, 2)}</pre></Typography.Paragraph>}
  </Modal>;
}
