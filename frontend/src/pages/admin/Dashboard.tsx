// 平台管理端首页：平台基础统计 + 系统就绪状态。
import { Alert, Card, Col, Row, Statistic, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '@/api/dashboard';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';

/**
 * 平台管理首页组件。
 *
 * 用途：给平台管理员看全平台维度的核心统计与系统就绪状态。
 * 数据来源：dashboardApi.platform() 一次请求拉全部统计卡片；
 *       dashboardApi.ready() 独立请求且每分钟轮询一次，用于持续显示就绪检查项。
 * 是否发请求：是，两个 useQuery 分别独立请求。
 * 失败呈现：统计接口失败整页展示 ErrorState + 重试按钮；
 *       ready 接口失败只在就绪区块内展示错误，不阻断上方统计卡。
 * 空态：后端返回的 stats 数组直接渲染卡片；就绪数据未返回时不展示就绪卡。
 */
export function AdminDashboardPage() {
  // 平台基础统计：默认仅在挂载时请求一次，命中缓存不再重取
  const platformQuery = useQuery({
    queryKey: ['dashboard', 'platform'],
    queryFn: () => dashboardApi.platform(),
  });
  // 就绪检查：每 60 秒自动重取，用于持续反映数据库/缓存/模型配置的健康状态
  const readyQuery = useQuery({
    queryKey: ['dashboard', 'ready'],
    queryFn: () => dashboardApi.ready(),
    refetchInterval: 60_000, // 60s 轮询；命中缓存时也会强制重取
  });

  // 加载中：整页占位；就绪查询单独走自己的 pending 分支
  if (platformQuery.isPending) return <LoadingState />;
  // 统计接口失败：整页错误态，点击重试直接 refetch 原查询
  if (platformQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={platformQuery.error} onRetry={platformQuery.refetch} />
      </PageContainer>
    );

  const overview = platformQuery.data;
  const ready = readyQuery.data;

  return (
    <PageContainer>
      <Typography.Title level={4}>平台管理首页</Typography.Title>
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        message="统计口径：全平台"
        description="下方所有数字均为全平台范围，与个人控制台统计不同。"
      />
      <Row gutter={[16, 16]}>
        {overview.stats.map((card) => (
          <Col xs={12} sm={8} md={6} key={card.key}>
            <Card>
              <Statistic
                title={card.label}
                value={card.value}
                suffix={card.hint ? <small style={{ color: '#999' }}>{card.hint}</small> : undefined}
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Typography.Title level={5} style={{ marginTop: 24 }}>
        系统就绪状态
      </Typography.Title>
      {readyQuery.isPending && <LoadingState tip="检查就绪状态…" />}
      {readyQuery.isError && (
        <ErrorState error={readyQuery.error} onRetry={readyQuery.refetch} />
      )}
      {ready && (
        <Card>
          <p>
            总体状态：
            {/* 总体状态色阶：ready 绿、degraded 橙、其余兜底红，与后端枚举对齐 */}
            <Tag
              color={
                ready.status === 'ready'
                  ? 'green'
                  : ready.status === 'degraded'
                    ? 'orange'
                    : 'red'
              }
            >
              {ready.status}
            </Tag>
          </p>
          <Row gutter={[16, 8]}>
            {ready.checks.map((check) => (
              <Col key={check.name} xs={24} sm={12} md={8}>
                <div style={{ marginBottom: 8 }}>
                  <span style={{ color: '#666' }}>{check.name}：</span>
                  {/* 单项状态色阶：up 绿、degraded 橙、down 红，其余兜底 default */}
                  <Tag
                    color={
                      check.status === 'up'
                        ? 'green'
                        : check.status === 'degraded'
                          ? 'orange'
                          : check.status === 'down'
                            ? 'red'
                            : 'default'
                    }
                  >
                    {check.status}
                  </Tag>
                </div>
                {/* detail 可能为空；有值才渲染灰色说明文本 */}
                {check.detail && (
                  <small style={{ color: '#999' }}>{check.detail}</small>
                )}
              </Col>
            ))}
          </Row>
        </Card>
      )}
    </PageContainer>
  );
}
