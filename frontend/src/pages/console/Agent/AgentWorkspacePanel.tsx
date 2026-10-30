import { Alert, Card, Checkbox, Divider, Empty, Spin, Tabs, Tag, Typography } from 'antd';
import type { AgentWorkspace } from '@/features/agent/contracts';
import { NotificationBriefPanel, ReportBriefPanel } from './AgentPanels';

interface AgentWorkspacePanelProps {
  selectedSessionId: number | null;
  workspace: AgentWorkspace | null;
  selectedCaseIds: number[];
  selectedPointIds: number[];
  onSelectedCaseIdsChange: (ids: number[]) => void;
  onSelectedPointIdsChange: (ids: number[]) => void;
  onOpenReport: () => void;
}

export function AgentWorkspacePanel({
  selectedSessionId,
  workspace,
  selectedCaseIds,
  selectedPointIds,
  onSelectedCaseIdsChange,
  onSelectedPointIdsChange,
  onOpenReport,
}: AgentWorkspacePanelProps) {
  return (
      <div className="agent-workspace-panel agent-workspace-details">
        <Typography.Text strong style={{ fontSize: 14 }}>工作区</Typography.Text>
        <Divider style={{ margin: '4px 0 8px' }} />
        <div className="agent-workspace-scroll">
          {selectedSessionId == null ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择会话" style={{ marginTop: 80 }} />
          ) : !workspace ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : workspace.test_plan || workspace.test_points.length > 0 || workspace.test_cases.length > 0 || workspace.analysis || workspace.report_brief || workspace.notification_brief ? (
            <Tabs
              size="small"
              items={[
                ...(workspace.test_plan
                  ? [{
                      key: 'plan',
                      label: '测试计划',
                      children: (
                        <pre style={{ fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
                          {JSON.stringify(workspace.test_plan, null, 2)}
                        </pre>
                      ),
                    }]
                  : []),
                ...(workspace.test_points.length > 0
                  ? [{
                      key: 'points',
                      label: `测试点(${workspace.test_points.length})`,
                      children: (
                        <div style={{ fontSize: 13 }}>
                          {workspace.stage === 'TEST_POINT_REVIEW' && (
                            <Checkbox.Group
                              style={{ marginBottom: 8 }}
                              value={selectedPointIds}
                              onChange={(vals) => onSelectedPointIdsChange(vals.map((v) => Number(v)))}
                            >
                              {workspace.test_points.map((p) => (
                                <Checkbox key={String(p.id)} value={p.id as number} style={{ display: 'block', marginBottom: 4 }}>
                                  {p.name as string} <Tag color="blue">{p.priority as string}</Tag>
                                </Checkbox>
                              ))}
                            </Checkbox.Group>
                          )}
                          {workspace.test_points.map((p, i) => (
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
                          {workspace.stage === 'TEST_CASE_REVIEW' && (
                            <Checkbox.Group
                              style={{ marginBottom: 8 }}
                              value={selectedCaseIds}
                              onChange={(vals) => onSelectedCaseIdsChange(vals.map((v) => Number(v)))}
                            >
                              {workspace.test_cases.map((c) => (
                                <Checkbox key={String(c.id)} value={c.id as number} style={{ display: 'block', marginBottom: 4 }}>
                                  {c.name as string} <Tag>{c.priority as string}</Tag>
                                </Checkbox>
                              ))}
                            </Checkbox.Group>
                          )}
                          {workspace.test_cases.map((c, i) => (
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
                      children: (
                        <pre style={{ fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
                          {JSON.stringify(workspace.analysis, null, 2)}
                        </pre>
                      ),
                    }]
                  : []),
                ...(workspace.execution_result
                  ? [{
                      key: 'execution',
                      label: '执行',
                      children: (
                        <pre style={{ fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
                          {JSON.stringify(workspace.execution_result, null, 2)}
                        </pre>
                      ),
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
      </div>
  );
}
