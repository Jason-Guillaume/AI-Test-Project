/**
 * 统一任务详情的参与者、会话、调度和产物面板。
 * 接收详情页已校验归属的数据与显式操作回调；不发请求、不决定权限，也不持有运行状态。
 */
import type { Dispatch, SetStateAction } from 'react';
import { Alert, Button, Card, Empty, Flex, Input, List, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd';
import { PlayCircleOutlined, SendOutlined } from '@ant-design/icons';
import type { Task, TaskAgentInstance, TaskEvent, TaskMessage, TaskPlan, TaskResourceRef, TaskRun, TaskRunDetail, TaskToolInvocation, TaskWorkItem } from '@/features/tasks/contracts';
import { fmtTime } from '@/shared/lib/format';
import { EventTimeline, MessageRow, ResourceList } from './TaskDetailActivity';
import { ROLE_LABEL, STATUS_LABEL, TERMINAL, TOOL_CALL_STATUS } from './taskLabels';
import type { TaskSecurityAssessmentPreview, TaskSecurityAssessmentSelection } from './taskTypes';

type TaskMessageType = 'TEXT' | 'GOAL_UPDATE' | 'REQUIREMENT';

interface TaskRunPanelsProps {
  task: Task;
  run: TaskRun;
  detail: TaskRunDetail | undefined;
  agents: TaskAgentInstance[];
  workItems: TaskWorkItem[];
  selectedId: number | 'events' | null;
  selectedAgent: TaskAgentInstance | null;
  selectedMessages: TaskMessage[];
  events: TaskEvent[];
  resources: TaskResourceRef[];
  historicalRun: boolean;
  latestPlan: TaskPlan | undefined;
  securityAssessmentSelection: TaskSecurityAssessmentSelection | null | undefined;
  securityAssessmentPreview: TaskSecurityAssessmentPreview | null | undefined;
  securityApiIds: number[];
  mainSelected: boolean;
  canMessageWorker: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  messageType: TaskMessageType;
  onMessageTypeChange: Dispatch<SetStateAction<TaskMessageType>>;
  onSelectAgent: (id: number | 'events') => void;
  sendPending: boolean;
  onSend: () => void;
  onRetryWorkItem: (workItemId: number) => void;
}

/** 展示已加载运行的工作台，并将命令交由详情页处理。 */
export function TaskRunPanels(props: TaskRunPanelsProps) {
  const {
    task,
    run,
    detail,
    agents,
    workItems,
    selectedId,
    selectedAgent,
    selectedMessages,
    events,
    resources,
    historicalRun,
    latestPlan,
    securityAssessmentSelection,
    securityAssessmentPreview,
    securityApiIds,
    mainSelected,
    canMessageWorker,
    draft,
    onDraftChange,
    messageType,
    onMessageTypeChange,
    onSelectAgent,
    sendPending,
    onSend,
    onRetryWorkItem,
  } = props;
  const roleItems = [
    ...agents.map((agent) => ({ key: String(agent.id), label: agent.display_name, agent })),
    { key: 'events', label: '系统事件', agent: null },
  ];

  return (
    <>
      <div className="task-workspace">
        <Card title="任务参与者" size="small" styles={{ body: { padding: 8 } }}>
          <List
            size="small"
            dataSource={roleItems}
            renderItem={(item) => {
              const agent = item.agent as TaskAgentInstance | null;
              const selected = String(selectedId ?? agents.find((entry) => entry.role === 'MAIN')?.id) === item.key;
              const state = agent ? agent.status : 'READ_ONLY';
              const stateLabel = agent ? (STATUS_LABEL[state] ?? state) : '只读';
              return (
                <List.Item
                  onClick={() => onSelectAgent(item.key === 'events' ? 'events' : Number(item.key))}
                  style={{ cursor: 'pointer', background: selected ? 'rgba(22, 119, 255, .08)' : undefined, paddingInline: 10 }}
                >
                  <List.Item.Meta
                    title={item.label}
                    description={agent ? `#${agent.id} · ${stateLabel}` : '持久化时间线'}
                  />
                </List.Item>
              );
            }}
          />
        </Card>

        <Card
          size="small"
          title={selectedAgent ? `${selectedAgent.display_name} · ${ROLE_LABEL[selectedAgent.role] ?? selectedAgent.role}` : '系统事件'}
          extra={selectedAgent && <Tag>{STATUS_LABEL[selectedAgent.status] ?? selectedAgent.status}</Tag>}
        >
          <Tabs
            items={[
              {
                key: 'conversation', label: '会话',
                children: selectedId === 'events' ? (
                  <EventTimeline events={events} />
                ) : (
                  <>
                    <List
                      dataSource={selectedMessages}
                      locale={{ emptyText: <Empty description="该参与者暂无消息" /> }}
                      renderItem={(item) => <MessageRow key={item.id} message={item} projectId={task.project_id} />}
                    />
                    {!historicalRun && selectedAgent && (mainSelected ? !TERMINAL.has(run.status) : canMessageWorker) && (
                      <div style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 16 }}>
                        <Space style={{ marginBottom: 8 }}>
                          {mainSelected ? (
                            <>
                              <Button size="small" type={messageType === 'TEXT' ? 'primary' : 'default'} onClick={() => onMessageTypeChange('TEXT')}>发消息</Button>
                              <Button size="small" type={messageType === 'GOAL_UPDATE' ? 'primary' : 'default'} onClick={() => onMessageTypeChange('GOAL_UPDATE')}>调整整体目标</Button>
                            </>
                          ) : <Tag color="purple">补充给指定 {selectedAgent.display_name}</Tag>}
                        </Space>
                        <Input.TextArea
                          value={draft}
                          onChange={(event) => onDraftChange(event.target.value)}
                          rows={3}
                          maxLength={8000}
                          placeholder={mainSelected ? (messageType === 'GOAL_UPDATE' ? '输入新的整体目标，将建立新的运行版本' : '向任务主 Agent 发送消息') : `向当前${selectedAgent?.display_name}提供补充要求`}
                        />
                        <Flex justify="flex-end" style={{ marginTop: 8 }}>
                          <Button
                            type="primary"
                            icon={<SendOutlined />}
                            loading={sendPending}
                            disabled={!draft.trim()}
                            onClick={() => {
                              if (!mainSelected) onMessageTypeChange('REQUIREMENT');
                              onSend();
                            }}
                          >发送</Button>
                        </Flex>
                      </div>
                    )}
                    {selectedAgent && !mainSelected && !canMessageWorker && <Alert type="info" showIcon message={`${selectedAgent.display_name} 当前没有可接收补充要求的工作项`} />}
                  </>
                ),
              },
              {
                key: 'plan', label: '方案与调度',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {!latestPlan ? <Empty description="Planner 尚未提交方案" /> : (
                      <Card size="small" title={`方案 v${latestPlan.version} · ${latestPlan.status}`}>
                        <Typography.Paragraph>{String(latestPlan.plan_json.summary ?? '')}</Typography.Paragraph>
                        <Typography.Text strong>验收条件</Typography.Text>
                        <List size="small" dataSource={(latestPlan.plan_json.acceptance_criteria as string[] | undefined) ?? []} renderItem={(item) => <List.Item>{item}</List.Item>} />
                        <Typography.Text type="secondary">用例范围：{((latestPlan.plan_json.case_ids as number[] | undefined) ?? []).map((id) => `#${id}`).join('、')}</Typography.Text>
                      </Card>
                    )}
                    {agents.some((item) => item.role === 'SUB_AGENT') && <Card size="small" title="LangGraph 子 Agent 节点">
                      <List size="small" dataSource={agents.filter((item) => item.role === 'SUB_AGENT')} renderItem={(item) => <List.Item><Space><Typography.Text strong>{item.display_name}</Typography.Text><Tag>v{String(item.config_snapshot.agent_version ?? 1)}</Tag><Tag color={item.status === 'SUCCEEDED' ? 'green' : item.status === 'FAILED' ? 'red' : 'blue'}>{STATUS_LABEL[item.status] ?? item.status}</Tag></Space></List.Item>} />
                    </Card>}
                    <Card size="small" title={`工具调用审计 · ${detail?.tool_invocations.length ?? 0}`}>
                      <Typography.Text type="secondary">仅展示调用身份和状态，不展示工具参数或结果。</Typography.Text>
                      <Table<TaskToolInvocation>
                        size="small"
                        rowKey="id"
                        pagination={false}
                        dataSource={detail?.tool_invocations ?? []}
                        locale={{ emptyText: <Empty description="暂无工具调用记录" /> }}
                        columns={[
                          { title: '工具', dataIndex: 'tool_name' },
                          { title: '状态', dataIndex: 'status', render: (state: string) => <Tag color={state === 'SUCCEEDED' ? 'green' : state === 'FAILED' ? 'red' : 'blue'}>{TOOL_CALL_STATUS[state] ?? state}</Tag> },
                          { title: '时间', dataIndex: 'created_at', render: fmtTime },
                          { title: '错误码', dataIndex: 'error_code', render: (value: string | null) => value || '—' },
                        ]}
                      />
                    </Card>
                    {securityAssessmentSelection && (
                      <Card size="small" title="自研安全评估计划预览">
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <Typography.Text>
                            {securityApiIds.length} 个 API（{securityApiIds.map((id) => `#${id}`).join('、')}）· {securityAssessmentSelection.strategy_ids?.length ?? 0} 个策略 · 共 {securityAssessmentPreview?.estimated_count ?? 0} 条计划项
                          </Typography.Text>
                          {securityAssessmentPreview?.truncated && <Alert type="error" showIcon message="计划预览已截断，当前不能确认执行；请减少策略后重新创建任务。" />}
                          {securityAssessmentPreview?.web_inspection && (
                            <Card size="small" title={`Web 页面被动观察 · 会话 #${securityAssessmentPreview.web_inspection.session_id}`}>
                              <Typography.Text type="secondary">
                                页面 HTTPS：{securityAssessmentPreview.web_inspection.page?.https ? '是' : '否'} · HTTP 状态：{securityAssessmentPreview.web_inspection.page?.response_status ?? '未知'}。{securityAssessmentPreview.web_inspection.interpretation}
                              </Typography.Text>
                              <List
                                size="small"
                                dataSource={securityAssessmentPreview.web_inspection.signals ?? []}
                                locale={{ emptyText: '未观察到候选信号' }}
                                renderItem={(signal) => <List.Item><Space><Tag color={signal.severity === 'LOW' ? 'orange' : 'blue'}>{signal.severity}</Tag>{signal.title}</Space></List.Item>}
                              />
                            </Card>
                          )}
                          <List
                            size="small"
                            dataSource={securityAssessmentPreview?.plans ?? []}
                            locale={{ emptyText: <Empty description="安全计划正在生成" /> }}
                            renderItem={(apiPlan) => (
                              <List.Item>
                                <Space direction="vertical" style={{ width: '100%' }}>
                                  <Typography.Text strong>API #{apiPlan.api.id} · {apiPlan.api.method} {apiPlan.api.path} · {apiPlan.api.name}</Typography.Text>
                                  <Typography.Text type="secondary">策略：{apiPlan.strategies?.map((strategy) => strategy.name).join('、') || '—'}</Typography.Text>
                                  <List
                                    size="small"
                                    dataSource={apiPlan.plan.items ?? []}
                                    locale={{ emptyText: <Empty description="该 API 没有可用变异项" /> }}
                                    renderItem={(item) => (
                                      <List.Item>
                                        <Space direction="vertical" size={0}>
                                          <Space wrap>
                                            <Typography.Text strong>#{item.index + 1} {item.name}</Typography.Text>
                                            <Tag>{item.mutation_type}</Tag>
                                            <Tag color={item.confirmation_required ? 'red' : 'blue'}>{item.confirmation_required ? '需高风险确认' : item.risk_level ?? item.severity ?? '普通风险'}</Tag>
                                          </Space>
                                          <Typography.Text type="secondary">
                                            {[item.method, item.location, item.field].filter(Boolean).join(' · ') || '按策略规则执行'}
                                            {item.blocked_reason ? ` · 暂不可执行：${item.blocked_reason}` : ''}
                                          </Typography.Text>
                                        </Space>
                                      </List.Item>
                                    )}
                                  />
                                </Space>
                              </List.Item>
                            )}
                          />
                          {!securityAssessmentPreview?.plans?.length && securityAssessmentPreview?.items?.length ? (
                            <List size="small" dataSource={securityAssessmentPreview.items} renderItem={(item) => <List.Item>#{item.index + 1} {item.name} · {item.mutation_type}</List.Item>} />
                          ) : null}
                          <Alert type="info" showIcon message="模型只解释预览计划；实际执行目标、策略和变异由服务端固定。高风险项需要在确认窗口显式授权。" />
                        </Space>
                      </Card>
                    )}
                    <Table<TaskWorkItem>
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={workItems}
                      columns={[
                        { title: '职责', dataIndex: 'kind', render: (kind: string) => ROLE_LABEL[{ PLAN: 'PLANNER', EXECUTE_API: 'API_WORKER', EXECUTE_WEB: 'UI_WORKER', EXECUTE_SECURITY: 'SECURITY_WORKER', SECURITY_SCAN: 'SECURITY_WORKER', REPORT: 'REPORT_AGENT', REVIEW: 'REVIEWER', FINALIZE: 'MAIN' }[kind] ?? kind] ?? kind },
                        { title: '状态', dataIndex: 'status', render: (state: string) => STATUS_LABEL[state] ?? state },
                        { title: '尝试', dataIndex: 'attempt_count', width: 80 },
                        { title: '结果/错误', render: (_, row) => row.error_message ?? JSON.stringify(row.output_json ?? {}) },
                        {
                          title: '操作',
                          width: 110,
                          render: (_, row) => {
                            if (historicalRun || row.status !== 'FAILED') return null;
                            if (!row.retryable) {
                              return (
                                <Tooltip title={row.retry_block_reason ?? '当前工作项不可重试'}>
                                  <Button size="small" disabled>不可重试</Button>
                                </Tooltip>
                              );
                            }
                            return (
                              <Button
                                size="small"
                                icon={<PlayCircleOutlined />}
                                onClick={() => onRetryWorkItem(row.id)}
                              >
                                重试
                              </Button>
                            );
                          },
                        },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: 'resources', label: '产物',
                children: <ResourceList resources={resources} projectId={task.project_id} targetType={run.input_snapshot.target_type} />,
              },
              {
                key: 'events', label: '运行记录',
                children: <EventTimeline events={events} />,
              },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
