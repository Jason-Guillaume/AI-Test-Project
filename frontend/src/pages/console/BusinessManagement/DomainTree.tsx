import { collectPages } from '@/shared/api/pagination';
// 左侧业务域 / 流程树。
// 两栏结构：域列表 → 选中域后展示其下流程。点击域切换流程列表，点击流程选中进入详情。
// 域与流程均支持删除（弹窗确认）；新建在 index.tsx 的主弹窗中完成。
import { useState } from 'react';
import { App, Button, Empty, Input, Popconfirm, Skeleton, Tag } from 'antd';
import { DeleteOutlined, FolderOutlined, PlayCircleOutlined, SearchOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { getErrorMessage } from '@/shared/api/client';
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
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState('');

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
            deletingFlow={removeFlowMutation.isPending}
            onDeleteFlow={(id) => removeFlowMutation.mutate(id)}
            flowsLoading={flowsQuery.isFetching}
          />
        ))}
      </div>
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
        <FolderOutlined />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {domain.name}
        </span>
        <Tag color={statusInfo.color} style={{ margin: 0, fontSize: 11 }}>
          {statusInfo.text}
        </Tag>
        <Popconfirm
          title="删除业务域会级联删除其下所有流程与动作，确认？"
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
                <PlayCircleOutlined />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>
                  {f.name}
                </span>
                <Tag color={fStatus.color} style={{ margin: 0, fontSize: 11 }}>
                  {fStatus.text}
                </Tag>
                <Popconfirm
                  title="删除流程会级联删除其下所有步骤与配置，确认？"
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
