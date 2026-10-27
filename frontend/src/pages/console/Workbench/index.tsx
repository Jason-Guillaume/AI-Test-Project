// 用户工作台总览：核心指标、统计图表、项目与通知动态。
// 指标与趋势均来自当前用户可见范围内的真实业务数据。
// 本模块导出 ConsoleWorkbenchPage，由路由 /console 挂载，是控制台默认落地页。
import { Button, Card, Col, List, Row, Statistic, Typography } from 'antd';
import { ApiOutlined, ArrowRightOutlined, SafetyOutlined, ScheduleOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '@/api/dashboard';
import { notificationsApi } from '@/api/notifications';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { PageHeader } from '@/components/PageHeader';
import { DashboardCharts } from './DashboardCharts';
import { useConsoleScope } from '@/hooks/useConsoleScope';

const QUICK_LINKS = [
  { to: '/console/api-catalog', icon: <ApiOutlined />, title: '管理测试资产', description: '接口、业务流与用例统一维护' },
  { to: '/console/test-plans', icon: <ScheduleOutlined />, title: '安排测试计划', description: '组合套件并查看计划状态' },
  { to: '/console/security-testing', icon: <SafetyOutlined />, title: '查看安全测试', description: '管理扫描目标、策略与发现项' },
];

// 工作台优先展示测试项目的四项核心指标。
const WORKBENCH_STAT_KEYS = [
  'projects',
  'test_runs',
  'reports',
  'defects',
] as const;

/**
 * 用户控制台工作台总览页组件。
 *
 * 用途：展示核心指标、执行/缺陷/生成趋势、最近项目与最近通知。
 * 数据来源：工作台看板接口、dashboardApi.projects（最近 3 个项目）、
 *       notificationsApi.list（最近 3 条通知）；均为只读请求，页面内没有任何写操作。
 * 403/404 行为：overview 失败（含无权限的错误信封）时整页换成可重试的 ErrorState；
 *       projects/notifications 两个卡片各自独立降级，不影响其他区块。
 * 空态：无可见项目 / 无通知时各自列表显示空态文案。
 */
export function ConsoleWorkbenchPage() {
  const { currentOrgId, currentProjectId } = useConsoleScope();
  // 概览接口：返回工作台核心指标，是整页的主数据源。
  const overviewQuery = useQuery({
    queryKey: ['dashboard', 'overview'],
    queryFn: () => dashboardApi.overview(),
  });
  // 最近 3 个项目，固定取第一页、每页 3 条，与首页卡片可视容量一致。
  const projectsQuery = useQuery({
    queryKey: ['dashboard', 'projects', { page: 1, page_size: 3 }],
    queryFn: () => dashboardApi.projects({ page: 1, page_size: 3 }),
  });
  // 最近 3 条通知，固定取第一页、每页 3 条。
  const notifQuery = useQuery({
    queryKey: ['notifications', { page: 1, page_size: 3 }],
    queryFn: () =>
      notificationsApi.list({ page: 1, page_size: 3 }),
  });

  // 概览是主数据源：未就绪就整页转圈，避免半渲染的布局跳动
  if (overviewQuery.isPending) return <LoadingState />;
  // 概览失败（含无权限时后端返回的 403 错误信封）：整页可重试的 ErrorState
  if (overviewQuery.isError)
    return (
      <PageContainer>
        <ErrorState
          error={overviewQuery.error}
          onRetry={overviewQuery.refetch}
        />
      </PageContainer>
    );

  const overview = overviewQuery.data;
  const primaryStats = WORKBENCH_STAT_KEYS.map((key) =>
    overview.stats.find((card) => card.key === key),
  ).filter((card): card is (typeof overview.stats)[number] => card !== undefined);

  return (
    <PageContainer>
      <PageHeader
        title="工作台"
        subtitle="聚焦当前团队的测试资产、执行动态与待处理事项"
        extra={
          <Link to="/console/tasks">
            <Button type="primary">任务中心</Button>
          </Link>
        }
      />
      <Row gutter={[16, 16]}>
        {primaryStats.map((card) => (
          <Col xs={24} sm={12} lg={6} key={card.key}>
            <Card className="dashboard-stat-card">
              <Statistic title={card.label} value={card.value} />
              <small className="dashboard-stat-hint">{card.hint}</small>
            </Card>
          </Col>
        ))}
      </Row>

      <DashboardCharts organizationId={currentOrgId} projectId={currentProjectId} />

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={15}>
          <Card
            className="dashboard-section-card"
            title="最近项目"
            extra={<Link to="/console/projects">查看全部</Link>}
          >
            {projectsQuery.isPending ? (
              <LoadingState tip="加载项目…" />
            ) : projectsQuery.isError ? (
              <ErrorState
                error={projectsQuery.error}
                onRetry={projectsQuery.refetch}
              />
            ) : (
              <List
                dataSource={projectsQuery.data.items}
                locale={{ emptyText: '暂无可见项目' }}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Link to={`/console/projects/${item.id}`}>{item.name}</Link>
                      }
                      description={
                        <>
                          <span style={{ color: '#666' }}>
                            {item.organization_name ?? '无组织'}
                          </span>{' '}
                          · 角色：{item.my_role ?? '-'}
                        </>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
        <Col xs={24} md={9}>
          <Card
            className="dashboard-section-card"
            title="最近通知"
            extra={<Link to="/console/notifications">通知中心</Link>}
          >
            {notifQuery.isPending ? (
              <LoadingState tip="加载通知…" />
            ) : (
              <List
                dataSource={notifQuery.data?.items ?? []}
                locale={{ emptyText: '暂无通知' }}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={item.title}
                      description={
                      <small className="dashboard-list-meta">{item.created_at}</small>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
      <section className="dashboard-quick-start">
        <div className="dashboard-section-heading">
          <Typography.Title level={5}>快速开始</Typography.Title>
          <Typography.Text type="secondary">继续当前项目的测试流程</Typography.Text>
        </div>
        <Row gutter={[16, 16]}>
          {QUICK_LINKS.map((item) => (
            <Col xs={24} sm={8} key={item.to}>
              <Link className="quick-action-link" to={item.to}>
                <Card hoverable className="quick-action-card">
                  <span className="quick-action-icon">{item.icon}</span>
                  <span className="quick-action-copy">
                    <Typography.Text strong>{item.title}</Typography.Text>
                    <Typography.Text type="secondary">{item.description}</Typography.Text>
                  </span>
                  <ArrowRightOutlined className="quick-action-arrow" />
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      </section>
    </PageContainer>
  );
}
