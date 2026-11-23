// 缺陷详情里的分享历史。
// 平台不保存访问凭证明文，所以这里的重推会重新签发链接，旧链接立即失效。
import { Alert, App, Button, Input, Modal, Space, Table, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { bugsApi } from '@/features/defects/api/defects';
import type { Bug, DefectSharePushResult, DefectShareSummary, DefectShareBatchResult } from '@/features/defects/contracts';
import { getErrorMessage } from '@/shared/api/client';

async function tryWriteClipboard(text: string): Promise<boolean> {
  if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
    return false;
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/**
 * 展示一个缺陷的推送记录，并提供撤销、重推和查看外部处理。
 * 只有具备项目写权限时显示变更按钮。
 */
export function DefectShareHistory({ bug, canManage }: { bug: Bug; canManage: boolean }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [retryingShareId, setRetryingShareId] = useState<string | null>(null);
  const [reissuedResult, setReissuedResult] = useState<DefectSharePushResult | null>(null);
  const [reissuedBatch, setReissuedBatch] = useState<DefectShareBatchResult | null>(null);
  const [copiedReissued, setCopiedReissued] = useState(false);

  const shares = useQuery({
    queryKey: ['bug-shares', bug.id],
    queryFn: () => bugsApi.listShares(bug.id),
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['bug-shares', bug.id] });
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    queryClient.invalidateQueries({ queryKey: ['bug-detail', bug.id] });
  };
  const retry = useMutation<DefectSharePushResult | DefectShareBatchResult, Error, { row: DefectShareSummary; confirmUncertain: boolean }>({
    mutationFn: ({ row, confirmUncertain }: { row: DefectShareSummary; confirmUncertain: boolean }) => {
      setRetryingShareId(row.share_id);
      return row.batch_share_id
        ? bugsApi.retryShareBatch(row.batch_share_id, confirmUncertain)
        : bugsApi.retryShare(bug.id, row.share_id, undefined, confirmUncertain);
    },
    onSuccess: async (result) => {
      if ('batch_share_url' in result) {
        setReissuedBatch(result);
        const copied = result.batch_share_url ? await tryWriteClipboard(result.batch_share_url) : false;
        setCopiedReissued(copied);
        message.success(copied ? '批次卡片已重发，新链接已复制' : '批次已重发，请在弹窗中复制新链接');
        refresh();
        return;
      }
      setReissuedResult(result);
      const copied = result.share_url ? await tryWriteClipboard(result.share_url) : false;
      setCopiedReissued(copied);
      if (result.notification_status === 'SUCCESS') {
        message.success(copied ? '已重新推送飞书，新链接已复制到剪贴板' : '已重新推送飞书，请在弹窗中复制新链接');
      } else if (result.notification_status === 'UNCERTAIN') {
        message.warning('投递结果待确认，请先查看群消息');
      } else {
        message.warning(`已生成新链接（旧链接已失效），飞书推送失败：${result.error_message || '未知原因'}`);
      }
      refresh();
    },
    onError: (error) => message.error(getErrorMessage(error, '重新推送失败')),
    onSettled: () => setRetryingShareId(null),
  });
  const revoke = useMutation({
    mutationFn: (row: DefectShareSummary) => bugsApi.revokeShare(bug.id, row.share_id),
    onSuccess: () => {
      message.success('分享链接已撤销');
      refresh();
    },
    onError: (error) => message.error(getErrorMessage(error, '撤销失败')),
  });
  const revokeBatch = useMutation({
    mutationFn: (row: DefectShareSummary) => bugsApi.revokeShareBatch(row.batch_share_id!),
    onSuccess: () => { message.success('批次入口已撤销'); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '撤销批次失败')),
  });
  const detail = useMutation({
    mutationFn: (row: DefectShareSummary) => bugsApi.getShare(bug.id, row.share_id),
    onSuccess: (data) => {
      modal.info({
        title: '推送与外部处理',
        width: 680,
        content: <Space direction="vertical">
          <Typography.Text>推送状态：{data.notification_status || '无'} {data.error_message || ''}</Typography.Text>
          {data.external_actions.length === 0 && <Typography.Text type="secondary">还没有外部修复记录。</Typography.Text>}
          {data.external_actions.map((action) => (
            <Typography.Paragraph key={action.created_at}>
              {action.actor_display_name || '未留姓名'} 于 {new Date(action.created_at).toLocaleString()} 提交：{action.repair_description}
              <br />{action.identity_note}
            </Typography.Paragraph>
          ))}
        </Space>,
      });
    },
    onError: (error) => message.error(getErrorMessage(error, '读取分享详情失败')),
  });

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      {shares.data?.items.flatMap((share) => share.latest_resolution ? [
        <div key={share.share_id}>
          <Typography.Text strong>外部修复结果（{share.channel_name}）</Typography.Text>
          <Typography.Paragraph>
            {share.latest_resolution.repair_description}
            <br />{new Date(share.latest_resolution.created_at).toLocaleString()} · {share.latest_resolution.actor_display_name || '未留姓名'}（自报）
            {share.latest_resolution.fix_version && <> · 版本：{share.latest_resolution.fix_version}</>}
            {share.latest_resolution.commit_sha && <> · Commit：{share.latest_resolution.commit_sha}</>}
            <br />{share.latest_resolution.identity_note}
          </Typography.Paragraph>
        </div>,
      ] : [])}
      <Typography.Text strong>分享记录</Typography.Text>
      <Table<DefectShareSummary>
        size="small"
        rowKey="share_id"
        loading={shares.isFetching}
        dataSource={shares.data?.items ?? []}
        pagination={false}
        locale={{ emptyText: '还没有推送记录' }}
        columns={[
          { title: '推送渠道', dataIndex: 'channel_name' },
          { title: '推送人', dataIndex: 'pushed_by_username', render: (value) => value || '-' },
          { title: '推送时间', dataIndex: 'pushed_at', render: (value: string) => new Date(value).toLocaleString() },
          { title: '有效期', dataIndex: 'expires_label' },
          { title: '分享状态', dataIndex: 'share_status', render: (value: string) => <Tag>{value}</Tag> },
          { title: '查看次数', dataIndex: 'view_count' },
          { title: '开发处理', dataIndex: 'resolution_status' },
          { title: '飞书结果', dataIndex: 'notification_status', render: (value) => value || '-' },
          {
            title: '操作',
            render: (_value, row) => <Space wrap>
              <Button size="small" onClick={() => detail.mutate(row)}>查看详情</Button>
              {/* 上次推送已成功的分享不再提供重推：后端会拒绝，且重推会让群里第一张卡片的链接失效。 */}
              {canManage && row.share_status === '有效' && row.notification_status !== 'SUCCESS' && (
                <Button
                  size="small"
                  loading={retry.isPending && retryingShareId === row.share_id}
                  disabled={retry.isPending}
                  onClick={() => modal.confirm({
                    title: row.batch_share_id ? '重新推送整批缺陷？' : '重新签发并推送？',
                    content: row.notification_status === 'UNCERTAIN'
                      ? '上次请求超时，可能已送达。请先查看群消息；确认未收到后再继续，避免重复。'
                      : row.batch_share_id ? '为原批次签发新入口并只发送一张卡片，旧入口立即失效。' : '平台不保存访问凭证。继续会签发新链接，旧链接立即失效。',
                    okText: '重新推送',
                    cancelText: '取消',
                    onOk: () => retry.mutateAsync({ row, confirmUncertain: row.notification_status === 'UNCERTAIN' }),
                  })}
                >
                  {row.batch_share_id ? '重推整批' : '重新推送'}
                </Button>
              )}
              {canManage && row.share_status === '有效' && <Button size="small" danger onClick={() => modal.confirm({
                title: '撤销这条分享链接？',
                content: '只撤销当前渠道的链接，不影响同一缺陷推送到其他群的链接。',
                okText: '撤销', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => revoke.mutateAsync(row),
              })}>撤销链接</Button>}
              {canManage && row.batch_share_id && row.share_status === '有效' && <Button size="small" danger onClick={() => modal.confirm({
                title: '撤销整个批次入口？',
                content: '批次中的所有缺陷都将无法再通过这个入口访问。',
                okText: '撤销整批', cancelText: '取消', okButtonProps: { danger: true },
                onOk: () => revokeBatch.mutateAsync(row),
              })}>撤销整批</Button>}
            </Space>,
          },
        ]}
      />
      <Modal
        open={reissuedResult !== null}
        title="已重新签发分享链接"
        onCancel={() => { setReissuedResult(null); setCopiedReissued(false); }}
        footer={[
          <Button
            key="copy"
            type="primary"
            onClick={async () => {
              if (!reissuedResult?.share_url) return;
              const ok = await tryWriteClipboard(reissuedResult.share_url);
              setCopiedReissued(ok);
              if (ok) {
                message.success('新链接已复制到剪贴板');
              } else {
                message.warning('自动复制失败，请在下方输入框手动全选复制');
              }
            }}
          >
            {copiedReissued ? '已复制新链接' : '复制新链接'}
          </Button>,
          <Button
            key="close"
            onClick={() => { setReissuedResult(null); setCopiedReissued(false); }}
          >
            关闭
          </Button>,
        ]}
      >
        {reissuedResult && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Alert
              type={reissuedResult.notification_status === 'SUCCESS' ? 'success' : reissuedResult.notification_status === 'UNCERTAIN' ? 'warning' : 'error'}
              showIcon
              message={
                reissuedResult.notification_status === 'SUCCESS'
                  ? `飞书推送成功（${reissuedResult.channel_name}）`
                  : reissuedResult.notification_status === 'UNCERTAIN'
                    ? `投递结果待确认（${reissuedResult.channel_name}）`
                    : `飞书推送失败（${reissuedResult.channel_name}）`
              }
              description={
                reissuedResult.notification_status === 'SUCCESS'
                  ? '旧分享链接已立即失效；平台不保存访问凭证明文，请妥善保存本次生成的新链接。'
                  : reissuedResult.notification_status === 'UNCERTAIN'
                    ? '请求已超时，群里可能已经收到。请先查看群消息，再决定是否显式重发。旧分享链接已失效。'
                    : `旧分享链接已立即失效。失败原因：${reissuedResult.error_message || '飞书服务响应异常'}。本次重试已记录，可复制新链接或稍后重试。`
              }
            />
            {!reissuedResult.url_is_absolute && (
              <Typography.Text type="danger">
                PUBLIC_APP_BASE_URL 配置异常，当前生成的不是完整绝对 URL。
              </Typography.Text>
            )}
            <Typography.Text type="secondary">新分享链接（点击输入框可全选手动复制）：</Typography.Text>
            <Input
              readOnly
              value={reissuedResult.share_url ?? ''}
              onFocus={(event) => event.target.select()}
              aria-label="新分享链接"
            />
          </Space>
        )}
      </Modal>
      <Modal
        open={reissuedBatch !== null}
        title="已重新签发批次分享链接"
        onCancel={() => { setReissuedBatch(null); setCopiedReissued(false); }}
        footer={[
          <Button key="copy" type="primary" disabled={!reissuedBatch?.batch_share_url} onClick={async () => {
            const url = reissuedBatch?.batch_share_url;
            if (!url) return;
            const ok = await tryWriteClipboard(url);
            setCopiedReissued(ok);
            if (ok) message.success('批次链接已复制');
            else message.warning('自动复制失败，请在下方输入框手动复制');
          }}>{copiedReissued ? '已复制新链接' : '复制批次链接'}</Button>,
          <Button key="close" onClick={() => { setReissuedBatch(null); setCopiedReissued(false); }}>关闭</Button>,
        ]}
      >
        {reissuedBatch && <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            type={reissuedBatch.notification_status === 'SUCCESS' ? 'success' : reissuedBatch.notification_status === 'UNCERTAIN' ? 'warning' : 'error'}
            showIcon
            message={`批次包含 ${reissuedBatch.items.length} 条缺陷 · ${reissuedBatch.notification_status}`}
            description={reissuedBatch.error_message || '本次飞书重试只发送一张卡片。'}
          />
          <Input readOnly value={reissuedBatch.batch_share_url ?? ''} onFocus={(event) => event.target.select()} />
        </Space>}
      </Modal>
    </Space>
  );
}
