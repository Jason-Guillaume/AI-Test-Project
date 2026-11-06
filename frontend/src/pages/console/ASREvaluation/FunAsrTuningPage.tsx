import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, App, Button, Card, Checkbox, Collapse, Descriptions, Divider, Flex, Input,
  InputNumber, Select, Space, Table, Tag, Typography, Upload,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import { AsrFrame } from './AsrFrame';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { funasrTuningApi } from '@/features/asr-evaluation/api/funasrTuning';
import type {
  FunAsrBinding, FunAsrEnvironment, FunAsrGroundTruth, FunAsrInterface,
  FunAsrParameterDefinition, FunAsrTuningSession,
} from '@/features/asr-evaluation/api/funasrTuning';
import type { AsrAudio, JsonValue } from '@/features/asr-evaluation/contracts';

const { Text, Paragraph, Title } = Typography;
const EMPTY_MAPPING = JSON.stringify({ text_source: 'full', text_pointer: '' }, null, 2);
const ERROR_MESSAGES: Record<string, string> = {
  QUEUED: '排队中', RUNNING: '运行中', PAUSE_REQUESTED: '等待暂停', PAUSED: '已暂停',
  WAITING_WINDOW: '等待夜间窗口', STOP_REQUESTED: '等待停止', STOPPED: '已停止',
  COMPLETED: '已完成', FAILED: '失败', RECONCILIATION_REQUIRED: '待核实',
  PENDING: '待运行', SUBMITTING: '提交中', SUCCEEDED: '成功', PARTIAL: '部分完成',
  ANALYZING: '分析中',
};

function parseObject(text: string, label: string): Record<string, JsonValue> {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error(`${label}不是有效 JSON`); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}必须是 JSON 对象`);
  return value as Record<string, JsonValue>;
}

function makeKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `funasr-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function statusTag(status: string) {
  const color = status === 'COMPLETED' || status === 'SUCCEEDED' ? 'green'
    : status === 'FAILED' || status === 'RECONCILIATION_REQUIRED' ? 'red'
      : status === 'RUNNING' || status === 'ANALYZING' || status === 'SUBMITTING' ? 'blue' : 'default';
  return <Tag color={color}>{ERROR_MESSAGES[status] ?? status}</Tag>;
}

