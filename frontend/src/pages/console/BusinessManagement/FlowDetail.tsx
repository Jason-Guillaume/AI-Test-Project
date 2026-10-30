// 流程详情：一次拉取聚合详情（动作+前置条件+变量+状态+绑定+映射+引用+规则），
// 三个 Tab 共享同一份数据，避免切 Tab 时重复请求。
// 点击步骤打开 ActionDrawer 配置单步子配置。
// 提供执行按钮，支持选择环境并查看执行结果。
import { useState } from 'react';
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Skeleton,
  Space,
  Steps,
  Tabs,
  Tag,
} from 'antd';
import { EditOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { projectsApi } from '@/features/projects/api/projects';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState } from '@/shared/ui/PageState';
import { FLOW_STATUS_OPTIONS } from './constants';
import { FlowSteps } from './FlowSteps';
import { VariableRefPanel } from './VariableRefPanel';
import { RulePanel } from './RulePanel';
import { ActionDrawer } from './ActionDrawer';
import type { BusinessActionCreate, BusinessFlowUpdate, BusinessFlowStatus, FlowExecution, FlowExecutionRequest, ActionExecution } from '@/features/business/contracts';


const FLOW_STATUS_LABELS: Record<string, { color: string; text: string }> = {
  DRAFT: { color: 'blue', text: '草稿' },
  ACTIVE: { color: 'green', text: '已上线' },
  DEPRECATED: { color: 'default', text: '已废弃' },
};

