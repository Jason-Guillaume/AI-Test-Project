import { Alert, Button, Card, Checkbox, Divider, Empty, Flex, Space, Spin, Tabs, Tag, Typography } from 'antd';
import type { AgentWorkspace } from '@/features/agent/contracts';
import { NotificationBriefPanel, ReportBriefPanel } from './AgentPanels';
import { AgentStructuredSummary } from './AgentSummaries';
import { toggleAllSelection } from './agentSelection.mjs';

interface AgentWorkspacePanelProps {
  selectedSessionId: number | null;
  workspace: AgentWorkspace | null;
  selectedCaseIds: number[];
  selectedPointIds: number[];
  loading: boolean;
  error: unknown;
  actionsPending: boolean;
  onRetry: () => void;
  onAction: (action: string) => void;
  onSelectedCaseIdsChange: (ids: number[]) => void;
  onSelectedPointIdsChange: (ids: number[]) => void;
  onOpenReport: () => void;
}

export function AgentWorkspacePanel({
  selectedSessionId,
  workspace,
  selectedCaseIds,
  selectedPointIds,
  loading,
  error,
  actionsPending,
  onRetry,
  onAction,
  onSelectedCaseIdsChange,
  onSelectedPointIdsChange,
  onOpenReport,
}: AgentWorkspacePanelProps) {
  const pointIds = (workspace?.test_points ?? [])
    .map((point) => point.id)
    .filter((id): id is number => typeof id === 'number');
  const visibleCases = workspace?.stage === 'READY_TO_EXECUTE'
    ? (workspace.test_cases ?? []).filter((testCase) => workspace.confirmed_case_ids?.includes(testCase.id as number))
    : workspace?.test_cases ?? [];
  const caseIds = visibleCases
    .map((testCase) => testCase.id)
    .filter((id): id is number => typeof id === 'number');
  const canSelectPoints = workspace?.stage === 'TEST_POINT_REVIEW';
  const canSelectCases = workspace?.stage === 'TEST_CASE_REVIEW' || workspace?.stage === 'READY_TO_EXECUTE';
  const allPointsSelected = pointIds.length > 0 && pointIds.every((id) => selectedPointIds.includes(id));
  const allCasesSelected = caseIds.length > 0 && caseIds.every((id) => selectedCaseIds.includes(id));

  return (
      <div className="agent-workspace-panel agent-workspace-details" id="agent-workspace-panel">
        <Typography.Text strong style={{ fontSize: 14 }}>工作区</Typography.Text>
        <Divider style={{ margin: '4px 0 8px' }} />
        <div className="agent-workspace-scroll">
          {selectedSessionId == null ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择会话" style={{ marginTop: 80 }} />
          ) : error ? (
            <Alert
              type="error"
              showIcon
              message="读取 Agent 工作区失败"
              description={error instanceof Error ? error.message : '请重试读取工作区'}
              action={<Button size="small" onClick={onRetry}>重试</Button>}
            />
          ) : loading ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : !workspace ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前会话暂无工作区快照" style={{ marginTop: 48 }} />
          ) : workspace.test_plan || workspace.test_points.length > 0 || workspace.test_cases.length > 0 || workspace.execution_result || workspace.analysis || workspace.report_brief || workspace.notification_brief ? (
            <Tabs
              size="small"
              items={[
                ...(workspace.test_plan
                  ? [{
                      key: 'plan',
                      label: '测试计划',
                      children: <AgentStructuredSummary kind="plan" value={{ plan: workspace.test_plan, intent: workspace.intent }} />,
                    }]
                  : []),
                ...(workspace.test_points.length > 0
                  ? [{
                      key: 'points',
                      label: `测试点(${workspace.test_points.length})`,
                      children: (
                        <div style={{ fontSize: 13 }}>
                          {canSelectPoints && (
                            <Flex align="center" justify="space-between" style={{ marginBottom: 8 }}>
                              <Typography.Text type="secondary">已选 {selectedPointIds.length}/{pointIds.length} 个测试点</Typography.Text>
                              <Button size="small" onClick={() => onSelectedPointIdsChange(toggleAllSelection(selectedPointIds, pointIds))}>
                                {allPointsSelected ? '取消全选' : '全选'}
                              </Button>
                            </Flex>
                          )}
                          {canSelectPoints && (
                            <Checkbox.Group
                              style={{ marginBottom: 8 }}
                              value={selectedPointIds}
                              onChange={(vals) => onSelectedPointIdsChange(vals.map((v) => Number(v)))}
                            >
                              {workspace.test_points.map((p) => (
                                <Card key={String(p.id)} size="small" style={{ marginBottom: 6 }}>
                                  <Checkbox value={p.id as number}>
                                    <Typography.Text strong>{p.name as string}</Typography.Text>
                                    <Tag color="blue" style={{ marginLeft: 8 }}>{p.priority as string}</Tag>
                                  </Checkbox>
                                  {p.description != null && <Typography.Text type="secondary" style={{ display: 'block', margin: '4px 0 0 24px' }}>{p.description as string}</Typography.Text>}
                                </Card>
                              ))}
                            </Checkbox.Group>
                          )}
                          {!canSelectPoints && workspace.test_points.map((p, i) => (
                            <Card key={i} size="small" style={{ marginBottom: 4 }}>
                              <Typography.Text strong>{p.name as string}</Typography.Text>
                              <Tag color="blue" style={{ marginLeft: 8 }}>{p.priority as string}</Tag>
                              {p.description != null && <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>{p.description as string}</Typography.Text>}
                            </Card>
                          ))}
                        </div>
                      ),
                    }]
                  : []),
                ...(workspace.test_cases.length > 0
                  ? [{
                      key: 'cases',
                      label: `用例(${workspace.test_cases.length})`,
                      children: (
                        <div style={{ fontSize: 13 }}>
                          {canSelectCases && (
                            <Flex align="center" justify="space-between" style={{ marginBottom: 8 }}>
                              <Typography.Text type="secondary">
                                {workspace.stage === 'READY_TO_EXECUTE' ? '本次执行范围' : '已选'} {selectedCaseIds.length}/{caseIds.length} 条用例
                              </Typography.Text>
                              <Button size="small" onClick={() => onSelectedCaseIdsChange(toggleAllSelection(selectedCaseIds, caseIds))}>
                                {allCasesSelected ? '取消全选' : '全选'}
                              </Button>
                            </Flex>
                          )}
                          {canSelectCases && (
                            <Checkbox.Group
                              style={{ marginBottom: 8 }}
                              value={selectedCaseIds}
                              onChange={(vals) => onSelectedCaseIdsChange(vals.map((v) => Number(v)))}
                            >
                              {visibleCases.map((c) => (
                                <Card key={String(c.id)} size="small" style={{ marginBottom: 6 }}>
                                  <Checkbox value={c.id as number}>
                                    <Typography.Text strong>{c.name as string}</Typography.Text>
                                    <Tag style={{ marginLeft: 8 }}>{c.priority as string}</Tag>
                                    {c.case_type != null && <Tag color="green">{c.case_type as string}</Tag>}
                                  </Checkbox>
                                </Card>
                              ))}
                            </Checkbox.Group>
                          )}
                          {!canSelectCases && workspace.test_cases.map((c, i) => (
                            <Card key={i} size="small" style={{ marginBottom: 4 }}>
                              <Typography.Text strong>{c.name as string}</Typography.Text>
                              <Tag style={{ marginLeft: 8 }}>{c.priority as string}</Tag>
                              {c.case_type != null && <Tag color="green">{c.case_type as string}</Tag>}
                            </Card>
                          ))}
                        </div>
                      ),
                    }]
                  : []),
                ...(workspace.analysis
                  ? [{
                      key: 'analysis',
                      label: '分析',
                      children: <AgentStructuredSummary kind="analysis" value={workspace.analysis} />,
                    }]
                  : []),
                ...(workspace.execution_result
                  ? [{
                      key: 'execution',
                      label: '执行',
                      children: <AgentStructuredSummary kind="execution" value={workspace.execution_result} />,
                    }]
                  : []),
                ...(workspace.report_brief
                  ? [{
                      key: 'report',
                      label: '报告',
                      children: (
                        <ReportBriefPanel
                          brief={workspace.report_brief}
                          onOpen={() =>
                            workspace.report_id != null
                              ? onOpenReport()
                              : undefined
                          }
                        />
                      ),
                    }]
                  : []),
                ...(workspace.notification_brief
                  ? [{
                      key: 'notification',
                      label: '通知',
                      children: <NotificationBriefPanel brief={workspace.notification_brief} />,
                    }]
                  : []),
              ]}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工作区数据" style={{ marginTop: 48 }} />
          )}
        </div>

        {workspace?.error && (
          <Alert
            type="error"
            showIcon
            message="Agent 报错"
            description={workspace.error.message as string}
            style={{ marginTop: 8, fontSize: 12 }}
          />
        )}

        {workspace?.suggested_actions.length ? (
          <div className="agent-workspace-actions" aria-label="工作区操作">
            <Space wrap>
              {workspace.suggested_actions.map((action) => {
                const requiresPoints = action === 'confirm_points';
                const requiresCases = action === 'confirm_cases' || action === 'execute';
                const disabled = (requiresPoints && selectedPointIds.length === 0)
                  || (requiresCases && selectedCaseIds.length === 0);
                const label: Record<string, string> = {
                  confirm_points: '确认所选测试点',
                  confirm_cases: '确认所选用例',
                  execute: '执行所选用例',
                  regenerate_points: '重新生成测试点',
                  regenerate_cases: '重新生成测试用例',
                  analyze: '分析结果',
                  confirm_report: '确认并发送通知',
                  skip_notification: '跳过通知',
                };
                return (
                  <Button
                    key={action}
                    type={requiresPoints || requiresCases ? 'primary' : 'default'}
                    disabled={disabled}
                    loading={actionsPending}
                    onClick={() => onAction(action)}
                  >
                    {label[action] ?? action}
                  </Button>
                );
              })}
            </Space>
            {(workspace.suggested_actions.includes('confirm_points') && selectedPointIds.length === 0)
              || (workspace.suggested_actions.some((action) => action === 'confirm_cases' || action === 'execute') && selectedCaseIds.length === 0) ? (
                <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6 }}>
                  请先在对应结果中选择至少一项；零选不会被解释为全选。
                </Typography.Text>
              ) : null}
          </div>
        ) : null}
      </div>
  );
}
