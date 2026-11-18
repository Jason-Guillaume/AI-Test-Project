// 缺陷推送到飞书的配置弹窗。
// 渠道来自已接入的通知渠道，不要求用户再次填写 Webhook。
// 分享凭证只在本次成功或失败响应中展示，关闭弹窗后不能再从历史接口取回。
import { Alert, App, Button, Checkbox, Form, Input, Modal, Radio, Space, Switch, Typography } from 'antd';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { bugsApi } from '@/features/defects/api/defects';
import type { Bug, DefectShareBatchResult, DefectShareField, DefectSharePushResult } from '@/features/defects/contracts';
import { notificationChannelsApi } from '@/features/notifications/api/notificationChannels';
import { getErrorMessage } from '@/shared/api/client';

const DEFAULT_FIELDS: DefectShareField[] = [
  'bug_no', 'title', 'severity', 'status', 'project_name', 'description',
  'steps_to_reproduce', 'environment', 'expected_result', 'actual_result',
  'created_at', 'reporter', 'assignee',
  'api_method', 'api_url', 'api_request_headers', 'api_request_body', 'api_response', 'attachments',
];
const OPTIONAL_FIELDS: Array<{ value: DefectShareField; label: string }> = [
  { value: 'api_execution', label: '关联接口自动化执行' },
  { value: 'agent_execution', label: '关联 Agent 执行记录' },
  { value: 'security_record', label: '关联安全测试记录' },
  { value: 'request_response', label: '请求和响应详情（脱敏后）' },
  { value: 'error_stack', label: '错误信息' },
  { value: 'screenshots', label: '测试截图' },
  { value: 'allure', label: 'Allure 报告入口' },
];
const FIELD_LABELS: Record<string, string> = {
  bug_no: '缺陷编号', title: '缺陷标题', severity: '严重度', status: '当前状态',
  project_name: '项目名称', description: '缺陷描述', steps_to_reproduce: '复现步骤',
  environment: '发现环境', expected_result: '预期结果', actual_result: '实际结果',
  created_at: '创建时间', reporter: '创建人', assignee: '当前处理人',
  api_method: '接口请求方法', api_url: '接口地址', api_request_headers: '接口请求头（脱敏）',
  api_request_body: '接口请求体（脱敏）', api_response: '接口响应正文（脱敏）', attachments: '附件',
};

interface ShareForm {
  channel_id: number;
  visible_fields: DefectShareField[];
  expires_in_days: 7 | 30 | 90 | 'permanent';
  allow_resolve: boolean;
}

/**
 * 打开推送配置。bugs 至少一条，且必须属于同一个项目。
 * canPermanent 为 false 时不展示永久有效选项。
 */
