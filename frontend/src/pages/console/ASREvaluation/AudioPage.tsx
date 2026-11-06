// 音频列表：管理授权 URL、版本和可达性；原始签名查询串不会在页面回显。
import { App, Button, Empty, Form, Input, Modal, Space, Table, Tag, Typography } from 'antd';
import { EditOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons';
import { Upload } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import { funasrTuningApi } from '@/features/asr-evaluation/api/funasrTuning';
import type { AsrAudio, JsonValue } from '@/features/asr-evaluation/contracts';
import type { FunAsrGroundTruth } from '@/features/asr-evaluation/api/funasrTuning';
import { AsrFrame } from './AsrFrame';
import { LoadingState, ErrorState } from '@/shared/ui/PageState';
import { useNavigate } from 'react-router-dom';

interface AudioFormValues {
  name: string;
  url: string;
  batch_text?: string;
}

type AudioFormMode = 'CREATE' | 'IMPORT' | 'EDIT';

const SAMPLE_JSON_MAPPING: Record<string, unknown> = {
  text_source: 'segments',
  segments_pointer: '',
  segment_text_pointer: '/text',
  start_pointer: '/start',
  end_pointer: '/end',
  speaker_pointer: '/spk',
  time_unit: 'ms',
};

function validateSampleJson(document: JsonValue): asserts document is JsonValue[] {
  if (!Array.isArray(document) || document.length === 0) {
    throw new Error('样例 JSON 须为非空数组，每段包含 start、end、spk、text 字段');
  }
  const invalidIndex = document.findIndex((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return true;
    const row = item as Record<string, JsonValue>;
    return typeof row.text !== 'string'
      || typeof row.start !== 'number' || !Number.isFinite(row.start) || row.start < 0
      || typeof row.end !== 'number' || !Number.isFinite(row.end) || row.end <= row.start
      || (typeof row.spk !== 'number' && typeof row.spk !== 'string' && row.spk !== null);
  });
  if (invalidIndex >= 0) {
    throw new Error(`第 ${invalidIndex + 1} 段格式无效；需要有效的 start/end、spk 和 text 字段`);
  }
}

/**
 * 解析用户从音频清单复制的名称与 URL 交替文本。
 *
 * 每个非空名称行后必须跟一行 HTTP(S) 地址；名称末尾冒号和空行允许存在。
 * 解析失败抛出中文错误，记录超过 200 条时拒绝继续导入。
 */
function parsePastedAudioRecords(value: string): Array<{ name: string; url: string }> {
  const lines = value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const records: Array<{ name: string; url: string }> = [];
  let pendingName = '';

  for (const line of lines) {
    if (/^https?:\/\//i.test(line)) {
      if (!pendingName) throw new Error('发现音频 URL 前没有名称，请按“名称一行、URL 一行”粘贴');
      let parsedUrl: URL;
      try { parsedUrl = new URL(line); }
      catch { throw new Error('音频 URL 格式无效，请检查地址'); }
      if (!['http:', 'https:'].includes(parsedUrl.protocol)) throw new Error('音频 URL 仅支持 HTTP(S) 地址');
      records.push({ name: pendingName, url: line });
      pendingName = '';
      if (records.length > 200) throw new Error('批量导入最多支持 200 条音频');
      continue;
    }

    if (pendingName) throw new Error(`“${pendingName}”后缺少音频 URL，请检查粘贴内容`);
    pendingName = line.replace(/[:：]\s*$/, '').trim();
    if (!pendingName) throw new Error('音频名称不能为空');
  }

  if (pendingName) throw new Error(`“${pendingName}”后缺少音频 URL`);
  if (records.length === 0) throw new Error('没有识别到音频记录，请粘贴名称和 URL');
  return records;
}

/** 音频资产列表和导入弹窗；链接检查不会把上游不可达直接写成无效。 */
export function AudioPage() {
  const { message } = App.useApp();
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<AudioFormValues>();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [formMode, setFormMode] = useState<AudioFormMode>('CREATE');
  const [batchInput, setBatchInput] = useState('');
  const [editingAudio, setEditingAudio] = useState<AsrAudio | null>(null);
  const batchPreview = useMemo(() => {
    if (!batchInput.trim()) return { count: 0, error: '' };
    try { return { count: parsePastedAudioRecords(batchInput).length, error: '' }; }
    catch (error) { return { count: 0, error: error instanceof Error ? error.message : '粘贴内容格式无效' }; }
  }, [batchInput]);
  const closeForm = () => {
    setOpen(false);
    setEditingAudio(null);
    setBatchInput('');
    form.resetFields();
  };
  const openForm = (mode: AudioFormMode, audio?: AsrAudio) => {
    setFormMode(mode);
    setEditingAudio(audio ?? null);
    setBatchInput('');
    form.resetFields();
    if (audio) form.setFieldsValue({ name: audio.name, url: '' });
    setOpen(true);
  };
  useEffect(() => {
    setPage(1);
    setKeyword('');
    setOpen(false);
    setEditingAudio(null);
    setBatchInput('');
    form.resetFields();
  }, [currentProjectId, form]);
  const key = currentProjectId ? asrQueryKeys.project(currentProjectId, 'audio', page, pageSize, keyword) : ['asr', 'audio', null, page, pageSize, keyword];
  const audioQuery = useQuery({
    queryKey: key,
    enabled: Boolean(currentProjectId),
    queryFn: async ({ signal }) =>
      (await asrEvaluationApi.listAudios(currentProjectId!, page, pageSize, signal, keyword)),
  });
  const audioIds = audioQuery.data?.items.map((item) => item.id) ?? [];
  const recentRunsQuery = useQuery({
    queryKey: currentProjectId ? asrQueryKeys.project(currentProjectId, 'audio-recent-runs', audioIds) : ['asr', 'audio-recent-runs', null],
    enabled: Boolean(currentProjectId && audioIds.length),
    queryFn: ({ signal }) => asrEvaluationApi.getRecentAudioRuns(currentProjectId!, audioIds, signal),
  });
  const recentRuns = new Map((recentRunsQuery.data?.items ?? []).map((item) => [item.audio_id, item]));
  const groundTruthQuery = useQuery({
    queryKey: currentProjectId ? asrQueryKeys.project(currentProjectId, 'funasr-ground-truth') : ['asr', 'funasr-ground-truth', null],
    enabled: Boolean(currentProjectId),
    queryFn: () => funasrTuningApi.groundTruth(currentProjectId!),
  });
  const groundTruthByAudioId = new Map((groundTruthQuery.data?.items ?? []).map((item: FunAsrGroundTruth) => [item.audio_id, item]));
  const importMutation = useMutation({
    mutationFn: async (values: AudioFormValues) => {
      if (formMode === 'EDIT' && editingAudio) {
        await asrEvaluationApi.updateAudio(editingAudio.id, {
          name: values.name, url: values.url?.trim() || undefined,
        });
      } else if (formMode === 'IMPORT' && values.batch_text?.trim()) {
        const items = parsePastedAudioRecords(values.batch_text);
        await asrEvaluationApi.importAudios(currentProjectId!, items);
      } else {
        await asrEvaluationApi.importAudios(currentProjectId!, [{
          name: values.name.trim(), url: values.url.trim(),
        }]);
      }
    },
    onSuccess: () => {
      message.success(formMode === 'EDIT' ? '音频资源已更新' : formMode === 'IMPORT' ? '音频链接已加入项目' : '音频已加入项目');
      closeForm();
      void queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (error) => message.error(error instanceof Error ? error.message : getErrorMessage(error, '导入音频失败')),
  });
  const checkMutation = useMutation({
    mutationFn: (audioId: number) => asrEvaluationApi.checkAudio(audioId),
    onSuccess: (data) => {
      const value = data as { audio_source?: string; platform_access?: string };
      message.info(value.audio_source === 'HEAD_NOT_SUPPORTED'
        ? '音频源不支持 HEAD；可达性保持未知'
        : value.platform_access === 'DENIED' ? '该目标尚未加入项目出站授权' : '已更新音频源检查结果');
      void queryClient.invalidateQueries({ queryKey: key });
    },
    onError: (error) => message.error(getErrorMessage(error, '检查音频链接失败')),
  });
  const uploadGroundTruthMutation = useMutation({
    mutationFn: async ({ audioId, file }: { audioId: number; file: File }) => {
      if (file.size > 5_000_000) throw new Error('样例 JSON 不能超过 5 MB');
      let document: JsonValue;
      try { document = JSON.parse(await file.text()) as JsonValue; }
      catch { throw new Error('文件不是有效 JSON'); }
      validateSampleJson(document);
      return funasrTuningApi.createGroundTruth(audioId, document, SAMPLE_JSON_MAPPING);
    },
    onSuccess: (_result, { audioId }) => {
      message.success(`已为音频 #${audioId} 绑定样例 JSON`);
      if (currentProjectId) {
        void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(currentProjectId, 'funasr-ground-truth') });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '绑定样例 JSON 失败')),
  });

  /** 音频表格列展示脱敏 URL、版本和真实可达性状态。 */
  const columns = [
    { title: '音频名称', dataIndex: 'name', key: 'name', width: 220 },
    {
      title: '对应样例 JSON', key: 'ground_truth', width: 200,
      render: (_: unknown, row: AsrAudio) => {
        const answer = groundTruthByAudioId.get(row.id);
        const uploading = uploadGroundTruthMutation.isPending && uploadGroundTruthMutation.variables?.audioId === row.id;
        return <Space direction="vertical" size={4}>
          {answer ? <Tag color="green">已绑定 v{answer.version}</Tag> : <Tag color="orange">未绑定</Tag>}
          <Upload accept=".json,application/json" maxCount={1} showUploadList={false}
            disabled={uploadGroundTruthMutation.isPending}
            beforeUpload={(file) => {
              uploadGroundTruthMutation.mutate({ audioId: row.id, file });
              return false;
            }}>
            <Button size="small" icon={<UploadOutlined />} loading={uploading} disabled={uploadGroundTruthMutation.isPending}>
              {answer ? '更换 JSON' : '上传 JSON'}
            </Button>
          </Upload>
        </Space>;
      },
    },
    {
      title: '音频 URL', dataIndex: 'url_display', key: 'url_display',
      render: (value: string) => <Typography.Text copyable={{ text: value }} ellipsis style={{ maxWidth: 420 }}>{value}</Typography.Text>,
    },
    {
      title: '时长', dataIndex: 'duration_seconds', key: 'duration_seconds', width: 110,
      render: (value: number | null) => value ? Math.floor(value / 60) + ' 分 ' + (value % 60) + ' 秒' : '尚未解析',
    },
    {
      title: '状态', dataIndex: 'availability', key: 'availability', width: 140,
      render: (value: string) => <Tag color={value === 'AVAILABLE' ? 'green' : value === 'PLATFORM_DENIED' ? 'red' : 'default'}>
        {value === 'AVAILABLE' ? '可访问' : value === 'PLATFORM_DENIED' ? '出站未授权' : value === 'UNREACHABLE' ? '源不可达' : '待检查'}
      </Tag>,
    },
    { title: '内容版本', dataIndex: 'content_version', key: 'content_version', width: 100, render: (value: number) => 'v' + value },
    {
      title: '操作', key: 'action', width: 340,
      render: (_: unknown, row: AsrAudio) => <Space wrap>
        <Button size="small" type="primary" onClick={() => navigate(`/console/asr/jobs?audio_id=${row.id}`)}>开始评测</Button>
        {recentRuns.get(row.id) && <Space size={4}>
          <Button size="small" onClick={() => navigate(`/console/asr/runs/${recentRuns.get(row.id)!.run_id}`)}>查看最近结果</Button>
          <Button size="small" onClick={() => navigate(`/console/asr/jobs/${recentRuns.get(row.id)!.job_id}`)}>最近任务</Button>
        </Space>}
        <Button size="small" icon={<EditOutlined />} onClick={() => openForm('EDIT', row)}>编辑</Button>
        <Button
          size="small" icon={<ReloadOutlined />} loading={checkMutation.isPending && checkMutation.variables === row.id}
          onClick={() => checkMutation.mutate(row.id)}
        >检查链接</Button>
      </Space>,
    },
  ];

  if (!currentProjectId) return <AsrFrame title="音频列表"><Empty description="先选择项目再管理音频链接" /></AsrFrame>;
  if (audioQuery.isPending) return <AsrFrame title="音频列表"><LoadingState /></AsrFrame>;
  if (audioQuery.isError) return <AsrFrame title="音频列表"><ErrorState error={audioQuery.error} onRetry={audioQuery.refetch} /></AsrFrame>;

  return (
    <AsrFrame title="音频列表">
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space wrap>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm('CREATE')}>添加音频</Button>
          <Button icon={<PlusOutlined />} onClick={() => openForm('IMPORT')}>批量导入</Button>
          <Button icon={<ReloadOutlined />} onClick={() => void audioQuery.refetch()}>刷新</Button>
          <Input.Search aria-label="按名称筛选音频" allowClear placeholder="按音频名称筛选" value={keyword}
            onChange={(event) => { setKeyword(event.target.value); setPage(1); }} style={{ width: 260 }} />
          <Typography.Text type="secondary">每行“对应样例 JSON”列可上传该音频的 JSON；自动映射 text/start/end/spk，时间单位为毫秒。音频本身只保存链接与版本信息。</Typography.Text>
        </Space>
        {recentRunsQuery.isError && <Typography.Text type="warning">最近任务链接读取失败；可从评测任务列表查找。</Typography.Text>}
        <Table<AsrAudio>
          rowKey="id" columns={columns} dataSource={audioQuery.data?.items ?? []}
          locale={{ emptyText: <Empty description="还没有音频链接，导入后即可创建夜间评测任务" /> }}
          pagination={{ current: page, pageSize, total: audioQuery.data?.total ?? 0, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], onChange: (nextPage, nextPageSize) => { setPage(nextPageSize !== pageSize ? 1 : nextPage); setPageSize(nextPageSize); } }}
          scroll={{ x: 1000 }}
        />
      </Space>
      <Modal
        title={formMode === 'EDIT' ? '编辑音频资源' : formMode === 'IMPORT' ? '批量导入音频' : '添加音频'} open={open} onCancel={closeForm}
        confirmLoading={importMutation.isPending}
        onOk={() => form.submit()}
      >
        <Form<AudioFormValues>
          form={form}
          layout="vertical"
          onValuesChange={(changed) => { if (typeof changed.batch_text === 'string') setBatchInput(changed.batch_text); }}
          onFinish={(values) => importMutation.mutate(values)}
        >
          {formMode !== 'IMPORT' && <Form.Item name="name" label="音频名称" rules={[{ required: formMode === 'CREATE', whitespace: true, message: '请输入音频名称' }]}>
            <Input maxLength={200} placeholder="例如：会议录音 2026-11-02" />
          </Form.Item>}
          {formMode !== 'IMPORT' && <Form.Item name="url" label={formMode === 'EDIT' ? '替换音频 URL（留空保留现有链接）' : '音频 URL'} rules={[{ required: formMode === 'CREATE', type: 'url', message: '请输入有效的 HTTP 或 HTTPS 地址' }]}>
            <Input placeholder={formMode === 'EDIT' ? '留空不更换 URL' : 'https://音频服务/文件.mp3?临时签名'} />
          </Form.Item>}
          {formMode === 'IMPORT' && <Form.Item name="batch_text" label="粘贴音频名称和 URL" rules={[{ required: true, whitespace: true, message: '请粘贴音频名称和 URL' }]}>
            <Input.TextArea
              rows={10}
              spellCheck={false}
              placeholder={'每条音频两行：名称在前，URL 在后；名称末尾冒号可保留。\n\n声音小，噪音大：\nhttps://音频服务/文件1.m4a\n技师顾客全为女：\nhttps://音频服务/文件2.m4a'}
            />
          </Form.Item>}
          {formMode === 'IMPORT' && batchInput.trim() && <Typography.Text type={batchPreview.error ? 'danger' : 'secondary'}>
            {batchPreview.error || `已识别 ${batchPreview.count} 条音频（最多 200 条）`}
          </Typography.Text>}
          {formMode !== 'IMPORT' && <Typography.Text type="secondary">
            只需填写音频名称和 HTTP(S) URL，时长等信息由平台按需解析。
          </Typography.Text>}
          <Typography.Paragraph className="asr-muted-note">
            URL 和查询参数加密保存；列表只显示不含签名查询串的地址。播放和 ASR 请求都会重新检查项目出站策略。
          </Typography.Paragraph>
        </Form>
      </Modal>
    </AsrFrame>
  );
}
