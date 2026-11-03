// 音频列表：管理授权 URL、版本和可达性；原始签名查询串不会在页面回显。
import { App, Button, Empty, Form, Input, Modal, Space, Table, Tag, Typography } from 'antd';
import { EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import type { AsrAudio } from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { LoadingState, ErrorState } from '@/shared/ui/PageState';

interface AudioFormValues {
  name: string;
  url: string;
  batch_text?: string;
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
  const queryClient = useQueryClient();
  const [form] = Form.useForm<AudioFormValues>();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [batchMode, setBatchMode] = useState(false);
  const [batchInput, setBatchInput] = useState('');
  const [editingAudio, setEditingAudio] = useState<AsrAudio | null>(null);
  const batchPreview = useMemo(() => {
    if (!batchInput.trim()) return { count: 0, error: '' };
    try { return { count: parsePastedAudioRecords(batchInput).length, error: '' }; }
    catch (error) { return { count: 0, error: error instanceof Error ? error.message : '粘贴内容格式无效' }; }
  }, [batchInput]);
  useEffect(() => { setPage(1); setKeyword(''); }, [currentProjectId]);
  const key = currentProjectId ? asrQueryKeys.project(currentProjectId, 'audio', page, pageSize, keyword) : ['asr', 'audio', null, page, pageSize, keyword];
  const audioQuery = useQuery({
    queryKey: key,
    enabled: Boolean(currentProjectId),
    queryFn: async ({ signal }) =>
      (await asrEvaluationApi.listAudios(currentProjectId!, page, pageSize, signal, keyword)),
  });
  const importMutation = useMutation({
    mutationFn: async (values: AudioFormValues) => {
      if (editingAudio) {
        await asrEvaluationApi.updateAudio(editingAudio.id, {
          name: values.name, url: values.url?.trim() || undefined,
        });
      } else if (values.batch_text?.trim()) {
        const items = parsePastedAudioRecords(values.batch_text);
        await asrEvaluationApi.importAudios(currentProjectId!, items);
      } else {
        await asrEvaluationApi.importAudios(currentProjectId!, [{
          name: values.name.trim(), url: values.url.trim(),
        }]);
      }
    },
    onSuccess: () => {
      message.success(editingAudio ? '音频资源已更新' : '音频链接已加入项目');
      setOpen(false);
      setEditingAudio(null);
      form.resetFields();
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

  /** 音频表格列展示脱敏 URL、版本和真实可达性状态。 */
  const columns = [
    { title: '音频名称', dataIndex: 'name', key: 'name', width: 220 },
    {
      title: '音频 URL', dataIndex: 'url_display', key: 'url_display',
      render: (value: string) => <Typography.Text copyable={{ text: value }} ellipsis style={{ maxWidth: 420 }}>{value}</Typography.Text>,
    },
    {
      title: '时长', dataIndex: 'duration_seconds', key: 'duration_seconds', width: 110,
      render: (value: number | null) => value ? Math.floor(value / 60) + ' 分 ' + (value % 60) + ' 秒' : '未填写',
    },
    {
      title: '状态', dataIndex: 'availability', key: 'availability', width: 140,
      render: (value: string) => <Tag color={value === 'AVAILABLE' ? 'green' : value === 'PLATFORM_DENIED' ? 'red' : 'default'}>
        {value === 'AVAILABLE' ? '可访问' : value === 'PLATFORM_DENIED' ? '出站未授权' : value === 'UNREACHABLE' ? '源不可达' : '待检查'}
      </Tag>,
    },
    { title: '内容版本', dataIndex: 'content_version', key: 'content_version', width: 100, render: (value: number) => 'v' + value },
    {
      title: '操作', key: 'action', width: 190,
      render: (_: unknown, row: AsrAudio) => <Space>
        <Button size="small" icon={<EditOutlined />} onClick={() => {
          setEditingAudio(row);
          form.setFieldsValue({ name: row.name, url: '' });
          setOpen(true);
        }}>编辑</Button>
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
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingAudio(null); setBatchMode(false); setBatchInput(''); form.resetFields(); setOpen(true); }}>添加音频</Button>
          <Button icon={<PlusOutlined />} onClick={() => { setEditingAudio(null); setBatchMode(true); setBatchInput(''); form.resetFields(); setOpen(true); }}>批量导入</Button>
          <Button icon={<ReloadOutlined />} onClick={() => void audioQuery.refetch()}>刷新</Button>
          <Input.Search aria-label="按名称筛选音频" allowClear placeholder="按音频名称筛选" value={keyword}
            onChange={(event) => { setKeyword(event.target.value); setPage(1); }} style={{ width: 260 }} />
          <Typography.Text type="secondary">只保存链接与版本信息；平台播放权限和云端可达性分开检查。</Typography.Text>
        </Space>
        <Table<AsrAudio>
          rowKey="id" columns={columns} dataSource={audioQuery.data?.items ?? []}
          locale={{ emptyText: <Empty description="还没有音频链接，导入后即可创建夜间评测任务" /> }}
          pagination={{ current: page, pageSize, total: audioQuery.data?.total ?? 0, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], onChange: (nextPage, nextPageSize) => { setPage(nextPageSize !== pageSize ? 1 : nextPage); setPageSize(nextPageSize); } }}
          scroll={{ x: 1000 }}
        />
      </Space>
      <Modal
        title={editingAudio ? '编辑音频资源' : batchMode ? '批量导入音频' : '添加音频'} open={open} onCancel={() => { setOpen(false); setEditingAudio(null); setBatchInput(''); form.resetFields(); }}
        confirmLoading={importMutation.isPending}
        onOk={() => form.submit()}
      >
        <Form<AudioFormValues>
          form={form}
          layout="vertical"
          onValuesChange={(changed) => { if (typeof changed.batch_text === 'string') setBatchInput(changed.batch_text); }}
          onFinish={(values) => importMutation.mutate(values)}
        >
          {!batchMode && <Form.Item name="name" label="音频名称" rules={[{ required: !editingAudio, whitespace: true, message: '请输入音频名称' }]}>
            <Input maxLength={200} placeholder="例如：会议录音 2026-11-02" />
          </Form.Item>}
          {!batchMode && <Form.Item name="url" label={editingAudio ? '替换音频 URL（留空保留现有链接）' : '音频 URL'} rules={[{ required: !editingAudio, type: 'url', message: '请输入有效的 HTTP 或 HTTPS 地址' }]}>
            <Input placeholder={editingAudio ? '留空不更换 URL' : 'https://音频服务/文件.mp3?临时签名'} />
          </Form.Item>}
          {batchMode && <Form.Item name="batch_text" label="粘贴音频名称和 URL" rules={[{ required: true, whitespace: true, message: '请粘贴音频名称和 URL' }]}>
            <Input.TextArea
              rows={10}
              spellCheck={false}
              placeholder={'每条音频两行：名称在前，URL 在后；名称末尾冒号可保留。\n\n声音小，噪音大：\nhttps://音频服务/文件1.m4a\n技师顾客全为女：\nhttps://音频服务/文件2.m4a'}
            />
          </Form.Item>}
          {batchMode && batchInput.trim() && <Typography.Text type={batchPreview.error ? 'danger' : 'secondary'}>
            {batchPreview.error || `已识别 ${batchPreview.count} 条音频（最多 200 条）`}
          </Typography.Text>}
          {!batchMode && <Typography.Text type="secondary">
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
