// 安全测试 · 疑似问题（Finding）Tab。
//
// 只改状态（标为误报 / 已确认 / 已修复 / 已忽略），不提供「转 Bug」——bug_id 恒 null。
// 疑似问题文案统一「疑似问题」，不写「已发现漏洞」。
//
// 安全红线：Finding 的 evidence（脱敏证据）不在本 Tab 展示；如需查看变异轨迹，请到
// 「安全用例」Tab 打开对应执行的变异详情抽屉。本 Tab 只展示 description / recommendation
// 等策展文本，避免在管理面二次扩散敏感字段。
import { useState } from 'react';
import {
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import {
  FINDING_STATUS_OPTIONS,
  FINDING_STATUS_TRANSITIONS,
  findingStatusColor,
  findingStatusLabel,
  severityColor,
  severityLabel,
} from './constants';
import type { SecurityFinding, SecurityFindingStatus } from '@/types';

/** 疑似问题 Tab。projectId 由父页传入（已确保非空）。 */
export function FindingsTab({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [severity, setSeverity] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [drawer, setDrawer] = useState<SecurityFinding | null>(null);

  const listQuery = useQuery({
    queryKey: ['security-findings', projectId, { severity, status }],
    queryFn: () =>
      securityApi.listFindings(projectId, {
        page: 1,
        page_size: 100,
        severity,
        status,
      }),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['security-findings'] });
    queryClient.invalidateQueries({ queryKey: ['security-overview', projectId] });
  };

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, next }: { id: number; next: SecurityFindingStatus }) =>
      securityApi.updateFinding(id, { status: next }),
    onSuccess: () => {
      message.success('状态已更新');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '状态更新失败（可能是不允许的迁移）')),
  });

  const columns: TableColumnsType<SecurityFinding> = [
    {
      title: '疑似问题',
      dataIndex: 'title',
      render: (_, r) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => setDrawer(r)}>
          <Typography.Text strong>{r.title}</Typography.Text>
        </Button>
      ),
    },
    {
      title: '严重级别',
      dataIndex: 'severity',
      width: 90,
      render: (v: string) => <Tag color={severityColor(v)}>{severityLabel(v)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag color={findingStatusColor(v)}>{findingStatusLabel(v)}</Tag>,
    },
    { title: '变异类型', dataIndex: 'mutation_type', width: 160 },
    {
      title: '处置',
      width: 200,
      render: (_, r) => (
        <Select
          size="small"
          style={{ width: 160 }}
          placeholder="变更状态"
          value={undefined}
          onChange={(next: SecurityFindingStatus) =>
            updateStatusMutation.mutate({ id: r.id, next })
          }
          options={(FINDING_STATUS_TRANSITIONS[r.status] ?? []).map((v) => {
            const o = FINDING_STATUS_OPTIONS.find((x) => x.value === v);
            return o ? { value: v, label: o.label } : { value: v, label: v };
          })}
        />
      ),
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const items = listQuery.data?.items ?? [];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            allowClear
            placeholder="严重级别"
            style={{ width: 140 }}
            value={severity}
            onChange={setSeverity}
            options={['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((s) => ({
              value: s,
              label: severityLabel(s),
            }))}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 140 }}
            value={status}
            onChange={setStatus}
            options={FINDING_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
        </Space>
      </Card>

      <Table<SecurityFinding>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      <Drawer
        title={drawer ? `疑似问题 #${drawer.id}` : '疑似问题'}
        open={drawer != null}
        onClose={() => setDrawer(null)}
        width={480}
        destroyOnClose
      >
        {drawer && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {drawer.title}
            </Typography.Title>
            <Space>
              <Tag color={severityColor(drawer.severity)}>{severityLabel(drawer.severity)}</Tag>
              <Tag color={findingStatusColor(drawer.status)}>
                {findingStatusLabel(drawer.status)}
              </Tag>
              <Typography.Text type="secondary">{drawer.mutation_type}</Typography.Text>
            </Space>
            <Descriptions size="small" column={1} bordered>
              {drawer.description && (
                <Descriptions.Item label="描述">{drawer.description}</Descriptions.Item>
              )}
              {drawer.recommendation && (
                <Descriptions.Item label="建议">{drawer.recommendation}</Descriptions.Item>
              )}
              <Descriptions.Item label="接口 ID">{drawer.api_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="安全用例 ID">
                {drawer.security_case_id ?? '-'}
              </Descriptions.Item>
            </Descriptions>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              疑似问题需人工确认，不等于已发现漏洞。证据（evidence）不在本页展示，如需查看变异轨迹请到「安全用例」Tab 打开对应执行。
            </Typography.Text>
          </Space>
        )}
      </Drawer>
    </div>
  );
}