export function FunAsrTuningPage() {
  const { message } = App.useApp();
  const { currentProjectId } = useConsoleScope();
  const projectId = currentProjectId;
  const [audios, setAudios] = useState<AsrAudio[]>([]);
  const [answers, setAnswers] = useState<FunAsrGroundTruth[]>([]);
  const [interfaces, setInterfaces] = useState<FunAsrInterface[]>([]);
  const [environments, setEnvironments] = useState<FunAsrEnvironment[]>([]);
  const [bindings, setBindings] = useState<FunAsrBinding[]>([]);
  const [definitions, setDefinitions] = useState<FunAsrParameterDefinition[]>([]);
  const [models, setModels] = useState<Array<{ id: number; label: string; model_name: string }>>([]);
  const [sessions, setSessions] = useState<FunAsrTuningSession[]>([]);
  const [selectedSession, setSelectedSession] = useState<FunAsrTuningSession | null>(null);
  const [selectedAudioIds, setSelectedAudioIds] = useState<number[]>([]);
  const [interfaceId, setInterfaceId] = useState<number>();
  const [environmentName, setEnvironmentName] = useState<string>();
  const [bindingId, setBindingId] = useState<number>();
  const [credential, setCredential] = useState('');
  const [credentialHeader, setCredentialHeader] = useState('Authorization');
  const [responseMappingText, setResponseMappingText] = useState(EMPTY_MAPPING);
  const [groundTruthMappingText, setGroundTruthMappingText] = useState(EMPTY_MAPPING);
  const [answerFixture, setAnswerFixture] = useState('');
  const [responseFixture, setResponseFixture] = useState('');
  const [parameterText, setParameterText] = useState('{}');
  const [allowedText, setAllowedText] = useState('{}');
  const [modelConfigId, setModelConfigId] = useState<number>();
  const [mode, setMode] = useState<'ANALYZE' | 'AUTO_TUNE'>('AUTO_TUNE');
  const [maxRounds, setMaxRounds] = useState(8);
  const [maxAsrRequests, setMaxAsrRequests] = useState(24);
  const [maxAiCalls, setMaxAiCalls] = useState(64);
  const [noImprovementLimit, setNoImprovementLimit] = useState(3);
  const [failedItemsLimit, setFailedItemsLimit] = useState(1);
  const [targetCer, setTargetCer] = useState<number | null>(null);
  const [nightWindow, setNightWindow] = useState(false);
  const [nightStart, setNightStart] = useState('22:00');
  const [nightEnd, setNightEnd] = useState('07:00');
  const [busy, setBusy] = useState(false);
  const [previewMarkdown, setPreviewMarkdown] = useState<string>();

  const loadSetup = useCallback(async () => {
    if (!projectId) return;
    try {
      const [audioResult, answerResult, interfaceResult, environmentResult, bindingResult, definitionResult, modelResult] = await Promise.all([
        funasrTuningApi.audioList(projectId), funasrTuningApi.groundTruth(projectId),
        funasrTuningApi.interfaces(projectId), funasrTuningApi.environments(projectId),
        funasrTuningApi.bindings(projectId), funasrTuningApi.definitions(), funasrTuningApi.models(projectId),
      ]);
      setAudios(audioResult.items); setAnswers(answerResult.items); setInterfaces(interfaceResult.items);
      setEnvironments(environmentResult.items); setBindings(bindingResult.items); setDefinitions(definitionResult.items);
      setModels(modelResult.items);
      setEnvironmentName((previous) => previous ?? environmentResult.items.find((item) => item.is_default)?.name ?? environmentResult.items[0]?.name);
      setModelConfigId((previous) => previous ?? modelResult.items[0]?.id);
      setSelectedAudioIds((previous) => previous.filter((id) => audioResult.items.some((item) => item.id === id)));
    } catch (error) {
      message.error(error instanceof Error ? error.message : '读取 FunASR 配置失败');
    }
  }, [message, projectId]);

  const loadSessions = useCallback(async () => {
    if (!projectId) return;
    try {
      const result = await funasrTuningApi.sessions(projectId);
      setSessions(result.items);
      if (selectedSession) {
        const current = result.items.find((item) => item.id === selectedSession.id);
        if (current) {
          const detail = await funasrTuningApi.session(current.id);
          setSelectedSession(detail);
        }
      }
    } catch { /* retain the latest readable state while polling */ }
  }, [projectId, selectedSession]);

  useEffect(() => {
    setAudios([]); setAnswers([]); setInterfaces([]); setEnvironments([]); setBindings([]); setModels([]); setSessions([]);
    setSelectedSession(null); setSelectedAudioIds([]); setInterfaceId(undefined); setEnvironmentName(undefined);
    setBindingId(undefined); setModelConfigId(undefined); setCredential(''); setResponseMappingText(EMPTY_MAPPING);
    setGroundTruthMappingText(EMPTY_MAPPING); setAnswerFixture(''); setResponseFixture('');
  }, [projectId]);
  useEffect(() => { void loadSetup(); }, [loadSetup]);
  useEffect(() => {
    if (!projectId) return;
    void loadSessions();
    const timer = window.setInterval(() => { void loadSessions(); }, 4000);
    return () => window.clearInterval(timer);
  }, [loadSessions, projectId]);

  const audioById = useMemo(() => new Map(audios.map((audio) => [audio.id, audio])), [audios]);
  const answerByAudioId = useMemo(() => new Map(answers.map((answer) => [answer.audio_id, answer])), [answers]);
  const selectedBinding = bindings.find((item) => item.id === bindingId);
  const selectedInterface = interfaces.find((item) => item.id === interfaceId);
  const currentParameters = useMemo(() => {
    try { return parseObject(parameterText, '基线参数'); } catch { return {}; }
  }, [parameterText]);
  const funasrInterfaces = interfaces.filter((item) => item.method.toUpperCase() === 'POST'
    && item.path.replace(/\/$/, '').endsWith('/api/v1/transcribe/paraformer/v2'));

  const createBinding = async () => {
    if (!projectId || !interfaceId || !environmentName) return;
    setBusy(true);
    try {
      const mapping = parseObject(responseMappingText, '响应映射');
      const row = await funasrTuningApi.createBinding({ project_id: projectId, api_interface_id: interfaceId,
        environment_name: environmentName, response_mapping: mapping, credential: credential || null,
        credential_header: credential ? credentialHeader : null });
      setBindings((current) => [row, ...current]); setBindingId(row.id); setCredential('');
      setParameterText(JSON.stringify(row.parameter_seed ?? {}, null, 2));
      message.success('接口绑定已保存；原接口参数示例仍按原值保留');
    } catch (error) { message.error(error instanceof Error ? error.message : '保存接口绑定失败'); }
    finally { setBusy(false); }
  };

  const saveResponseMapping = async () => {
    if (!bindingId) return;
    setBusy(true);
    try {
      const mapping = parseObject(responseMappingText, '响应映射');
      if (!responseFixture.trim()) throw new Error('请提供实际响应 JSON 样本并预览映射');
      const sample = JSON.parse(responseFixture) as JsonValue;
      const preview = await funasrTuningApi.previewMapping(sample, mapping, 'recognition');
      setPreviewMarkdown(preview.markdown);
      const row = await funasrTuningApi.updateBinding(bindingId, mapping, sample);
      setBindings((current) => current.map((item) => item.id === row.id ? row : item));
      message.success('响应映射已保存。请用真实响应样本预览后再创建任务。');
    } catch (error) { message.error(error instanceof Error ? error.message : '保存映射失败'); }
    finally { setBusy(false); }
  };

  const previewJson = async (source: 'ground_truth' | 'recognition') => {
    const text = source === 'ground_truth' ? answerFixture : responseFixture;
    if (!text.trim()) { message.info('请先选择或粘贴一份 JSON 样本用于预览'); return; }
    try {
      const document = JSON.parse(text) as JsonValue;
      const mapping = parseObject(source === 'ground_truth' ? groundTruthMappingText : responseMappingText,
        source === 'ground_truth' ? '标准答案映射' : '响应映射');
      const result = await funasrTuningApi.previewMapping(document, mapping, source);
      setPreviewMarkdown(result.markdown);
      message.success(`映射预览完成${result.warnings.length ? `，${result.warnings.length} 条提示` : ''}`);
    } catch (error) { message.error(error instanceof Error ? error.message : '映射预览失败'); }
  };

  const uploadAnswer = async (audioId: number, file: File) => {
    setBusy(true);
    try {
      const document = JSON.parse(await file.text()) as JsonValue;
      const mapping = parseObject(groundTruthMappingText, '标准答案映射');
      await funasrTuningApi.createGroundTruth(audioId, document, mapping);
      const refreshed = await funasrTuningApi.groundTruth(projectId!);
      setAnswers(refreshed.items);
      setAnswerFixture(JSON.stringify(document, null, 2));
      message.success('标准答案已保存为新版本');
    } catch (error) { message.error(error instanceof Error ? error.message : '标准答案 JSON 上传失败'); }
    finally { setBusy(false); }
  };

  const createSession = async () => {
    if (!projectId || !bindingId || !modelConfigId || !selectedAudioIds.length) return;
    setBusy(true);
    try {
      const parameters = parseObject(parameterText, '基线参数');
      const allowed = parseObject(allowedText, '搜索范围');
      const result = await funasrTuningApi.createSession({ project_id: projectId, binding_id: bindingId,
        model_config_id: modelConfigId, audio_ids: selectedAudioIds, parameters, allowed_parameters: allowed,
        mode, max_rounds: maxRounds, max_asr_requests: maxAsrRequests, max_ai_calls: maxAiCalls,
        no_improvement_limit: noImprovementLimit, failed_items_limit: failedItemsLimit,
        target_micro_cer: targetCer, min_improvement: 0.001, max_sample_degradation: 0.05,
        window_enabled: nightWindow, night_start: nightStart, night_end: nightEnd, idempotency_key: makeKey() });
      setSelectedSession(result);
      await loadSessions();
      message.success('后台调优任务已创建；关闭页面不会停止任务');
    } catch (error) { message.error(error instanceof Error ? error.message : '创建调优任务失败'); }
    finally { setBusy(false); }
  };

  const actOnSession = async (action: 'pause' | 'resume' | 'stop' | 'retryFailed' | 'retryAnalysis') => {
    if (!selectedSession) return;
    setBusy(true);
    try {
      const next = await funasrTuningApi[action](selectedSession.id);
      setSelectedSession(next); await loadSessions();
      message.success('任务操作已提交');
    } catch (error) { message.error(error instanceof Error ? error.message : '任务操作失败'); }
    finally { setBusy(false); }
  };

  const audioColumns: TableColumnsType<AsrAudio> = [
    { title: '录音', dataIndex: 'name', key: 'name', render: (_value, row) => <Space direction="vertical" size={0}><Text strong>{row.name}</Text><Text type="secondary">音频版本 {row.content_version}</Text></Space> },
    { title: '标准答案 JSON', key: 'answer', width: 220, render: (_value, row) => {
      const answer = answerByAudioId.get(row.id);
      return <Space direction="vertical" size="small">{answer ? <Tag color="green">答案 v{answer.version} 已冻结</Tag> : <Tag color="orange">待上传</Tag>}
        <Upload accept=".json,application/json" showUploadList={false} disabled={busy}
          beforeUpload={(file) => { void uploadAnswer(row.id, file); return false; }}>
          <Button size="small" icon={<UploadOutlined />} disabled={busy}>
            {answer ? '更换答案 JSON' : '绑定样例 JSON'}
          </Button>
        </Upload>
      </Space>;
    } },
    { title: '时长', dataIndex: 'duration_seconds', key: 'duration', width: 90, render: (value) => value == null ? '—' : `${value} 秒` },
  ];

  const sessionColumns: TableColumnsType<FunAsrTuningSession> = [
    { title: '任务', dataIndex: 'id', key: 'id', width: 80, render: (value) => `#${value}` },
    { title: '状态', dataIndex: 'status', key: 'status', render: statusTag },
    { title: '轮次', dataIndex: 'current_round', key: 'round', width: 90, render: (value, row) => `${value} / ${row.total_rounds || '—'}` },
    { title: '进度', key: 'progress', render: (_value, row) => `${row.completed_items}/${row.total_items} 项` },
    { title: '最佳微平均 CER', dataIndex: 'best_micro_cer', key: 'cer', render: (value) => value == null ? '—' : Number(value).toFixed(4) },
    { title: 'ASR / AI 用量', key: 'usage', render: (_value, row) => `${row.asr_requests_used}/${row.max_asr_requests} · ${row.ai_calls_used}/${row.max_ai_calls}` },
  ];

  const detail = selectedSession;
  const currentStatus = detail?.status ?? '';
  const canPause = ['QUEUED', 'RUNNING', 'WAITING_WINDOW'].includes(currentStatus);
  const canResume = ['PAUSED', 'WAITING_WINDOW'].includes(currentStatus);
  const canStop = !['COMPLETED', 'STOPPED', 'FAILED'].includes(currentStatus);
  const canRetryAsr = currentStatus === 'FAILED' && detail?.rounds?.some((round) => round.items?.some((item) => item.status === 'FAILED'));
  const canRetryAi = currentStatus === 'FAILED' && detail?.rounds?.some((round) => round.items?.some((item) => item.review_status === 'FAILED') || round.status === 'FAILED');

  return <AsrFrame title="AI 分析与调优" projectId={projectId ?? undefined}>
    {!projectId ? <Alert type="info" showIcon message="请先在顶部选择项目" description="接口、录音、答案和任务均按项目隔离。" /> : <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Alert type="info" showIcon message="独立 FunASR 评测流程" description="从接口管理绑定 POST /api/v1/transcribe/paraformer/v2，逐条串行识别并计算 CER。后台按预算、窗口和停止条件自动运行；页面关闭不会停止任务。真实响应与答案路径必须由你配置并预览。" />

      <Card title="1. 绑定接口与项目环境" extra={selectedBinding && (selectedBinding.interface_updated || selectedBinding.interface_removed) ? <Tag color="orange">来源接口已更新</Tag> : null}>
        <Flex gap="middle" wrap="wrap" align="end">
          <div style={{ minWidth: 280, flex: 1 }}><Text>接口管理中的 FunASR 接口</Text><Select style={{ width: '100%' }} value={interfaceId}
            placeholder="选择 POST Paraformer V2 接口" options={funasrInterfaces.map((item) => ({ value: item.id, label: `${item.name} · ${item.method} ${item.path}` }))}
            onChange={(value) => setInterfaceId(value)} /></div>
          <div style={{ minWidth: 180 }}><Text>项目环境</Text><Select style={{ width: '100%' }} value={environmentName}
            placeholder="选择环境" options={environments.map((item) => ({ value: item.name, label: `${item.display_name}${item.is_default ? '（默认）' : ''}` }))}
            onChange={setEnvironmentName} /></div>
          <Button type="primary" loading={busy} disabled={!interfaceId || !environmentName} onClick={() => void createBinding()}>
            创建接口绑定
          </Button>
        </Flex>
        {selectedInterface && <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          已选接口 v{selectedInterface.version}，source hash {selectedInterface.source_hash ?? '未提供'}。任务会冻结此版本和环境地址。
        </Paragraph>}
        <Divider />
        <Flex gap="middle" wrap="wrap" align="end">
          <div style={{ minWidth: 280, flex: 1 }}><Text>已保存绑定</Text><Select style={{ width: '100%' }} value={bindingId}
            placeholder="选择已有绑定" options={bindings.map((item) => ({ value: item.id,
              label: `#${item.id} ${item.interface_name} · ${item.environment_name}${item.interface_updated ? ' · 接口有更新' : ''}` }))}
            onChange={(value) => { setBindingId(value); const row = bindings.find((item) => item.id === value); if (row) {
              setResponseMappingText(JSON.stringify(row.response_mapping ?? {}, null, 2));
              setParameterText(JSON.stringify(row.parameter_seed ?? {}, null, 2));
            } }} /></div>
          <div style={{ minWidth: 210 }}><Text>鉴权请求头（仅创建绑定时）</Text><Input value={credentialHeader} onChange={(event) => setCredentialHeader(event.target.value)} /></div>
          <div style={{ minWidth: 250, flex: 1 }}><Text>鉴权凭据（加密保存，不回显）</Text><Input.Password value={credential} onChange={(event) => setCredential(event.target.value)} autoComplete="new-password" /></div>
        </Flex>
        {selectedBinding?.parameter_seed_warnings?.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} style={{ marginTop: 12 }} />)}
        {selectedBinding && !selectedBinding.response_mapping_verified && <Alert type="warning" showIcon
          message="响应映射尚未通过样本验证；请粘贴真实响应 JSON、预览并验证保存后再运行。" style={{ marginTop: 12 }} />}
        <Divider />
        <Text strong>真实响应映射 JSON</Text>
        <Paragraph type="secondary">没有可用响应样本时不能启动任务。填写实际 JSON 响应并预览、验证后保存，系统会在发出 ASR 请求前拒绝未验证映射。</Paragraph>
        <Input.TextArea rows={5} value={responseMappingText} onChange={(event) => setResponseMappingText(event.target.value)} spellCheck={false} />
        <Flex gap="small" wrap="wrap" style={{ marginTop: 8 }}>
          <Button disabled={!bindingId || !responseFixture.trim()} loading={busy} onClick={() => void saveResponseMapping()}>验证并保存响应映射</Button>
          <Button onClick={() => void previewJson('recognition')}>预览响应 JSON 映射</Button>
        </Flex>
        <Input.TextArea rows={4} value={responseFixture} onChange={(event) => setResponseFixture(event.target.value)}
          placeholder="粘贴用于映射预览的真实响应 JSON。缺少真实响应时可先继续配置标准答案，但不能启动真实任务。" style={{ marginTop: 10 }} spellCheck={false} />
      </Card>

      <Card title="2. 给录音绑定标准答案 JSON">
        <Paragraph type="secondary">先在 ASR 音频页导入录音，再在下方对应录音行的“标准答案 JSON”列点击“绑定样例 JSON”选择文件。答案会保存为不可变版本并绑定当前音频版本；只配置样例中实际存在的字段，缺失的时间和说话人不会补造。</Paragraph>
        <Text strong>标准答案映射 JSON</Text>
        <Input.TextArea rows={4} value={groundTruthMappingText} onChange={(event) => setGroundTruthMappingText(event.target.value)} spellCheck={false} />
        <Flex gap="small" wrap="wrap" style={{ marginTop: 8 }}>
          <Button onClick={() => void previewJson('ground_truth')}>预览答案 JSON 映射</Button>
        </Flex>
        <Input.TextArea rows={3} value={answerFixture} onChange={(event) => setAnswerFixture(event.target.value)}
          placeholder="可粘贴答案 JSON 预览映射；正式配对请在录音行上传 JSON 文件。" style={{ marginTop: 10 }} spellCheck={false} />
        <Table rowKey="id" style={{ marginTop: 14 }} size="small" dataSource={audios} columns={audioColumns}
          rowSelection={{ selectedRowKeys: selectedAudioIds, onChange: (keys) => setSelectedAudioIds(keys.map(Number)) }}
          pagination={{ pageSize: 10 }} locale={{ emptyText: '当前项目还没有录音，请先在 ASR 音频列表中导入。' }} />
      </Card>

      <Card title="3. 创建单轮分析或自动调优">
        {!selectedBinding && <Alert type="warning" showIcon message="请先选择或创建接口绑定。" style={{ marginBottom: 16 }} />}
        {selectedBinding?.interface_updated && <Alert type="warning" showIcon message="来源接口已更新，请基于新接口重新绑定后再创建任务。" style={{ marginBottom: 16 }} />}
        {selectedBinding && <Alert type="info" showIcon message="基线来自接口请求示例" description="下面的值按接口导入示例初始化。截图中的 preset_spk_num=1 会保留为强制单人；文档默认 null 仅作为参数说明，不会替换当前基线。" style={{ marginBottom: 16 }} />}
        <Flex gap="middle" wrap="wrap" align="center">
          <div style={{ minWidth: 250, flex: 1 }}><Text>文本分析模型</Text><Select style={{ width: '100%' }} value={modelConfigId}
            placeholder="选择已授权的文本模型" options={models.map((item) => ({ value: item.id, label: `${item.label} · ${item.model_name}` }))}
            onChange={setModelConfigId} /></div>
          <div><Text>任务模式</Text><Select style={{ width: 190 }} value={mode} onChange={setMode}
            options={[{ value: 'AUTO_TUNE', label: '自动多轮调优' }, { value: 'ANALYZE', label: '单轮分析' }]} /></div>
        </Flex>
        <Title level={5} style={{ marginTop: 18 }}>FunASR 基线参数（JSON 顶层字段）</Title>
        <Input.TextArea rows={8} value={parameterText} onChange={(event) => setParameterText(event.target.value)} spellCheck={false} />
        <Paragraph type="secondary">不能包含 audio、parameters 包装或任务元数据。audio 会逐条注入。null、false、0 和空字符串均按原值保留。</Paragraph>
        <Text strong>允许搜索范围（空对象表示不自动调参）</Text>
        <Input.TextArea rows={4} value={allowedText} onChange={(event) => setAllowedText(event.target.value)} spellCheck={false}
          placeholder={'例如：{ "/target_rms_dbfs": { "minimum": -30, "maximum": -10 } }'} />
        <Paragraph type="secondary">只允许调优已勾选字段的范围；热词、固定人数、批处理性能字段默认锁定。speaker_merge_threshold 只有自动估计人数时生效，merge_length_s 只有 merge_vad=true 时生效。</Paragraph>
        <Descriptions size="small" column={{ xs: 1, md: 2 }} bordered style={{ marginTop: 12 }}>
          {definitions.map((item) => <Descriptions.Item key={item.path} label={<code>{item.path.slice(1)}</code>}>
            <Space wrap size={4}><Text>{item.value_type}</Text>
              <Text type="secondary">{item.exclusive_minimum != null ? `(${item.exclusive_minimum}, ${item.maximum}]` : item.minimum != null ? `[${item.minimum}, ${item.maximum}]` : '按类型限制'}</Text>
              {item.unit && <Text type="secondary">{item.unit}</Text>}
              {item.nullable && <Tag>可空</Tag>}{item.tunable ? <Tag color="blue">可调</Tag> : <Tag>默认固定</Tag>}
              <Text type="secondary">文档默认：{item.default === null ? 'null' : JSON.stringify(item.default)}</Text>
              {item.active_when && <Tag color={currentParameters[String(item.active_when.path).slice(1)] === item.active_when.equals ? 'green' : 'orange'}>
                {currentParameters[String(item.active_when.path).slice(1)] === item.active_when.equals ? '当前生效' : '当前不生效'}
              </Tag>}
            </Space>
            <div><Text type="secondary">{item.description}</Text>{item.tuning_note && <div><Text type="warning">{item.tuning_note}</Text></div>}</div>
          </Descriptions.Item>)}
        </Descriptions>
        <Divider />
        <Flex gap="middle" wrap="wrap" align="center">
          <label>最大轮数 <InputNumber min={1} max={100} value={maxRounds} onChange={(value) => setMaxRounds(Number(value ?? 1))} /></label>
          <label>ASR 请求预算 <InputNumber min={1} max={20000} value={maxAsrRequests} onChange={(value) => setMaxAsrRequests(Number(value ?? 1))} /></label>
          <label>AI 调用预算 <InputNumber min={1} max={100} value={maxAiCalls} onChange={(value) => setMaxAiCalls(Number(value ?? 1))} /></label>
          <label>连续无改善上限 <InputNumber min={1} max={20} value={noImprovementLimit} onChange={(value) => setNoImprovementLimit(Number(value ?? 1))} /></label>
          <label>失败录音上限 <InputNumber min={0} max={200} value={failedItemsLimit} onChange={(value) => setFailedItemsLimit(Number(value ?? 0))} /></label>
          <label>目标微平均 CER <InputNumber min={0} max={5} step={0.01} value={targetCer ?? undefined} onChange={(value) => setTargetCer(value ?? null)} placeholder="可选" /></label>
        </Flex>
        <Flex gap="middle" wrap="wrap" align="center" style={{ marginTop: 16 }}>
          <Checkbox checked={nightWindow} onChange={(event) => setNightWindow(event.target.checked)}>仅在夜间窗口发起新请求（Asia/Shanghai）</Checkbox>
          <label>开始 <Input value={nightStart} onChange={(event) => setNightStart(event.target.value)} style={{ width: 90 }} /></label>
          <label>结束 <Input value={nightEnd} onChange={(event) => setNightEnd(event.target.value)} style={{ width: 90 }} /></label>
        </Flex>
        <Paragraph type="secondary" style={{ marginTop: 8 }}>预算按请求次数控制；没有价格信息时不显示费用估算。窗口外不会开始新的 ASR 或 AI 调用，在途调用会完成并落盘。</Paragraph>
      <Button type="primary" size="large" loading={busy} disabled={!bindingId || !selectedBinding?.response_mapping_verified || !modelConfigId || !selectedAudioIds.length
          || Boolean(selectedBinding?.interface_updated) || selectedAudioIds.some((id) => !answerByAudioId.has(id))}
          onClick={() => void createSession()}>
          创建后台任务（{selectedAudioIds.length} 条录音）
        </Button>
        {selectedAudioIds.some((id) => !answerByAudioId.has(id)) && <Text type="danger" style={{ marginLeft: 12 }}>所选录音必须都有当前版本标准答案。</Text>}
      </Card>

      <Card title="4. 后台任务与轮次结果">
        <Table rowKey="id" size="small" dataSource={sessions} columns={sessionColumns} pagination={{ pageSize: 8 }}
          onRow={(row) => ({ onClick: () => { void funasrTuningApi.session(row.id).then(setSelectedSession).catch(() => message.error('读取任务详情失败')); } })}
          rowClassName={(row) => row.id === selectedSession?.id ? 'ant-table-row-selected' : ''}
          locale={{ emptyText: '尚无 FunASR AI 分析任务。' }} />
        {detail && <>
          <Divider />
          <Flex justify="space-between" align="center" wrap="wrap" gap="middle">
            <Space><Title level={5} style={{ margin: 0 }}>任务 #{detail.id}</Title>{statusTag(detail.status)}</Space>
            <Space wrap>
              {canPause && <Button disabled={busy} onClick={() => void actOnSession('pause')}>暂停</Button>}
              {canResume && <Button type="primary" disabled={busy} onClick={() => void actOnSession('resume')}>继续</Button>}
              {canRetryAsr && <Button disabled={busy} onClick={() => void actOnSession('retryFailed')}>修复映射 / 补跑失败阶段</Button>}
              {canRetryAi && <Button disabled={busy} onClick={() => void actOnSession('retryAnalysis')}>补跑 AI 分析</Button>}
              {canStop && <Button danger disabled={busy} onClick={() => void actOnSession('stop')}>停止</Button>}
            </Space>
          </Flex>
          {canRetryAsr && <Paragraph type="secondary" style={{ marginTop: 8 }}>已有识别响应的项目只会重新映射和评分，不会重发 ASR；没有收到响应的明确失败项才会按操作补跑请求。待核实项始终不会自动重发。</Paragraph>}
          <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ marginTop: 14 }}>
            <Descriptions.Item label="进度">{detail.completed_items}/{detail.total_items}</Descriptions.Item>
            <Descriptions.Item label="最佳轮次">{detail.best_round_id ?? '尚无完整轮次'}</Descriptions.Item>
            <Descriptions.Item label="最佳微平均 CER">{detail.best_micro_cer == null ? '—' : Number(detail.best_micro_cer).toFixed(5)}</Descriptions.Item>
            <Descriptions.Item label="ASR 预算">{detail.asr_requests_used}/{detail.max_asr_requests}</Descriptions.Item>
            <Descriptions.Item label="AI 预算">{detail.ai_calls_used}/{detail.max_ai_calls}</Descriptions.Item>
            <Descriptions.Item label="夜间窗口">{detail.window_enabled ? `${detail.night_start}–${detail.night_end} Asia/Shanghai` : '不限时段'}</Descriptions.Item>
            {detail.stop_reason && <Descriptions.Item label="停止原因" span={3}>{detail.stop_reason}</Descriptions.Item>}
          </Descriptions>
          <Collapse style={{ marginTop: 12 }} items={(detail.rounds ?? []).map((round) => ({
            key: round.id,
            label: <Space>第 {round.ordinal} 轮{statusTag(round.status)}<Text type="secondary">CER 微平均：{String(round.metrics?.micro_cer ?? '—')}{round.accepted === true ? ' · 新最佳' : round.accepted === false ? ' · 保留原最佳' : ''}</Text></Space>,
            children: <Space direction="vertical" style={{ width: '100%' }}>
              <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                <Descriptions.Item label="参数快照"><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(round.parameters, null, 2)}</pre></Descriptions.Item>
                <Descriptions.Item label="轮次指标"><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(round.metrics, null, 2)}</pre></Descriptions.Item>
              </Descriptions>
              {round.report_markdown && <><Text strong>整轮 AI 分析（引用证据已校验）</Text><pre style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflow: 'auto' }}>{round.report_markdown}</pre></>}
              {(round.items ?? []).map((item) => <Card key={item.id} size="small" title={`${audioById.get(item.audio_id)?.name ?? `录音 ${item.audio_id}`} · ${ERROR_MESSAGES[item.status] ?? item.status}`} extra={item.metrics?.cer == null ? 'CER 不可计算' : `CER ${Number(item.metrics.cer).toFixed(4)}`}>
                {item.error_message && <Alert type={item.status === 'RECONCILIATION_REQUIRED' ? 'warning' : 'error'} showIcon message={item.error_message} />}
                {item.review_json && <Paragraph>{String(item.review_json.summary ?? '')}</Paragraph>}
                {item.review_json?.findings != null && <Collapse items={[{ key: 'findings', label: '逐条 AI 分析与证据', children:
                  <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(item.review_json.findings, null, 2)}</pre> }]} />}
                {item.normalized_json && <Descriptions size="small" column={1}>
                  <Descriptions.Item label="标准答案全文">{String(item.ground_truth_json?.transcript ?? '')}</Descriptions.Item>
                  <Descriptions.Item label="识别全文">{String(item.normalized_json.transcript ?? '')}</Descriptions.Item>
                  <Descriptions.Item label="CER 计数">{JSON.stringify(item.metrics)}</Descriptions.Item>
                </Descriptions>}
                {(item.answer_markdown || item.response_markdown) && <Collapse items={[{ key: 'markdown', label: '标准答案与识别结果 Markdown', children:
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {item.answer_markdown && <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>{item.answer_markdown}</pre>}
                    {item.response_markdown && <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>{item.response_markdown}</pre>}
                  </Space> }]} />}
                {item.response_json != null && <Collapse items={[{ key: 'json', label: '脱敏识别响应 JSON', children: <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>{JSON.stringify(item.response_json, null, 2)}</pre> }]} />}
              </Card>)}
            </Space>,
          }))} />
        </>}
      </Card>
      {previewMarkdown && <Card title="确定性 Markdown 预览" extra={<Button onClick={() => setPreviewMarkdown(undefined)}>关闭</Button>}>
        <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 480, overflow: 'auto' }}>{previewMarkdown}</pre>
      </Card>}
      <Card size="small" title="参数约束速查"><Paragraph type="secondary" style={{ marginBottom: 0 }}>
        speaker_merge_threshold 范围为 (0,1]，仅 preset_spk_num=null 时生效；当前因未实现说话人错误指标而锁定。merge_length_s 仅 merge_vad=true 时生效。热词默认固定，不从标准答案自动生成。接口服务的异步提交协议和幂等能力尚未配置；同步超时/服务端 5xx 会停在待核实，不会自动重发。
      </Paragraph></Card>
    </Space>}
  </AsrFrame>;
}