export function FlowDetail({ flowId, projectId }: { flowId: number; projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [editForm] = Form.useForm<BusinessFlowUpdate>();
  const [actionCreateOpen, setActionCreateOpen] = useState(false);
  const [actionCreateForm] = Form.useForm<BusinessActionCreate>();
  const [selectedActionId, setSelectedActionId] = useState<number | null>(null);
  const [detailRefresh, setDetailRefresh] = useState(0);

  // ---- 执行相关状态 ----
  const [executeOpen, setExecuteOpen] = useState(false);
  const [executeForm] = Form.useForm<{ environment_id: number; variables: Record<string, unknown> }>();
  const [executionResult, setExecutionResult] = useState<{ execution: FlowExecution; actions: ActionExecution[] } | null>(null);
  const [executionDetailOpen, setExecutionDetailOpen] = useState(false);

  const detailQuery = useQuery({
    queryKey: ['business', flowId, 'detail'],
    queryFn: () => businessApi.getFlowDetail(flowId),
    enabled: flowId > 0,
  });
  const detail = detailQuery.data;

  const editMutation = useMutation({
    mutationFn: (body: BusinessFlowUpdate) => businessApi.updateFlow(flowId, body),
    onSuccess: () => {
      message.success('流程已更新');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setEditOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const createActionMutation = useMutation({
    mutationFn: (body: BusinessActionCreate) =>
      businessApi.createAction(flowId, body),
    onSuccess: () => {
      message.success('步骤已添加');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setActionCreateOpen(false);
      actionCreateForm.resetFields();
      setDetailRefresh((n) => n + 1);
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const deleteActionMutation = useMutation({
    mutationFn: (actionId: number) => businessApi.removeAction(actionId),
    onSuccess: () => {
      message.success('步骤已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setSelectedActionId(null);
      setDetailRefresh((n) => n + 1);
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  // ---- 环境列表（供执行选择器使用）----
  const envQuery = useQuery({
    queryKey: ['project-environments', projectId, 'active'],
    queryFn: () => projectsApi.listEnvironments(projectId),
    staleTime: 60_000,
  });

  // ---- 执行流程 ----
  const executeMutation = useMutation({
    mutationFn: async (body: FlowExecutionRequest) => {
      const execution = await businessApi.executeFlow(flowId, body);
      const actions = await businessApi.listExecutionActions(execution.id);
      return { execution, actions: actions.items ?? [] };
    },
    onSuccess: (result) => {
      setExecuteOpen(false);
      setExecutionResult(result);
      setExecutionDetailOpen(true);
      const status = result.execution.status;
      if (status === 'SUCCESS') {
        message.success('流程执行成功');
      } else {
        message.warning(`流程执行完成，状态：${status}`);
      }
    },
    onError: (e) => {
      message.error(getErrorMessage(e, '执行失败'));
    },
  });

  if (detailQuery.isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (detailQuery.isError)
    return <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />;
  if (!detail) return <Empty />;

  const statusInfo = FLOW_STATUS_LABELS[detail.status] ?? { color: 'default', text: detail.status };

  const tabItems = [
    {
      key: 'steps',
      label: `步骤编排（${detail.actions.length}）`,
      children: (
        <FlowSteps
          actions={detail.actions}
          onReorder={() => {
            queryClient.invalidateQueries({ queryKey: ['business'] });
            setDetailRefresh((n) => n + 1);
          }}
          onDelete={(actionId) => deleteActionMutation.mutate(actionId)}
          deleting={deleteActionMutation.isPending}
          onAdd={() => {
            actionCreateForm.resetFields();
            setActionCreateOpen(true);
          }}
          onSelectAction={setSelectedActionId}
        />
      ),
    },
    {
      key: 'refs',
      label: '变量引用',
      children: <VariableRefPanel flowId={flowId} actions={detail.actions} refreshKey={detailRefresh} />,
    },
    {
      key: 'rules',
      label: '业务规则',
      children: <RulePanel flowId={flowId} projectId={projectId} actions={detail.actions} />,
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <Space direction="vertical" size={0}>
          <Space size={8}>
            <span style={{ fontWeight: 600, fontSize: 16 }}>{detail.name}</span>
            <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
          </Space>
          <span style={detail.description ? undefined : { color: '#999' }}>
            {detail.description ?? '暂无描述'}
          </span>
          <span style={{ color: '#999', fontSize: 12 }}>
            所属业务域：{detail.domain_name ?? '-'}
          </span>
        </Space>
        <Space size="small">
          <Button
            size="small"
            icon={<PlayCircleOutlined />}
            type="primary"
            disabled={detail.status === 'DEPRECATED' || detail.actions.length === 0}
            onClick={() => {
              executeForm.resetFields();
              setExecuteOpen(true);
            }}
          >
            执行
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => {
            editForm.setFieldsValue({ name: detail.name, description: detail.description ?? undefined, status: detail.status as BusinessFlowStatus });
            setEditOpen(true);
          }}>
            编辑流程
          </Button>
        </Space>
      </div>

      <Tabs items={tabItems} size="small" />

      {/* 编辑流程弹窗 */}
      <Modal
        title="编辑业务流程"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={async () => {
          const values = await editForm.validateFields();
          await editMutation.mutateAsync(values);
        }}
        confirmLoading={editMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<BusinessFlowUpdate> form={editForm} layout="vertical">
          <Form.Item name="name" label="流程名称" rules={[{ required: true, message: '请输入流程名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={FLOW_STATUS_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增步骤弹窗 */}
      <Modal
        title="新增业务步骤"
        open={actionCreateOpen}
        onCancel={() => setActionCreateOpen(false)}
        onOk={async () => {
          const values = await actionCreateForm.validateFields();
          await createActionMutation.mutateAsync({
            name: values.name,
            action_key: values.action_key,
            description: values.description || null,
            action_type: values.action_type || 'NORMAL',
            sort: values.sort ?? 0,
          });
        }}
        confirmLoading={createActionMutation.isPending}
        okText="添加"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<BusinessActionCreate>
          form={actionCreateForm}
          layout="vertical"
          initialValues={{ action_type: 'NORMAL' }}
        >
          <Form.Item name="name" label="步骤名称" rules={[{ required: true, message: '请输入步骤名称' }]}>
            <Input maxLength={200} placeholder="如 创建任务" />
          </Form.Item>
          <Form.Item
            name="action_key"
            label="业务标识"
            tooltip="稳定标识，不依赖接口 ID，如 CREATE_TASK"
            rules={[{ required: true, message: '请输入业务标识' }]}
          >
            <Input maxLength={100} placeholder="如 CREATE_TASK" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 步骤配置抽屉 */}
      <Drawer
        title="步骤配置"
        placement="right"
        width={720}
        open={selectedActionId != null}
        onClose={() => setSelectedActionId(null)}
      >
        {selectedActionId != null && detail.actions.some((a) => a.id === selectedActionId) && (
          <ActionDrawer
            projectId={projectId}
            action={detail.actions.find((a) => a.id === selectedActionId)!}
            onConfigChanged={() => {
              queryClient.invalidateQueries({ queryKey: ['business'] });
              setDetailRefresh((n) => n + 1);
            }}
          />
        )}
      </Drawer>

      {/* 执行流程弹窗 */}
      <Modal
        title="执行业务流程"
        open={executeOpen}
        onCancel={() => setExecuteOpen(false)}
        onOk={async () => {
          const values = await executeForm.validateFields();
          await executeMutation.mutateAsync({
            environment_id: values.environment_id,
            variables: values.variables || {},
          });
        }}
        confirmLoading={executeMutation.isPending}
        okText="开始执行"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form
          form={executeForm}
          layout="vertical"
          initialValues={{ variables: {} }}
        >
          <Form.Item
            name="environment_id"
            label="执行环境"
            rules={[{ required: true, message: '请选择执行环境' }]}
          >
            <Select
              placeholder="选择执行环境"
              loading={envQuery.isPending}
              options={(envQuery.data?.items ?? []).map((e) => ({
                value: e.id,
                label: `${e.display_name || e.name} (${e.base_url || '未配置'})`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="variables"
            label="初始变量（JSON）"
            tooltip={'可选，用于提供流程所需的输入变量，如 {"project_id": "P001"}'}
          >
            <Input.TextArea
              rows={3}
              placeholder='{"project_id": "P001", "username": "testuser"}'
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 执行结果弹窗 */}
      <Modal
        title="执行结果"
        open={executionDetailOpen}
        onCancel={() => setExecutionDetailOpen(false)}
        footer={<Button onClick={() => setExecutionDetailOpen(false)}>关闭</Button>}
        width={720}
      >
        {executionResult ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="执行ID">#{executionResult.execution.id}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={executionResult.execution.status === 'SUCCESS' ? 'green' : 'red'}>
                  {executionResult.execution.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {executionResult.execution.started_at || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="结束时间">
                {executionResult.execution.finished_at || '-'}
              </Descriptions.Item>
              {executionResult.execution.error_code && (
                <Descriptions.Item label="错误代码">
                  <Tag color="orange">{executionResult.execution.error_code}</Tag>
                </Descriptions.Item>
              )}
              {executionResult.execution.error_message && (
                <Descriptions.Item label="错误信息" span={2}>
                  {executionResult.execution.error_message}
                </Descriptions.Item>
              )}
            </Descriptions>

            <Steps
              size="small"
              current={executionResult.actions.length}
              items={executionResult.actions.map((a, i) => ({
                title: `步骤 ${i + 1}`,
                description: a.error_message || (a.status === 'SUCCESS' ? `完成 ${a.duration_ms ?? 0}ms` : a.status),
                status: a.status === 'SUCCESS' ? 'finish' : a.status === 'FAILED' ? 'error' : a.status === 'SKIPPED' ? 'wait' : 'process',
              }))}
            />

            {executionResult.actions.some((a) => a.request_snapshot || a.response_snapshot) && (
              <div>
                <h4 style={{ marginBottom: 8 }}>步骤详情</h4>
                {executionResult.actions.map((a, i) => (
                  <Descriptions
                    key={a.id}
                    bordered
                    size="small"
                    column={1}
                    style={{ marginBottom: 8 }}
                  >
                    <Descriptions.Item label={`步骤 ${i + 1} 状态`}>
                      <Tag color={a.status === 'SUCCESS' ? 'green' : 'red'}>{a.status}</Tag>
                      {a.duration_ms != null && <span>耗时 {a.duration_ms}ms</span>}
                      {a.error_code && <Tag color="orange" style={{ marginLeft: 4 }}>{a.error_code}</Tag>}
                    </Descriptions.Item>
                    {a.request_snapshot && (
                      <Descriptions.Item label="请求快照">
                        <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                          {JSON.stringify(a.request_snapshot, null, 2)}
                        </pre>
                      </Descriptions.Item>
                    )}
                    {a.response_snapshot && (
                      <Descriptions.Item label="响应快照">
                        <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                          {JSON.stringify(a.response_snapshot, null, 2)}
                        </pre>
                      </Descriptions.Item>
                    )}
                    {a.error_message && (
                      <Descriptions.Item label="错误信息">{a.error_message}</Descriptions.Item>
                    )}
                    {a.unverified_preconditions && a.unverified_preconditions.length > 0 && (
                      <Descriptions.Item label="未验证的前置条件">
                        {a.unverified_preconditions.map((pc, j) => (
                          <div key={j} style={{ fontSize: 11, color: '#fa8c16' }}>
                            [{String(pc.type)}] {String(pc.target)} - {String(pc.reason)}
                          </div>
                        ))}
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                ))}
              </div>
            )}
          </div>
        ) : (
          <Empty description="暂无数据" />
        )}
      </Modal>
    </div>
  );
}