export function DefectShareModal({
  bugs, canPermanent, onClose,
}: {
  bugs: Array<Pick<Bug, 'id' | 'project_id'>>;
  canPermanent: boolean;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<ShareForm>();
  const [results, setResults] = useState<DefectSharePushResult[] | null>(null);
  const [batchResult, setBatchResult] = useState<DefectShareBatchResult | null>(null);
  const requestKey = useRef<{ signature: string; key: string } | null>(null);
  const projectId = bugs[0]?.project_id;
  const channels = useQuery({
    queryKey: ['notification-channels', projectId, 'share'],
    queryFn: () => notificationChannelsApi.list(projectId),
    enabled: projectId != null,
  });
  const values = Form.useWatch([], form);
  const previewBody = useMemo(() => {
    if (!values?.channel_id || !bugs.length) return null;
    return {
      bug_ids: bugs.map((bug) => bug.id),
      channel_id: values.channel_id,
      visible_fields: values.visible_fields,
      expires_in_days: values.expires_in_days === 'permanent' ? 7 : values.expires_in_days,
      permanent: values.expires_in_days === 'permanent',
      allow_resolve: values.allow_resolve,
      allow_view: true,
    };
  }, [bugs, values]);
  const preview = useQuery({
    queryKey: ['defect-share-preview', previewBody],
    queryFn: () => bugsApi.previewShare(previewBody!),
    enabled: previewBody != null,
  });
  const push = useMutation({
    mutationFn: async () => {
      const current = await form.validateFields();
      const bodyWithoutKey = {
        channel_id: current.channel_id,
        visible_fields: current.visible_fields,
        expires_in_days: current.expires_in_days === 'permanent' ? 7 : current.expires_in_days,
        permanent: current.expires_in_days === 'permanent',
        allow_resolve: current.allow_resolve,
        allow_view: true,
      };
      const signature = JSON.stringify({ bug_ids: bugs.map((bug) => bug.id), ...bodyWithoutKey });
      if (!requestKey.current || requestKey.current.signature !== signature) {
        requestKey.current = {
          signature,
          key: typeof crypto !== 'undefined' && 'randomUUID' in crypto
            ? crypto.randomUUID()
            : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
        };
      }
      const body = { ...bodyWithoutKey, request_key: requestKey.current.key };
      if (bugs.length === 1) return { kind: 'single' as const, items: [await bugsApi.share(bugs[0].id, body)] };
      return { kind: 'batch' as const, batch: await bugsApi.shareBatch({ ...body, bug_ids: bugs.map((bug) => bug.id) }) };
    },
    onSuccess: (result) => {
      if (result.kind === 'single') setResults(result.items);
      else setBatchResult(result.batch);
    },
  });

  useEffect(() => {
    form.setFieldsValue({ visible_fields: DEFAULT_FIELDS, expires_in_days: 7, allow_resolve: true });
  }, [form]);

  /**
   * 复制本次返回的链接。剪贴板受限时提示从只读输入框手动复制，不抛出未捕获异常。
   */
  async function copy(url: string) {
    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        message.warning('当前浏览器不支持一键复制，请在下方输入框全选复制');
        return;
      }
      await navigator.clipboard.writeText(url);
      message.success('分享链接已复制');
    } catch {
      message.warning('剪贴板写入受限，请在下方输入框手动全选复制');
    }
  }

  return (
    <Modal
      open
      width={760}
      title={bugs.length > 1 ? `批量推送 ${bugs.length} 条缺陷` : '推送到飞书'}
      onCancel={onClose}
      destroyOnHidden
      footer={results || batchResult ? [<Button key="close" type="primary" onClick={onClose}>完成</Button>] : [
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="ok" type="primary" loading={push.isPending} disabled={preview.data?.public_url_valid === false} onClick={() => push.mutate()}>确认推送</Button>,
      ]}
    >
      {batchResult ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            type={batchResult.notification_status === 'SUCCESS' ? 'success' : batchResult.notification_status === 'UNCERTAIN' ? 'warning' : 'error'}
            showIcon
            message={`${batchResult.items.length} 条缺陷 · ${batchResult.notification_status === 'SUCCESS' ? '已发送一张飞书卡片' : batchResult.notification_status === 'UNCERTAIN' ? '投递结果待确认' : '投递失败'}`}
            description={batchResult.error_message || `飞书卡片包含 ${batchResult.items.length} 条缺陷和一个批次入口。`}
          />
          {batchResult.batch_share_url ? <>
            {!batchResult.url_is_absolute && <Typography.Text type="danger">PUBLIC_APP_BASE_URL 配置异常，当前链接不是可访问的绝对域名地址。</Typography.Text>}
            <Input readOnly value={batchResult.batch_share_url} onFocus={(event) => event.target.select()} aria-label="批次分享链接" />
            <Button size="small" onClick={() => copy(batchResult.batch_share_url!)}>复制批次链接</Button>
          </> : <Typography.Text type="secondary">该请求已处理过；凭证只在首次签发时返回。请从首次响应中复制链接，或从历史执行重试。</Typography.Text>}
        </Space>
      ) : results ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          {results.map((item) => (
            <Alert
              key={item.share_id}
              type={item.notification_status === 'SUCCESS' ? 'success' : item.notification_status === 'UNCERTAIN' ? 'warning' : 'error'}
              showIcon
              message={`${item.bug_no} ${item.notification_status === 'SUCCESS' ? '已推送到' : item.notification_status === 'UNCERTAIN' ? '投递结果待确认' : '推送失败'} ${item.channel_name}`}
              description={<Space direction="vertical" style={{ width: '100%' }}>
                <Typography.Text>{item.error_message || '分享链接只显示这一次。飞书发送失败时链接仍然有效，可以复制后重试。'}</Typography.Text>
                {!item.url_is_absolute && <Typography.Text type="danger">PUBLIC_APP_BASE_URL 配置异常，当前链接不是可访问的绝对域名地址。</Typography.Text>}
                {item.share_url && <Typography.Paragraph style={{ marginBottom: 0 }}>{item.share_url}</Typography.Paragraph>}
                <Input
                  readOnly
                  value={item.share_url ?? ''}
                  onFocus={(event) => event.target.select()}
                  aria-label={`分享链接 ${item.bug_no}`}
                />
                {item.share_url && <Button size="small" onClick={() => copy(item.share_url!)}>复制链接</Button>}
              </Space>}
            />
          ))}
        </Space>
      ) : (
        <Form form={form} layout="vertical" initialValues={{ visible_fields: DEFAULT_FIELDS, expires_in_days: 7, allow_resolve: true }}>
          <Form.Item name="channel_id" label="飞书群聊" rules={[{ required: true, message: '请选择已接入的飞书群聊' }]}>
            <Radio.Group>
              <Space direction="vertical">
                {(channels.data?.items ?? []).map((channel) => (
                  <Radio key={channel.id} value={channel.id} disabled={!channel.enabled}>
                    {channel.name} · {channel.enabled ? '已启用' : '已停用'} · {channel.webhook_configured ? 'Webhook 已配置' : 'Webhook 未配置'}
                  </Radio>
                ))}
              </Space>
            </Radio.Group>
          </Form.Item>
          {!channels.isFetching && (channels.data?.items.length ?? 0) === 0 && <Alert type="info" showIcon message="当前项目还没有飞书群聊，请先在通知渠道中接入。" />}
          <Form.Item name="visible_fields" label="推送内容">
            <Checkbox.Group style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {DEFAULT_FIELDS.map((field) => <Checkbox key={field} value={field}>{FIELD_LABELS[field]}</Checkbox>)}
              {OPTIONAL_FIELDS.map((field) => <Checkbox key={field.value} value={field.value}>{field.label}</Checkbox>)}
            </Checkbox.Group>
          </Form.Item>
          <Form.Item name="expires_in_days" label="分享有效期">
            <Radio.Group>
              <Radio value={7}>7 天</Radio>
              <Radio value={30}>30 天</Radio>
              <Radio value={90}>90 天</Radio>
              {canPermanent && <Radio value="permanent">永久有效</Radio>}
            </Radio.Group>
          </Form.Item>
          <Form.Item name="allow_resolve" label="允许开发人员提交已解决" valuePropName="checked">
            <Switch />
          </Form.Item>
          {preview.data?.public_url_valid === false && preview.data.public_url_error && (
            <Alert
              style={{ marginBottom: 12 }}
              type="error"
              showIcon
              message="平台外链配置校验未通过"
              description={preview.data.public_url_error}
            />
          )}
          <Alert
            type={preview.isError ? 'error' : 'info'}
            showIcon
            message="推送预览"
            description={preview.isError ? getErrorMessage(preview.error, '预览失败') : preview.data?.message_preview || '选择群聊后显示预览'}
          />
          {push.isError && <Alert style={{ marginTop: 12 }} type="error" showIcon message={getErrorMessage(push.error, '推送失败')} />}
        </Form>
      )}
    </Modal>
  );
}
