import { collectPages } from '@/shared/api/pagination';
// 左侧业务域 / 流程树。
// 两栏结构：域列表 → 选中域后展示其下流程。点击域切换流程列表，点击流程选中进入详情。
// 域与流程均支持删除（弹窗确认）；新建在 index.tsx 的主弹窗中完成。
import { useEffect, useState } from 'react';
import { Alert, App, Button, Checkbox, Empty, Input, Popconfirm, Skeleton, Space, Tag } from 'antd';
import { DeleteOutlined, FolderOutlined, PlayCircleOutlined, SearchOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { getErrorMessage } from '@/shared/api/client';
import type { BatchLifecycleReceipt } from '@/features/data-lifecycle/api';
import type { BusinessDomain } from '@/features/business/contracts';


interface DomainTreeProps {
  projectId: number;
  selectedDomainId: number | null;
  onSelectDomain: (id: number | null) => void;
  selectedFlowId: number | null;
  onSelectFlow: (id: number | null) => void;
}

const DOMAIN_STATUS_LABELS: Record<string, { color: string; text: string }> = {
  ACTIVE: { color: 'green', text: '启用' },
  INACTIVE: { color: 'default', text: '停用' },
};
const FLOW_STATUS_LABELS: Record<string, { color: string; text: string }> = {
  DRAFT: { color: 'blue', text: '草稿' },
  ACTIVE: { color: 'green', text: '已上线' },
  DEPRECATED: { color: 'default', text: '已废弃' },
};

export function DomainTree(props: DomainTreeProps) {
  const { projectId, selectedDomainId, onSelectDomain, selectedFlowId, onSelectFlow } = props;
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState('');
  const [selectedDomainIds, setSelectedDomainIds] = useState<number[]>([]);
  const [selectedFlowIds, setSelectedFlowIds] = useState<number[]>([]);

  useEffect(() => setSelectedFlowIds([]), [selectedDomainId]);

  const domainsQuery = useQuery({
    queryKey: ['business', projectId, 'domains', keyword],
    queryFn: () =>
      collectPages((page) => businessApi.listDomains(projectId, { page, page_size: 100, keyword: keyword || undefined })),
    enabled: projectId != null,
  });
  const domains: BusinessDomain[] = domainsQuery.data?.items ?? [];

  const flowsQuery = useQuery({
    queryKey: ['business', projectId, 'flows', selectedDomainId],
    queryFn: () =>
      collectPages((page) => businessApi.listFlows(projectId, {
        page,
        page_size: 100,
        domain_id: selectedDomainId ?? undefined,
      })),
    enabled: selectedDomainId != null,
  });
  const flows = flowsQuery.data?.items ?? [];

  const removeDomainMutation = useMutation({
    mutationFn: (domainId: number) => businessApi.removeDomain(domainId),
    onSuccess: () => {
      message.success('业务域已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      onSelectDomain(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const removeFlowMutation = useMutation({
    mutationFn: (flowId: number) => businessApi.removeFlow(flowId),
    onSuccess: () => {
      message.success('业务流程已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      onSelectFlow(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const batchDeleteMutation = useMutation({
    mutationFn: ({ type, ids }: { type: 'business_domain' | 'business_flow'; ids: number[] }) =>
      type === 'business_domain'
        ? businessApi.removeDomains(projectId, ids)
        : businessApi.removeFlows(projectId, ids),
    onSuccess: (receipt: BatchLifecycleReceipt, variables) => {
      queryClient.invalidateQueries({ queryKey: ['business'] });
      if (variables.type === 'business_domain') {
        setSelectedDomainIds([]);
        onSelectDomain(null);
      } else {
        setSelectedFlowIds([]);
        onSelectFlow(null);
      }
      if (receipt.failed === 0) {
        message.success(`已删除 ${receipt.succeeded} 条，记录已移入回收站`);
      } else {
        message.warning(`已删除 ${receipt.succeeded} 条，${receipt.failed} 条未删除`);
        modal.info({
          title: '批量删除结果',
          width: 620,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              {receipt.items.filter((item) => !item.succeeded).map((item) => (
                <Alert key={item.id} type="error" showIcon message={`资源 #${item.id}`} description={item.error ?? '删除失败'} />
              ))}
            </Space>
          ),
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
  });

  function confirmBatchDelete(type: 'business_domain' | 'business_flow', ids: number[]) {
    const label = type === 'business_domain' ? '业务域' : '业务流程';
    modal.confirm({
      title: `删除选中的 ${ids.length} 个${label}？`,
      content: '每条资源会独立检查依赖并返回结果；成功删除的记录可在回收站恢复。',
      okText: '删除并移入回收站',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => batchDeleteMutation.mutateAsync({ type, ids }),
    });
  }

  if (domainsQuery.isPending) {
    return <Skeleton active paragraph={{ rows: 4 }} />;
  }

  if (domainsQuery.isError) return <div role="alert">业务域加载失败 <Button onClick={() => void domainsQuery.refetch()}>重试</Button></div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {flowsQuery.isError && <div role="alert">流程加载失败 <Button onClick={() => void flowsQuery.refetch()}>重试</Button></div>}
      <Input
        size="small"
        allowClear
        prefix={<SearchOutlined />}
        placeholder="搜索业务域"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <Space wrap>
        <Checkbox
          checked={domains.length > 0 && domains.every((domain) => selectedDomainIds.includes(domain.id))}
          indeterminate={selectedDomainIds.some((id) => domains.some((domain) => domain.id === id)) && !domains.every((domain) => selectedDomainIds.includes(domain.id))}
          onChange={(event) => setSelectedDomainIds(event.target.checked ? domains.map((domain) => domain.id) : [])}
        >
          全选当前搜索结果（{domains.length}）
        </Checkbox>
        <Button
          size="small"
          danger
          disabled={selectedDomainIds.length === 0 || batchDeleteMutation.isPending}
          loading={batchDeleteMutation.isPending && selectedDomainIds.length > 0}
          onClick={() => confirmBatchDelete('business_domain', selectedDomainIds)}
        >
          批量删除域（{selectedDomainIds.length}）
        </Button>
      </Space>
      {domains.length === 0 && !keyword && (
        <Empty description="暂无业务域，点击「新建域」开始" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {domains.map((d) => (
          <DomainNode
            key={d.id}
            domain={d}
            selected={selectedDomainId === d.id}
            flows={selectedDomainId === d.id ? flows : []}
            selectedFlowId={selectedFlowId}
            onSelect={onSelectDomain}
            onSelectFlow={onSelectFlow}
            onDelete={(id) => removeDomainMutation.mutate(id)}
            domainChecked={selectedDomainIds.includes(d.id)}
            onToggleDomain={(checked) => setSelectedDomainIds((current) => checked ? [...new Set([...current, d.id])] : current.filter((id) => id !== d.id))}
            selectedFlowIds={selectedFlowIds}
            onToggleFlow={(id, checked) => setSelectedFlowIds((current) => checked ? [...new Set([...current, id])] : current.filter((value) => value !== id))}
            deletingFlow={removeFlowMutation.isPending}
            onDeleteFlow={(id) => removeFlowMutation.mutate(id)}
            flowsLoading={flowsQuery.isFetching}
          />
        ))}
      </div>
      {selectedDomainId != null && (
        <Space wrap>
          <Checkbox
            checked={flows.length > 0 && flows.every((flow) => selectedFlowIds.includes(flow.id))}
            indeterminate={selectedFlowIds.some((id) => flows.some((flow) => flow.id === id)) && !flows.every((flow) => selectedFlowIds.includes(flow.id))}
            onChange={(event) => setSelectedFlowIds(event.target.checked ? flows.map((flow) => flow.id) : [])}
          >
            全选当前流程列表（{flows.length}）
          </Checkbox>
          <Button
            size="small"
            danger
            disabled={selectedFlowIds.length === 0 || batchDeleteMutation.isPending}
            loading={batchDeleteMutation.isPending && selectedFlowIds.length > 0}
            onClick={() => confirmBatchDelete('business_flow', selectedFlowIds)}
          >
            批量删除流程（{selectedFlowIds.length}）
          </Button>
        </Space>
      )}
    </div>
  );
}

function DomainNode({
  domain,
  selected,
  flows,
  selectedFlowId,
  onSelect,
  onSelectFlow,
  onDelete,
  domainChecked,
  onToggleDomain,
  selectedFlowIds,
  onToggleFlow,
  onDeleteFlow,
  deletingFlow,
  flowsLoading,
}: {
  domain: BusinessDomain;
  selected: boolean;
  flows: { id: number; name: string; status: string }[];
  selectedFlowId: number | null;
  onSelect: (id: number) => void;
  onSelectFlow: (id: number | null) => void;
  onDelete: (id: number) => void;
  domainChecked: boolean;
  onToggleDomain: (checked: boolean) => void;
  selectedFlowIds: number[];
  onToggleFlow: (id: number, checked: boolean) => void;
  onDeleteFlow: (id: number) => void;
  deletingFlow: boolean;
  flowsLoading: boolean;
}) {
  const statusInfo = DOMAIN_STATUS_LABELS[domain.status] ?? { color: 'default', text: domain.status };
  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 6px',
          borderRadius: 4,
          cursor: 'pointer',
          background: selected ? '#e6f4ff' : 'transparent',
        }}
        onClick={() => onSelect(domain.id)}
      >
        <Checkbox
          checked={domainChecked}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onToggleDomain(event.target.checked)}
        />
        <FolderOutlined />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {domain.name}
        </span>
        <Tag color={statusInfo.color} style={{ margin: 0, fontSize: 11 }}>
          {statusInfo.text}
        </Tag>
        <Popconfirm
          title="删除此业务域？仍有流程时服务端会拒绝删除。"
          onConfirm={() => onDelete(domain.id)}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>
      </div>
      {selected && (
        <div style={{ marginLeft: 20, marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {flowsLoading && <Skeleton active paragraph={false} title={false} />}
          {!flowsLoading && flows.length === 0 && (
            <div style={{ padding: '4px 8px', color: '#999', fontSize: 12 }}>该域下暂无流程</div>
          )}
          {flows.map((f) => {
            const fStatus = FLOW_STATUS_LABELS[f.status] ?? { color: 'default', text: f.status };
            return (
              <div
                key={f.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '3px 6px',
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: selectedFlowId === f.id ? '#bae0ff' : 'transparent',
                }}
                onClick={() => onSelectFlow(f.id)}
              >
                <Checkbox
                  checked={selectedFlowIds.includes(f.id)}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => onToggleFlow(f.id, event.target.checked)}
                />
                <PlayCircleOutlined />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>
                  {f.name}
                </span>
                <Tag color={fStatus.color} style={{ margin: 0, fontSize: 11 }}>
                  {fStatus.text}
                </Tag>
                <Popconfirm
                  title="删除此流程？仍有动作、引用或执行任务时服务端会拒绝删除。"
                  onConfirm={() => onDeleteFlow(f.id)}
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true, loading: deletingFlow }}
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    disabled={deletingFlow}
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
