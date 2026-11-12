// 步骤编排：有序展示流程下的业务动作，支持上移/下移重排（无 DnD 库，用按钮）。
// 点击步骤名称进入 ActionDrawer 配置该步骤的前置条件/变量/状态/绑定。
// 删除步骤会级联删除其子配置与绑定。
import { useState } from 'react';
import { Alert, App, Button, Card, Checkbox, Empty, Popconfirm, Space, Tag } from 'antd';
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, RightOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { getErrorMessage } from '@/shared/api/client';
import type { BatchLifecycleReceipt } from '@/features/data-lifecycle/api';
import type { BusinessAction } from '@/features/business/contracts';


interface FlowStepsProps {
  projectId: number;
  actions: BusinessAction[];
  onReorder: () => void;
  onDelete: (actionId: number) => void;
  deleting: boolean;
  onAdd: () => void;
  onSelectAction: (id: number) => void;
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  NORMAL: '普通动作',
  SYSTEM: '系统动作（历史类型）',
  MANUAL: '人工动作（历史类型）',
  WAIT: '等待动作（历史类型）',
  DECISION: '决策动作（历史类型）',
};

export function FlowSteps({ projectId, actions, onReorder, onDelete, deleting, onAdd, onSelectAction }: FlowStepsProps) {
  const { message, modal } = App.useApp();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const sorted = [...actions].sort((a, b) => a.sort - b.sort);
  // 所有动作同属一个流程，从第一个动作取 flow_id 即可。
  const flowId = actions[0]?.flow_id ?? 0;

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: number[]) => businessApi.removeActions(projectId, ids),
    onSuccess: (receipt: BatchLifecycleReceipt) => {
      setSelectedIds([]);
      onReorder();
      if (receipt.failed === 0) {
        message.success(`已删除 ${receipt.succeeded} 个动作，记录已移入回收站`);
      } else {
        message.warning(`已删除 ${receipt.succeeded} 个动作，${receipt.failed} 个未删除`);
        modal.info({
          title: '批量删除结果',
          width: 620,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              {receipt.items.filter((item) => !item.succeeded).map((item) => (
                <Alert key={item.id} type="error" showIcon message={`动作 #${item.id}`} description={item.error ?? '删除失败'} />
              ))}
            </Space>
          ),
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
  });

  const reorderMutation = useMutation({
    mutationFn: (items: { action_id: number; sort: number }[]) =>
      businessApi.reorderActions(flowId, { items }),
    onSuccess: () => {
      message.success('步骤顺序已更新');
      onReorder();
    },
    onError: (e) => message.error(getErrorMessage(e, '重排失败')),
  });

  function move(actionId: number, delta: number) {
    const index = sorted.findIndex((a) => a.id === actionId);
    const target = index + delta;
    if (target < 0 || target >= sorted.length) return;
    // 先构建目标顺序，再连续编号，避免只交换两行导致其余行排序值不变。
    const nextOrder = [...sorted];
    [nextOrder[index], nextOrder[target]] = [nextOrder[target], nextOrder[index]];
    const items = nextOrder.map((a, i) => ({ action_id: a.id, sort: (i + 1) * 10 }));
    reorderMutation.mutate(items);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Space style={{ marginBottom: 4 }}>
        <Button size="small" type="primary" icon={<RightOutlined />} onClick={onAdd}>
          新增步骤
        </Button>
        <span style={{ color: '#999', fontSize: 12 }}>
          提示：用 ↑↓ 调整顺序；点击步骤名称配置该步骤的前置条件、变量、状态与 API 绑定
        </span>
      </Space>
      {sorted.length > 0 && (
        <Space wrap>
          <Checkbox
            checked={selectedIds.length === sorted.length}
            indeterminate={selectedIds.length > 0 && selectedIds.length < sorted.length}
            onChange={(event) => setSelectedIds(event.target.checked ? sorted.map((action) => action.id) : [])}
          >
            全选当前流程动作（{sorted.length}）
          </Checkbox>
          <Button
            size="small"
            danger
            disabled={selectedIds.length === 0 || batchDeleteMutation.isPending}
            loading={batchDeleteMutation.isPending}
            onClick={() => modal.confirm({
              title: `删除选中的 ${selectedIds.length} 个动作？`,
              content: '动作仍有配置、变量引用、测试资产或正在运行任务时会逐条拒绝；成功删除的动作可在回收站恢复。',
              okText: '删除并移入回收站',
              cancelText: '取消',
              okButtonProps: { danger: true },
              onOk: () => batchDeleteMutation.mutateAsync(selectedIds),
            })}
          >
            批量删除动作（{selectedIds.length}）
          </Button>
        </Space>
      )}
      {sorted.length === 0 ? (
        <Empty description="暂无步骤，点击「新增步骤」开始编排" />
      ) : (
        sorted.map((a, idx) => (
          <Card
            key={a.id}
            size="small"
            style={{ marginBottom: 4 }}
            bodyStyle={{ padding: '8px 12px' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Space size={2}>
                <Checkbox
                  checked={selectedIds.includes(a.id)}
                  onChange={(event) => setSelectedIds((current) => event.target.checked ? [...new Set([...current, a.id])] : current.filter((id) => id !== a.id))}
                />
                <Button
                  size="small"
                  type="text"
                  icon={<ArrowUpOutlined />}
                  disabled={idx === 0}
                  onClick={() => move(a.id, -1)}
                />
                <Button
                  size="small"
                  type="text"
                  icon={<ArrowDownOutlined />}
                  disabled={idx === sorted.length - 1}
                  onClick={() => move(a.id, 1)}
                />
              </Space>
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                {idx + 1}. {a.name}
              </span>
              <Tag style={{ fontSize: 11 }}>{a.action_key}</Tag>
              <Tag color="blue" style={{ fontSize: 11 }}>
                {ACTION_TYPE_LABELS[a.action_type] ?? a.action_type}
              </Tag>
              <span style={{ flex: 1 }} />
              <Button
                size="small"
                type="link"
                onClick={() => onSelectAction(a.id)}
              >
                配置
              </Button>
              <Popconfirm
                title="删除此动作？仍有配置、关联引用或执行任务时服务端会拒绝删除。"
                onConfirm={() => onDelete(a.id)}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={deleting}
                />
              </Popconfirm>
            </div>
            {a.description && (
              <div style={{ color: '#666', fontSize: 12, marginTop: 4 }}>{a.description}</div>
            )}
          </Card>
        ))
      )}
    </div>
  );
}
