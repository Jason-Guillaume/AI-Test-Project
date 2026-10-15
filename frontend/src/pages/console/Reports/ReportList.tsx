// 测试报告列表页：按项目分页列出正式测试报告，支持环境 / 风险等级 / 状态筛选。
//
// 数据：GET /projects/{project_id}/reports 返回分页信封 {items,total,page,page_size}。
// 权限（服务端为准）：读 = 项目可见（viewer+）；越权 404，前端不展示。
// 报告统计字段全部由后端代码计算，本页只展示，不做二次计算。
import { useMemo, useState } from 'react';
import { Button, Card, Col, Flex, Form, Progress, Select, Table, Tag, Typography } from 'antd';
import { EyeOutlined, ReloadOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import type { TableColumnsType } from 'antd';
import { reportsApi } from '@/api/reports';
import { environmentsApi } from '@/api/environments';
import { EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import {
  fmtTime,
  REPORT_RISK_OPTIONS,
  REPORT_STATUS_COLOR,
  REPORT_STATUS_OPTIONS,
  RISK_COLOR,
} from './constants';
import type { ReportRiskLevel, ReportStatus, TestReportListItem } from '@/types';

interface Filters {
  environment_id?: number;
  risk_level?: ReportRiskLevel;
  status?: ReportStatus;
}

/** 测试报告列表页。 */
export function ConsoleReportListPage() {
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();
  const [form] = Form.useForm<Filters>();
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const envsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: () => environmentsApi.list({ page: 1, page_size: 100 }),
    staleTime: 60_000,
  });
  const envs = envsQuery.data?.items ?? [];

  const reportsQuery = useQuery({
    queryKey: ['test-reports', currentProjectId, page, pageSize, filters],
    queryFn: () => reportsApi.list(currentProjectId!, { page, page_size: pageSize, ...filters }),
    enabled: currentProjectId != null,
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const rows: TestReportListItem[] = reportsQuery.data?.items ?? [];
  const total = reportsQuery.data?.total ?? 0;
  const currentPage = reportsQuery.data?.page ?? page;

  const columns: TableColumnsType<TestReportListItem> = useMemo(
    () => [
      { title: '报告编号', dataIndex: 'report_no', width: 170 },
      { title: '标题', dataIndex: 'title', ellipsis: true },
      {
        title: '风险',
        dataIndex: 'risk_level',
        width: 110,
        render: (v: ReportRiskLevel) => (
          <Tag color={RISK_COLOR[v] ?? 'default'}>
            {REPORT_RISK_OPTIONS.find((o) => o.value === v)?.label ?? v}
          </Tag>
        ),
      },
      {
        title: '通过率',
        dataIndex: 'pass_rate',
        width: 150,
        render: (v: number) => (
          <Progress
            percent={v}
            size="small"
            strokeColor={v >= 90 ? '#52c41a' : v >= 60 ? '#faad14' : '#ff4d4f'}
          />
        ),
      },
      {
        title: '总数',
        width: 130,
        render: (_, r) => (
          <span>
            <b>{r.total_cases}</b>
            <span style={{ color: '#999', fontSize: 12, marginLeft: 6 }}>
              通过 {r.passed_cases} / 失败 {r.failed_cases} / 错误 {r.error_cases}
            </span>
          </span>
        ),
      },
      {
        title: '耗时',
        dataIndex: 'duration_ms',
        width: 100,
        align: 'right',
        render: (v: number | null) => (v == null ? '-' : `${(v / 1000).toFixed(2)} s`),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 120,
        render: (v: ReportStatus) => (
          <Tag color={REPORT_STATUS_COLOR[v] ?? 'default'}>
            {REPORT_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v}
          </Tag>
        ),
      },
      { title: '生成时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtTime(v) },
      {
        title: '操作',
        width: 110,
        fixed: 'right',
        render: (_, row) => (
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/console/test-reports/${row.id}`)}
          >
            查看详情
          </Button>
        ),
      },
    ],
    [navigate],
  );

  return (
    <PageContainer>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          测试报告
        </Typography.Title>
        <Typography.Text type="secondary">
          报告由测试执行结果自动生成；统计数据不可变，AI 仅负责总结与风险解释。
        </Typography.Text>
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="inline"
          initialValues={filters}
          onFinish={(values) => {
            setFilters(values);
            setPage(1);
          }}
        >
          <Col>
            <Form.Item name="environment_id" label="环境">
              <Select
                allowClear
                placeholder="全部环境"
                style={{ width: 170 }}
                options={envs.map((e) => ({
                  label: e.display_name || e.name,
                  value: e.id as number,
                }))}
              />
            </Form.Item>
          </Col>
          <Col>
            <Form.Item name="risk_level" label="风险等级">
              <Select
                allowClear
                placeholder="全部风险"
                style={{ width: 150 }}
                options={REPORT_RISK_OPTIONS}
              />
            </Form.Item>
          </Col>
          <Col>
            <Form.Item name="status" label="状态">
              <Select
                allowClear
                placeholder="全部状态"
                style={{ width: 150 }}
                options={REPORT_STATUS_OPTIONS}
              />
            </Form.Item>
          </Col>
          <Col>
            <Form.Item>
              <Flex gap="small">
                <Button type="primary" htmlType="submit" loading={reportsQuery.isFetching}>
                  筛选
                </Button>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={() => {
                    form.resetFields();
                    setFilters({});
                    setPage(1);
                  }}
                >
                  重置
                </Button>
              </Flex>
            </Form.Item>
          </Col>
        </Form>
      </Card>

      {reportsQuery.isLoading ? (
        <LoadingState />
      ) : rows.length === 0 ? (
        <EmptyState description="暂无测试报告，可先在「执行历史」中执行测试用例生成报告" />
      ) : (
        <Table<TestReportListItem>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1120 }}
          pagination={{
            current: currentPage,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            pageSizeOptions: [10, 20, 50],
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      )}
    </PageContainer>
  );
}
