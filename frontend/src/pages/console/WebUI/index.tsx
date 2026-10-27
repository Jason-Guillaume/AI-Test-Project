// Web UI 自动化控制台：页面对象、结构化用例、加密登录态、调试历史和报告。
import { useState } from 'react';
import { Alert, App, Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { webUIApi } from '@/api/webUI';
import { reportsApi } from '@/api/reports';
import { businessApi } from '@/api/business';
import { getErrorMessage } from '@/api/client';
import { AuthEditor, CaseEditor, PageEditor } from '@/pages/console/WebUI/Editors';
import { WebArtifacts } from '@/pages/console/WebUI/Artifacts';
import { TaskSourceLinks } from '@/components/tasks/TaskSourceLinks';
import type { WebAuthProfile, WebCase, WebExecution, WebPage } from '@/types';

/** 作用域变化后重建工作区，防止旧项目弹窗或执行选择残留。 */
export function ConsoleWebUIPage() {
  const { currentProjectId } = useConsoleScope();
  return <PageContainer>{currentProjectId ? <Workspace key={currentProjectId} projectId={currentProjectId} /> : <Empty description="请先选择项目" />}</PageContainer>;
}

/** 项目工作区；请求使用项目 queryKey，所有写操作由服务端再次校验权限。 */
function Workspace({ projectId }: { projectId: number }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const caseId = Number(searchParams.get('caseId'));
  const requestedCaseId = Number.isSafeInteger(caseId) && caseId > 0 ? caseId : null;
  const [tab, setTab] = useState('cases');
  const [casePage, setCasePage] = useState(1);
  const [pageModal, setPageModal] = useState<{ row: WebPage | null } | null>(null);
  const [caseModal, setCaseModal] = useState<{ row: WebCase | null } | null>(null);
  const [authModal, setAuthModal] = useState<{ row: WebAuthProfile | null } | null>(null);
  const [environmentId, setEnvironmentId] = useState<number>();
  const [environmentKeyword, setEnvironmentKeyword] = useState('');
  const [selectedExecution, setSelectedExecution] = useState<WebExecution | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [agentOpen, setAgentOpen] = useState(false);
  const [bindCase, setBindCase] = useState<WebCase | null>(null);
  const [flowId, setFlowId] = useState<number>();
  const [actionId, setActionId] = useState<number>();
  const [agentForm] = Form.useForm();
  const cases = useQuery({ queryKey: ['project', projectId, 'web', 'cases', casePage], queryFn: () => webUIApi.cases(projectId, casePage) });
  const requestedCase = useQuery({ queryKey: ['web-case-link', requestedCaseId], queryFn: () => webUIApi.case(requestedCaseId!), enabled: requestedCaseId != null });
  const pages = useQuery({ queryKey: ['project', projectId, 'web', 'pages'], queryFn: () => webUIApi.pages(projectId) });
  const auth = useQuery({ queryKey: ['project', projectId, 'web', 'auth'], queryFn: () => webUIApi.auth(projectId) });
  const environments = useQuery({ queryKey: ['project', projectId, 'web', 'environments', environmentKeyword], queryFn: () => webUIApi.environments(projectId, environmentKeyword) });
  const history = useQuery({ queryKey: ['project', projectId, 'web', 'history', historyPage], queryFn: () => webUIApi.history(projectId, historyPage), enabled: tab === 'history' });
  const flows = useQuery({ queryKey: ['project', projectId, 'web', 'flows'], queryFn: () => businessApi.listFlows(projectId, { page_size: 200 }), enabled: agentOpen || !!bindCase });
  const actions = useQuery({ queryKey: ['project', projectId, 'web', 'actions', flowId], queryFn: () => businessApi.listActions(flowId!), enabled: !!flowId && !!bindCase });
  const write = useMutation({
    mutationFn: (job: () => Promise<unknown>) => job(),
    onSuccess: async () => {
      // 等待缓存刷新后再结束 mutation，防止用户对旧 revision 点击人工确认。
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['project', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['business'] }),
      ]);
      void message.success('操作完成');
    },
    onError: error => void message.error(getErrorMessage(error)),
  });
  /** 人工确认后使用完整测试执行链路，执行结束自动生成既有报告。 */
  function debug(row: WebCase) {
    if (!environmentId) { void message.warning('请选择执行环境'); return; }
    write.mutate(async () => {
      const run = await webUIApi.debug(row.id, environmentId);
      setTab('history');
      await reportsApi.generate(run.id, { generate_ai_summary: false });
      void message.info(`执行 #${run.id}：通过 ${run.passed}，失败 ${run.failed}，错误 ${run.error}`);
    });
  }
  if (cases.isPending || pages.isPending || auth.isPending) return <LoadingState />;
  const failed = cases.error || pages.error || auth.error;
  if (failed) return <ErrorState error={failed} onRetry={() => { void cases.refetch(); void pages.refetch(); void auth.refetch(); }} />;
  const pageRows = pages.data?.items ?? [];
  const authRows = auth.data?.items ?? [];
  const environmentRows = environments.data?.items.filter(e => e.is_active) ?? [];
  return <Space direction="vertical" style={{ width: '100%' }} size="middle">
    <Typography.Title level={4} style={{ margin: 0 }}>Web UI 工作区</Typography.Title>
    {requestedCaseId != null && (requestedCase.isPending ? <LoadingState /> : requestedCase.isError ? (
      <Alert type="warning" showIcon message="用例不存在或无访问权限" />
    ) : requestedCase.data?.project_id !== projectId ? (
      <Alert type="warning" showIcon message={`该用例属于项目 #${requestedCase.data?.project_id}，请先在顶部切换项目`} />
    ) : (
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="info" showIcon message={`已定位 Web 用例 #${requestedCase.data.id}：${requestedCase.data.name}`} action={<Button size="small" onClick={() => setCaseModal({ row: requestedCase.data })}>查看与编辑步骤</Button>} />
        <TaskSourceLinks resourceType="TEST_CASE" resourceId={String(requestedCase.data.id)} />
      </Space>
    ))}
    <Alert type="info" showIcon message="Chromium 隔离执行 · 稳定元素定位 · 结构化步骤 · 人工确认" description="请先在项目设置中授权测试目标，再维护页面对象和登录态。Fixture、Mock、数据变量及正式测试报告沿用现有平台能力。" />
    <Tabs activeKey={tab} onChange={setTab} items={[
      { key: 'cases', label: 'UI 用例与调试', children: <Space direction="vertical" style={{ width: '100%' }}>
        <Space wrap><Button type="primary" onClick={() => setCaseModal({ row: null })}>新增 UI 用例</Button>
          <Button onClick={() => setAgentOpen(true)}>Agent 生成草稿</Button>
          <Button onClick={() => navigate('/console/web-ui-agent')}>浏览器智能编写</Button>
          <Select showSearch filterOption={false} onSearch={setEnvironmentKeyword} style={{ width: 280 }} placeholder="选择执行环境" value={environmentId} onChange={setEnvironmentId} options={environmentRows.map(e => ({ value: e.id, label: `${e.display_name || e.name}（${e.name}）` }))} />
          {environments.isError && <Typography.Text type="danger">环境读取失败</Typography.Text>}
        </Space>
        <Table rowKey="id" dataSource={cases.data?.items ?? []} pagination={{ current: casePage, pageSize: 20, total: cases.data?.total, onChange: setCasePage }} columns={[
          { title: '用例', dataIndex: 'name' }, { title: '步骤', render: (_, row) => row.steps.length },
          { title: '状态', render: (_, row) => <Tag color={row.confirmed ? 'green' : 'gold'}>{row.confirmed ? '已确认' : '待人工确认'} · {row.source_type}</Tag> },
          { title: '操作', render: (_, row) => <Space wrap>
            <Button onClick={() => setCaseModal({ row })}>编辑步骤</Button>
            <Button disabled={!row.confirmed} onClick={() => navigate(`/console/tasks?create=1&projectId=${projectId}&type=WEB&caseId=${row.id}`)}>用此用例创建任务</Button>
            <Button disabled={row.confirmed} loading={write.isPending} onClick={() => modal.confirm({ title: '确认已审核全部步骤、登录态与页面目标？', content: '后续修改用例、页面对象或认证配置后，需要重新确认。', onOk: () => write.mutateAsync(() => webUIApi.confirm(row.id, row.revision)) })}>人工确认</Button>
            <Button type="primary" disabled={!row.confirmed || !environmentId} loading={write.isPending} onClick={() => debug(row)}>调试执行</Button>
            <Button onClick={() => { setBindCase(row); setFlowId(undefined); setActionId(undefined); }}>绑定业务动作</Button>
            <Popconfirm title="删除此测试用例？" onConfirm={() => write.mutate(() => webUIApi.deleteCase(row.id))}><Button danger>删除</Button></Popconfirm>
          </Space> },
        ]} />
      </Space> },
      { key: 'pages', label: '页面对象', children: <Space direction="vertical" style={{ width: '100%' }}>
        <Button type="primary" onClick={() => setPageModal({ row: null })}>新增页面对象</Button>
        <Table rowKey="id" dataSource={pageRows} columns={[{ title: '名称', dataIndex: 'name' }, { title: '路径', dataIndex: 'path' },
          { title: '元素', render: (_, row) => row.elements.map(e => e.key).join('、') },
          { title: '操作', render: (_, row) => <Space><Button onClick={() => setPageModal({ row })}>编辑</Button><Popconfirm title="删除后引用该页面的用例需重新配置，继续？" onConfirm={() => write.mutate(() => webUIApi.deletePage(row.id))}><Button danger>删除</Button></Popconfirm></Space> }]} />
      </Space> },
      { key: 'auth', label: '登录态与测试账号', children: <Space direction="vertical" style={{ width: '100%' }}>
        <Button type="primary" onClick={() => setAuthModal({ row: null })}>新增认证 / 导入人工会话</Button>
        <Table rowKey="id" dataSource={authRows} columns={[{ title: '名称', dataIndex: 'name' },
          { title: '凭据', render: () => '已加密 · 不回显' }, { title: '有效期(UTC)', dataIndex: 'expires_at' },
          { title: '操作', render: (_, row) => <Space><Button onClick={() => setAuthModal({ row })}>替换</Button><Popconfirm title="撤销此登录态？" onConfirm={() => write.mutate(() => webUIApi.deleteAuth(row.id))}><Button danger>撤销</Button></Popconfirm></Space> }]} />
      </Space> },
      { key: 'history', label: '执行历史与报告', children: <>
        {history.isError && <ErrorState error={history.error} onRetry={history.refetch} />}
        <Table rowKey="id" loading={history.isPending} dataSource={history.data?.items ?? []}
          pagination={{ current: historyPage, pageSize: 20, total: history.data?.total, onChange: setHistoryPage }} columns={[
            { title: '执行 ID', dataIndex: 'id' }, { title: '用例 ID', dataIndex: 'test_case_id' }, { title: '状态', dataIndex: 'status' },
            { title: '错误定位', dataIndex: 'error_message' }, { title: '耗时(ms)', dataIndex: 'duration_ms' },
            { title: '操作', render: (_, row) => <Space><Button onClick={() => setSelectedExecution(row)}>日志 / 截图 / Trace</Button>
              {row.report_id ? <Button onClick={() => navigate(`/console/test-reports/${row.report_id}`)}>查看报告</Button> : <Button onClick={() => write.mutate(() => reportsApi.generate(row.test_run_id, { generate_ai_summary: false }))}>生成报告</Button>}
            </Space> },
          ]} />
      </> },
    ]} />
    {pageModal && <PageEditor key={pageModal.row?.id ?? 'new'} initial={pageModal.row} busy={write.isPending} onClose={() => setPageModal(null)} onSave={body => write.mutate(async () => { await webUIApi.savePage(projectId, body, pageModal.row?.id); setPageModal(null); })} />}
    {caseModal && <CaseEditor key={caseModal.row?.id ?? 'new'} initial={caseModal.row} pages={pageRows} auth={authRows} busy={write.isPending} onClose={() => setCaseModal(null)} onSave={body => write.mutate(async () => { await webUIApi.saveCase(projectId, body, caseModal.row?.id); await cases.refetch(); setCaseModal(null); })} />}
    {authModal && <AuthEditor key={authModal.row?.id ?? 'new'} initial={authModal.row} environments={environmentRows} busy={write.isPending} onClose={() => setAuthModal(null)} onSave={body => write.mutate(async () => { await webUIApi.saveAuth(projectId, body, authModal.row?.id); setAuthModal(null); })} />}
    <Modal title="执行详情" open={!!selectedExecution} onCancel={() => setSelectedExecution(null)} footer={null} width={1000} destroyOnClose>
      {selectedExecution?.error_message && <Alert type="error" message={selectedExecution.error_message} />}
      <WebArtifacts snapshot={selectedExecution?.response_snapshot} />
    </Modal>
    <Modal title="Agent 生成 UI 步骤草稿" open={agentOpen} destroyOnClose onCancel={() => setAgentOpen(false)} confirmLoading={write.isPending} onOk={() => agentForm.submit()}>
      <Alert type="info" message="只生成未确认草稿；人工审核、选择账号并确认后才能执行。" />
      <Form form={agentForm} layout="vertical" onFinish={body => write.mutate(async () => {
        const draft = await webUIApi.generate(projectId, body);
        setAgentOpen(false); setCaseModal({ row: draft });
      })} initialValues={{ page_object_ids: [] }}>
        <Form.Item name="instruction" label="业务目标" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
        <Form.Item name="flow_id" label="关联业务流程"><Select allowClear options={flows.data?.items.map(f => ({ value: f.id, label: f.name }))} /></Form.Item>
        <Form.Item name="page_object_ids" label="页面上下文（空表示全部）"><Select mode="multiple" options={pageRows.map(p => ({ value: p.id, label: p.name }))} /></Form.Item>
      </Form>
    </Modal>
    <Modal title={`绑定业务动作：${bindCase?.name ?? ''}`} open={!!bindCase} destroyOnClose onCancel={() => setBindCase(null)} confirmLoading={write.isPending}
      onOk={() => { if (bindCase && actionId) write.mutate(async () => { await webUIApi.bind(actionId, bindCase.id); setBindCase(null); }); }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="info" message="选择 WEB 作为此动作默认通道，流程内其他 API 动作保持原有配置。" />
        <Select style={{ width: '100%' }} placeholder="业务流程" value={flowId} onChange={id => { setFlowId(id); setActionId(undefined); }} options={flows.data?.items.map(f => ({ value: f.id, label: f.name }))} />
        <Select style={{ width: '100%' }} placeholder="业务动作" value={actionId} onChange={setActionId} options={actions.data?.map(a => ({ value: a.id, label: a.name }))} />
      </Space>
    </Modal>
  </Space>;
}
