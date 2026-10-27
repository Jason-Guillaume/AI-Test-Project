// 平台管理端首页：平台基础统计 + 系统就绪状态。
import { Card, Col, Row, Statistic, Tag, Typography } from 'antd';
import {
  ApiOutlined,
  ApartmentOutlined,
  ArrowRightOutlined,
  CloudOutlined,
  ProjectOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '@/api/dashboard';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { PageHeader } from '@/components/PageHeader';

const PRIMARY_STAT_KEYS = new Set(['users', 'active_users', 'organizations', 'projects']);

const CHECK_LABELS: Record<string, string> = {
  database: '数据库',
  llm_configs: '模型配置',
  environments: '执行环境',
};

const CHECK_STATUS_LABELS: Record<string, string> = {
  up: '正常',
  degraded: '待处理',
  down: '异常',
  unknown: '未知',
};

const ADMIN_LINKS = [
  { to: '/admin/users', icon: <TeamOutlined />, title: '用户管理', description: '账号、角色与启用状态' },
  { to: '/admin/organizations', icon: <ApartmentOutlined />, title: '组织管理', description: '组织成员与模型授权' },
  { to: '/admin/projects', icon: <ProjectOutlined />, title: '项目管理', description: '全平台项目与成员关系' },
  { to: '/admin/model-configs', icon: <ApiOutlined />, title: '模型配置', description: '连接、安全与默认模型' },
  { to: '/admin/environments', icon: <CloudOutlined />, title: '环境配置', description: '执行环境与目标服务' },
];

function readinessStatus(status: string) {
  if (status === 'ready') return { label: '系统正常', color: 'green' as const };
  if (status === 'degraded') return { label: '部分配置待处理', color: 'orange' as const };
  if (status === 'not_ready') return { label: '系统不可用', color: 'red' as const };
  return { label: '状态未知', color: 'default' as const };
}

function checkStatus(status: string) {
  if (status === 'up') return { label: CHECK_STATUS_LABELS.up, color: 'green' as const };
  if (status === 'degraded') return { label: CHECK_STATUS_LABELS.degraded, color: 'orange' as const };
  if (status === 'down') return { label: CHECK_STATUS_LABELS.down, color: 'red' as const };
  return { label: CHECK_STATUS_LABELS.unknown, color: 'default' as const };
}

/**
 * 平台管理首页。
 * 主要统计与就绪检查沿用现有接口；页面不推算趋势，也不引入额外数据请求。
 */
export function AdminDashboardPage() {
  const platformQuery = useQuery({
    queryKey: ['dashboard', 'platform'],
    queryFn: () => dashboardApi.platform(),
  });
  const readyQuery = useQuery({
    queryKey: ['dashboard', 'ready'],
    queryFn: () => dashboardApi.ready(),
    refetchInterval: 60_000,
  });

  if (platformQuery.isPending) return <LoadingState />;
  if (platformQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={platformQuery.error} onRetry={platformQuery.refetch} />
      </PageContainer>
    );

  const stats = platformQuery.data.stats;
  const primaryStats = stats.filter((stat) => PRIMARY_STAT_KEYS.has(stat.key));
  const detailStats = stats.filter((stat) => !PRIMARY_STAT_KEYS.has(stat.key));
  const readiness = readyQuery.data ? readinessStatus(readyQuery.data.status) : null;

  return (
    <PageContainer>
      <PageHeader
        title="平台总览"
        subtitle="全局账号、组织资源与系统依赖状态"
        extra={<Tag color="blue">全平台统计</Tag>}
      />

      <Row gutter={[16, 16]} className="admin-primary-stats">
        {primaryStats.map((stat) => (
          <Col xs={12} sm={12} lg={6} key={stat.key}>
            <Card className="dashboard-stat-card admin-stat-card">
              <Statistic title={stat.label} value={stat.value} />
              <Typography.Text className="dashboard-stat-hint" type="secondary">
                {stat.hint}
              </Typography.Text>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} className="admin-dashboard-main-row">
        <Col xs={24} xl={15}>
          <Card
            className="dashboard-section-card admin-health-card"
            title={
              <div className="admin-card-heading">
                <span>系统就绪状态</span>
                <Typography.Text type="secondary">数据库、模型与执行环境</Typography.Text>
              </div>
            }
            extra={readiness && <Tag color={readiness.color}>{readiness.label}</Tag>}
          >
            {readyQuery.isPending && <LoadingState tip="检查系统依赖…" />}
            {readyQuery.isError && (
              <ErrorState error={readyQuery.error} onRetry={readyQuery.refetch} />
            )}
            {readyQuery.data && (
              <div className="admin-health-list">
                {readyQuery.data.checks.map((check) => {
                  const state = checkStatus(check.status);
                  return (
                    <div className="admin-health-item" key={check.name}>
                      <span className={`admin-health-dot admin-health-dot--${check.status}`} />
                      <span className="admin-health-copy">
                        <Typography.Text strong>
                          {CHECK_LABELS[check.name] ?? check.name}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          {check.detail || state.label}
                        </Typography.Text>
                      </span>
                      <Tag color={state.color}>{state.label}</Tag>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} xl={9}>
          <Card
            className="dashboard-section-card admin-links-card"
            title="平台管理入口"
            extra={<span className="dashboard-list-meta">高频治理操作</span>}
          >
            <div className="admin-link-list">
              {ADMIN_LINKS.map((item) => (
                <Link className="admin-link-item" to={item.to} key={item.to}>
                  <span className="admin-link-icon">{item.icon}</span>
                  <span className="admin-link-copy">
                    <Typography.Text strong>{item.title}</Typography.Text>
                    <Typography.Text type="secondary">{item.description}</Typography.Text>
                  </span>
                  <ArrowRightOutlined className="admin-link-arrow" />
                </Link>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      {detailStats.length > 0 && (
        <Card
          className="dashboard-section-card admin-detail-card"
          title="资源统计明细"
          extra={<Typography.Text type="secondary">按全平台接口统计</Typography.Text>}
        >
          <Row gutter={[16, 20]}>
            {detailStats.map((stat) => (
              <Col xs={12} sm={8} lg={4} key={stat.key}>
                <Statistic title={stat.label} value={stat.value} />
                <Typography.Text className="dashboard-stat-hint" type="secondary">
                  {stat.hint}
                </Typography.Text>
              </Col>
            ))}
          </Row>
        </Card>
      )}
    </PageContainer>
  );
}
