// 缺陷详情里的分享历史。
// 平台不保存访问凭证明文，所以这里的复制会重新签发链接，旧链接立即失效。
import { App, Button, Space, Table, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { bugsApi } from '@/features/defects/api/defects';
import type { Bug, DefectShareSummary } from '@/features/defects/contracts';
import { getErrorMessage } from '@/shared/api/client';

/**
 * 展示一个缺陷的推送记录，并提供撤销、重推和查看外部处理。
 * 只有具备项目写权限时显示变更按钮。
 */
export function DefectShareHistory({ bug, canManage }: { bug: Bug; canManage: boolean }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const shares = useQuery({
    queryKey: ['bug-shares', bug.id],
    queryFn: () => bugsApi.listShares(bug.id),
  });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['bug-shares', bug.id] });
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    queryClient.invalidateQueries({ queryKey: ['bug-detail', bug.id] });
  };
  const retry = useMutation({
    mutationFn: (row: DefectShareSummary) => bugsApi.retryShare(bug.id, row.share_id),
    onSuccess: async (result) => {
      await navigator.clipboard.writeText(result.share_url);
      message.success(result.notification_status === 'SUCCESS' ? '已重新推送，新链接已复制' : `已重新签发链接，飞书推送失败：${result.error_message || '未知原因'}`);
      refresh();
    },
    onError: (error) => message.error(getErrorMessage(error, '重新推送失败')),
  });
  const revoke = useMutation({
    mutationFn: (row: DefectShareSummary) => bugsApi.revokeShare(bug.id, row.share_id),
    onSuccess: () => {
      message.success('分享链接已撤销');
      refresh();
    },
    onError: (error) => message.error(getErrorMessage(error, '撤销失败')),
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
              {canManage && <Button size="small" onClick={() => modal.confirm({
                title: '重新签发并推送？',
                content: '平台不保存访问凭证。继续会签发新链接，旧链接立即失效。',
                okText: '重新推送', cancelText: '取消', onOk: () => retry.mutateAsync(row),
              })}>重新推送</Button>}
              {canManage && row.share_status === '有效' && <Button size="small" danger onClick={() => modal.confirm({
                title: '撤销这条分享链接？',
                content: '只撤销当前渠道的链接，不影响同一缺陷推送到其他群的链接。',
                okText: '撤销', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => revoke.mutateAsync(row),
              })}>撤销链接</Button>}
            </Space>,
          },
        ]}
      />
    </Space>
  );
}
