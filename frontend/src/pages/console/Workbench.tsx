// 用户工作台总览：项目概况、可用统计、最近通知。
// 所有指标均带统计范围说明；未接入的测试执行/报告/缺陷显示「未接入」而非 0。
// 本模块导出 ConsoleWorkbenchPage，由路由 /console 挂载，是控制台默认落地页。
import { Alert, Card, Col, List, Row, Statistic, Tag } from 'antd';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '@/api/dashboard';
import { notificationsApi } from '@/api/notifications';
import { useAuth } from '@/hooks/useAuth';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';

/**
 * 用户控制台工作台总览页组件。
 *
 * 用途：给出统计范围说明、核心指标卡（含「未接入」占位）、最近项目与最近通知。
 * 数据来源：dashboardApi.overview（指标与范围）、dashboardApi.projects（最近 5 个项目）、
 *       notificationsApi.list（最近 5 条通知）；均为只读请求，页面内没有任何写操作。
 * 「未接入」语义：后端对尚未接入的模块（测试执行/报告/缺陷）返回 hint === '未接入'，
 *       前端据此把数值显示为 '-' 并附 Tag，而不是把 0 当成真实统计值误导用户。
 * 403/404 行为：overview 失败（含无权限的错误信封）时整页换成可重试的 ErrorState；
 *       projects/notifications 两个卡片各自独立降级，不影响其他区块。
 * 空态：无可见项目 / 无通知时各自列表显示空态文案。
 */
export function ConsoleWorkbenchPage() {
  // 用于在范围说明里展示当前用户名
  const { user } = useAuth();
  // 概览接口：返回指标卡数组与统计范围描述，是整页的主数据源
  const overviewQuery = useQuery({
    queryKey: ['dashboard', 'overview'],
    queryFn: () => dashboardApi.overview(),
  });
  // 最近 5 个项目，固定取第一页、每页 5 条
  const projectsQuery = useQuery({
    queryKey: ['dashboard', 'projects', { page: 1, page_size: 5 }],
    queryFn: () => dashboardApi.projects({ page: 1, page_size: 5 }),
  });
  // 最近 5 条通知，固定取第一页、每页 5 条
  const notifQuery = useQuery({
    queryKey: ['notifications', { page: 1, page_size: 5 }],
    queryFn: () =>
      notificationsApi.list({ page: 1, page_size: 5 }),
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

  return (
    <PageContainer>
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        message={`统计范围：${
          overview.scope.is_platform_admin ? '平台管理员（可见全部）' : '当前用户可见资源'
        }`}
        description={`用户：${user?.username}（角色 ${overview.scope.role}）。指标按当前用户可见资源计算，切换组织/项目后会同步刷新。`}
      />
      <Row gutter={[16, 16]}>
        {overview.stats.map((card) => {
          // 关键判断：hint === '未接入' 说明该模块尚未对接数据源
          const notMigrated = card.hint === '未接入';
          return (
            <Col xs={12} sm={8} md={6} key={card.key}>
              <Card>
                <Statistic
                  title={card.label}
                  /* 未接入的模块不展示数字，也不展示 0（0 会被误读成真实统计值） */ value={notMigrated ? '-' : card.value}
                />
                <small style={{ color: '#999' }}>
                  {notMigrated ? (
                    <Tag>未接入</Tag>
                  ) : (
                    card.hint
                  )}
                </small>
              </Card>
            </Col>
          );
        })}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} md={14}>
          <Card
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
        <Col xs={24} md={10}>
          <Card
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
                        <small style={{ color: '#999' }}>{item.created_at}</small>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
