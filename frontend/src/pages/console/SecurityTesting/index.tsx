import { collectPages } from '@/shared/api/pagination';
// 安全测试页（用户控制台）。
//
// 四个 Tab：概览 / 策略与规则 / 安全用例 / 疑似问题。
//   - 概览：无后端 overview 端点，前端从 cases / findings / strategies / apis 聚合。
//   - 策略与规则：系统模板只读；项目策略可建/改/删，规则可建/改/删（预留类强制停用）。
//   - 安全用例：新建安全计划（预览 Modal）→ 确认生成 → 高风险确认 → 执行（测试环境）
//     → 打开变异详情抽屉。confirm-risk / execute 都只能由人在本页触发。
//   - 疑似问题：可人工关联缺陷，状态变更仍需独立确认。
//
// 权限（服务端为准）：读 viewer+；策略规则与 Finding 状态 editor+；计划/用例/执行 member+。
// 安全红线：本页不做注入 / 扫描器；不在生产环境发安全变异请求（allow_production 恒不生效，
// 由后端 gate 强制）；疑似问题文案统一「疑似问题」，不写「已发现漏洞」。
//
// 依赖当前项目作用域：未选项目时整页空态。切换项目由 useConsoleScope 失效相关缓存。
import { Button, Card, Col, Empty, Row, Spin, Statistic, Tabs, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { ErrorState, EmptyState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import {
  COVERAGE_OPTIONS,
  categoryToCoverage,
  severityColor,
  severityLabel,
} from './constants';
import { StrategyTab } from './StrategyTab';
import { CasesTab } from './CasesTab';
import { FindingsTab } from './FindingsTab';

/**
 * 安全测试页：项目作用域下的四个 Tab。
 *
 * 不发请求做鉴权；数据由各 Tab 的 useQuery 触发。未选项目时整页空态。
 */
export function ConsoleSecurityTestingPage() {
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const requestedProjectId = Number(searchParams.get('projectId'));
  const activeTab = ['overview', 'strategies', 'cases', 'findings'].includes(requestedTab ?? '')
    ? requestedTab!
    : 'overview';

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }
  if (requestedProjectId > 0 && requestedProjectId !== currentProjectId) return <PageContainer><EmptyState description={`此链接指向项目 #${requestedProjectId}，请先在顶部切换项目`} /></PageContainer>;

  return (
    <PageContainer>
      <Tabs
        tabBarExtraContent={<Button onClick={() => navigate(`/console/tasks?create=1&projectId=${currentProjectId}&type=SECURITY`)}>创建安全评估任务</Button>}
        activeKey={activeTab}
        onChange={(key) => {
          const next = new URLSearchParams(searchParams);
          next.set('tab', key);
          setSearchParams(next, { replace: true });
        }}
        items={[
          { key: 'overview', label: '概览', children: <OverviewTab projectId={currentProjectId} /> },
          {
            key: 'strategies',
            label: '策略与规则',
            children: <StrategyTab projectId={currentProjectId} />,
          },
          { key: 'cases', label: '安全用例', children: <CasesTab projectId={currentProjectId} /> },
          {
            key: 'findings',
            label: '疑似问题',
            children: <FindingsTab projectId={currentProjectId} />,
          },
        ]}
      />
    </PageContainer>
  );
}

/** 概览 Tab：前端聚合，无后端 overview 端点。 */
function OverviewTab({ projectId }: { projectId: number }) {
  // 汇总完整分页结果，查询失败时不显示误导性零值。
  const casesQuery = useQuery({
    queryKey: ['security-overview', projectId, 'cases'],
    queryFn: () => collectPages((page) => securityApi.listCases(projectId, { page, page_size: 100 })),
  });
  const findingsQuery = useQuery({
    queryKey: ['security-overview', projectId, 'findings'],
    queryFn: () => collectPages((page) => securityApi.listFindings(projectId, { page, page_size: 100, status: 'OPEN' })),
  });
  const strategiesQuery = useQuery({
    queryKey: ['security-overview', projectId, 'strategies'],
    queryFn: () => collectPages((page) => securityApi.listStrategies(projectId, { page, page_size: 100 })),
  });
  const apisQuery = useQuery({
    queryKey: ['security-overview', projectId, 'apis'],
    queryFn: () => apiCatalogApi.listApis(projectId, { page: 1, page_size: 1 }),
  });

  const loading =
    casesQuery.isLoading ||
    findingsQuery.isLoading ||
    strategiesQuery.isLoading ||
    apisQuery.isLoading;
  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }

  const failed = [casesQuery, findingsQuery, strategiesQuery, apisQuery].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;

  const cases = casesQuery.data?.items ?? [];
  const findings = findingsQuery.data?.items ?? [];
  const strategies = strategiesQuery.data?.items ?? [];
  const apiTotal = apisQuery.data?.total ?? 0;

  // 覆盖接口数 = 安全用例里出现过的不同 api_id 数。
  const coveredApis = new Set(
    cases.map((c) => c.api_id).filter((id): id is number => id != null),
  ).size;
  // 高危 / 严重疑似问题 = OPEN 中 severity 为 HIGH / CRITICAL。
  const highCritical = findings.filter(
    (f) => f.severity === 'HIGH' || f.severity === 'CRITICAL',
  ).length;
  // 最近一次含安全用例的执行（取最近一次 latest_execution）。
  const latestRunId = cases
    .map((c) => c.latest_execution?.test_run_id ?? null)
    .filter((id): id is number => id != null)
    .sort((a, b) => b - a)[0];

  // 六类覆盖：每类下启用策略数（按 category 归并）。
  // 不套 useMemo：这里已经有早返回（loading 分支），早返回之后再调用 hook 会触发
  // React「渲染时 hook 数量不一致」崩溃。数据量 ≤100 条，直接算即可。
  const counts: Record<string, number> = {};
  for (const opt of COVERAGE_OPTIONS) counts[opt.value] = 0;
  for (const s of strategies) {
    if (!s.enabled) continue;
    const cov = categoryToCoverage(s.category);
    if (cov) counts[cov] = (counts[cov] ?? 0) + 1;
  }
  const coverageCounts = counts;

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic title="安全用例" value={casesQuery.data?.total ?? cases.length} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic title="覆盖接口" value={coveredApis} suffix={`/ ${apiTotal}`} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic
              title="待处理疑似问题"
              value={findingsQuery.data?.total ?? findings.length}
              valueStyle={{ color: '#cf1322' }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card size="small">
            <Statistic
              title="高危 / 严重"
              value={highCritical}
              valueStyle={{ color: '#cf1322' }}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="六类覆盖（启用策略数）" style={{ marginTop: 16 }}>
        {COVERAGE_OPTIONS.every((o) => (coverageCounts[o.value] ?? 0) === 0) ? (
          <Empty description="尚未启用任何策略" />
        ) : (
          <Row gutter={[12, 12]}>
            {COVERAGE_OPTIONS.map((o) => (
              <Col key={o.value} xs={12} md={8} lg={4}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Typography.Text type="secondary">{o.label}</Typography.Text>
                  <Typography.Text strong>{coverageCounts[o.value] ?? 0}</Typography.Text>
                </div>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <Card size="small" title="最近安全执行" style={{ marginTop: 16 }}>
        {latestRunId == null ? (
          <Empty description="尚未执行过安全用例" />
        ) : (
          <Typography.Text>
            最近一次含安全用例的执行记录：
            <Tag color="blue" style={{ marginLeft: 8 }}>
              TestRun #{latestRunId}
            </Tag>
            {' · 前往「测试报告」查看安全摘要'}
          </Typography.Text>
        )}
      </Card>

      <Card size="small" title="高危疑似问题 Top" style={{ marginTop: 16 }}>
        {findings.length === 0 ? (
          <Empty description="无待处理疑似问题" />
        ) : (
          <Row gutter={[12, 12]}>
            {findings.slice(0, 6).map((f) => (
              <Col key={f.id} xs={24} md={12} lg={8}>
                <Card size="small">
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <Typography.Text ellipsis style={{ maxWidth: '70%' }}>
                      {f.title}
                    </Typography.Text>
                    <Tag color={severityColor(f.severity)}>{severityLabel(f.severity)}</Tag>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>
    </div>
  );
}
