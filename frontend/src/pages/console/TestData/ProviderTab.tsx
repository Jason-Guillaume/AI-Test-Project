import { collectPages } from '@/shared/api/pagination';
// 数据工厂 Tab：Data Provider 列表 + 新增/编辑/试跑/启用停用。
//
// §7.4：表列 名称、类型、状态、风险等级、使用次数、最近执行状态。
// 操作：新增、编辑、试跑、启用/停用。试跑打开确认 Modal 展示当前环境名，
// 成功后直接把返回的执行记录详情开进 ExecutionDetailDrawer（每步 input/output/error）。
// 单 Provider 试跑没有 Fixture 归属，步骤列在抽屉的「无归属步骤」区块。
import { useState } from 'react';
import { App, Button, Popconfirm, Space, Switch, Table, Tag } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/features/test-data/api/testData';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, EmptyState, LoadingState } from '@/shared/ui/PageState';
import {
  PROVIDER_EXECUTION_STATUS_COLOR,
  PROVIDER_TYPE_OPTIONS,
  RISK_LEVEL_COLOR,
  RISK_LEVEL_OPTIONS,
  labelOf,
} from './constants';
import { ProviderModal } from './ProviderModal';
import { ExecutionDetailDrawer } from './ExecutionDetailDrawer';
import type { DataProvider, ProviderExecutionStatus, ProviderType, RiskLevel } from '@/features/test-data/contracts';
import type { DataExecutionDetail } from '@/features/test-data/executionContracts';


/**
 * Data Provider 列表。
 */
export function ProviderTab({
  projectId,
  environmentId,
  environmentName,
}: {
  projectId: number;
  environmentId: number | null;
  environmentName: string | null;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DataProvider | null>(null);
  // 试跑结果：直接作为抽屉的 seed，省一次回读请求。
  const [detail, setDetail] = useState<DataExecutionDetail | null>(null);

  const query = useQuery({
    queryKey: ['test-data', 'providers', projectId],
    queryFn: () => collectPages((page) => testDataApi.listProviders(projectId, { page, page_size: 200 })),
    enabled: projectId != null,
  });

  const setEnabledMutation = useMutation({
    mutationFn: (p: { id: number; enabled: boolean }) =>
      p.enabled
        ? testDataApi.enableProvider(p.id)
        : testDataApi.disableProvider(p.id),
    onSuccess: () => {
      message.success('已更新');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'providers'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '操作失败')),
  });

  const testMutation = useMutation({
    mutationFn: (p: { id: number; environment_id: number }) =>
      testDataApi.testProvider(p.id, { environment_id: p.environment_id }),
    onSuccess: (data) => {
      setDetail(data);
      message.success(
        data.status === 'FAILED' ? `试跑完成，但执行失败（${data.error_code ?? 'UNKNOWN'}）` : '试跑完成',
      );
      queryClient.invalidateQueries({ queryKey: ['test-data', 'providers'] });
      queryClient.invalidateQueries({ queryKey: ['test-data', 'executions'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '试跑失败')),
  });

  const handleTest = (provider: DataProvider) => {
    if (environmentId == null) {
      message.warning('请先在顶部选择试跑环境');
      return;
    }
    modal.confirm({
      title: '试跑确认',
      content: `将在环境「${environmentName ?? environmentId}」下试跑「${provider.name}」，确认继续？`,
      okText: '试跑',
      cancelText: '取消',
      onOk: () => testMutation.mutateAsync({ id: provider.id, environment_id: environmentId }),
    });
  };

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const rows = query.data.items ?? [];

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          新增 Provider
        </Button>
      </Space>
      {rows.length === 0 ? (
        <EmptyState description="暂无 Data Provider，点「新增」创建第一个" />
      ) : (
        <Table<DataProvider>
          rowKey={(r) => r.id}
          dataSource={rows}
          loading={query.isFetching}
          pagination={false}
          size="middle"
          columns={[
            { title: '名称', dataIndex: 'name' },
            {
              title: '类型',
              dataIndex: 'provider_type',
              width: 150,
              render: (v: ProviderType) => <Tag>{labelOf(PROVIDER_TYPE_OPTIONS, v)}</Tag>,
            },
            {
              title: '状态',
              dataIndex: 'enabled',
              width: 90,
              render: (v: boolean, r: DataProvider) => (
                <Switch
                  checked={v}
                  loading={setEnabledMutation.isPending}
                  onChange={(checked) =>
                    setEnabledMutation.mutate({ id: r.id, enabled: checked })
                  }
                />
              ),
            },
            {
              title: '风险',
              dataIndex: 'risk_level',
              width: 90,
              render: (v: RiskLevel) => (
                <Tag color={RISK_LEVEL_COLOR[v]}>{labelOf(RISK_LEVEL_OPTIONS, v)}</Tag>
              ),
            },
            { title: '使用次数', dataIndex: 'usage_count', width: 90 },
            {
              title: '最近状态',
              dataIndex: 'last_status',
              width: 100,
              render: (v: ProviderExecutionStatus | null) =>
                v ? (
                  <Tag color={PROVIDER_EXECUTION_STATUS_COLOR[v]}>{v}</Tag>
                ) : (
                  '-'
                ),
            },
            {
              title: '操作',
              key: 'actions',
              width: 200,
              render: (_: unknown, r: DataProvider) => (
                <Space size={4}>
                  <a
                    onClick={() => {
                      setEditing(r);
                      setModalOpen(true);
                    }}
                  >
                    编辑
                  </a>
                  <a onClick={() => handleTest(r)}>试跑</a>
                  <Popconfirm
                    title={`删除 Provider「${r.name}」？`}
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={async () => {
                      try {
                        await testDataApi.removeProvider(r.id);
                        message.success('已删除');
                        queryClient.invalidateQueries({ queryKey: ['test-data', 'providers'] });
                      } catch (e) {
                        message.error(getErrorMessage(e, '删除失败'));
                      }
                    }}
                  >
                    <a style={{ color: '#ff4d4f' }}>删除</a>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      )}

      <ProviderModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={projectId}
        editing={editing}
      />

      <ExecutionDetailDrawer
        open={detail != null}
        executionId={detail?.id ?? null}
        seed={detail}
        onClose={() => setDetail(null)}
      />
    </>
  );
}
