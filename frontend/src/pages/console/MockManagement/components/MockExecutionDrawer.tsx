import { Alert, App, Button, Drawer, Flex, Popconfirm, Space, Tag, Typography } from 'antd';
import { ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getErrorMessage } from '@/shared/api/client';
import { mockManagementApi } from '@/features/mocking/api/mockManagement';
import { EmptyState, LoadingState } from '@/shared/ui/PageState';
import { fmtJson, statusCodeColor } from '../constants';

export /** 执行详情抽屉：展示已脱敏的请求 / 响应快照。 */
function MockExecutionDrawer({
  projectId,
  rowId,
  onClose,
  onFilter,
}: {
  projectId: number | null;
  rowId: number | null;
  onClose: () => void;
  onFilter: (contextId: string) => void;
}) {
  const { message: msg } = App.useApp();
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ['mock-execution', rowId],
    queryFn: () => mockManagementApi.getExecution(rowId!),
    enabled: rowId != null,
  });
  const row = detailQuery.data;
  const closeMutation = useMutation({
    mutationFn: (cid: string) => mockManagementApi.closeContext(cid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mock-contexts', projectId] });
      msg.success('作用域已关闭');
    },
    onError: (e) => msg.error(getErrorMessage(e, '关闭作用域失败')),
  });

  const block = (label: string, value: unknown) => (
    <div style={{ marginBottom: 12 }}>
      <Typography.Text strong style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <pre
        style={{
          margin: '4px 0 0',
          maxHeight: 260,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          fontSize: 12,
          background: 'var(--ant-color-fill-quaternary, rgba(0,0,0,0.04))',
          padding: 8,
          borderRadius: 4,
        }}
      >
        {fmtJson(value)}
      </pre>
    </div>
  );

  return (
    <Drawer
      title={row ? `调用记录 #${row.id} · ${row.method} ${row.path}` : '调用记录详情'}
      open={rowId != null}
      onClose={onClose}
      width={680}
    >
      {detailQuery.isLoading ? (
        <LoadingState />
      ) : row ? (
        <div>
          <Space wrap size="small" style={{ marginBottom: 12 }}>
            <Tag color="blue">{row.method}</Tag>
            <Tag color={statusCodeColor(row.response_status)}>{row.response_status ?? '-'}</Tag>
            <Tag color={row.matched ? 'green' : 'red'}>{row.matched ? '命中场景' : '未命中'}</Tag>
            {row.service_key ? <Tag color="geekblue">{row.service_key}</Tag> : null}
            {row.scenario_key ? <Tag color="purple">{row.scenario_key}</Tag> : null}
            {row.duration_ms != null ? <Tag>耗时 {row.duration_ms}ms</Tag> : null}
            {row.test_run_id ? <Tag color="geekblue">Run #{row.test_run_id}</Tag> : null}
            {row.error_code ? <Tag color="red">{row.error_code}</Tag> : null}
          </Space>

          {row.error_message && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message={`失败原因：${row.error_message}`}
            />
          )}

          {row.mock_context_id && (
            <Flex justify="space-between" align="center" style={{ marginBottom: 12 }}>
              <Typography.Text copyable={{ text: row.mock_context_id }} code style={{ fontSize: 12 }}>
                Context {row.mock_context_id}
              </Typography.Text>
              <Popconfirm title="关闭该作用域？" onConfirm={() => closeMutation.mutate(row.mock_context_id!)}>
                <Button size="small" icon={<StopOutlined />}>
                  关闭作用域
                </Button>
              </Popconfirm>
            </Flex>
          )}

          {row.request_id && (
            <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 12 }}>
              request_id：{row.request_id}
            </Typography.Text>
          )}

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            请求快照（Authorization、X-Api-Key、password、token 等敏感字段已脱敏）
          </Typography.Text>
          {block('查询参数', row.query_snapshot)}
          {block('请求头', row.header_snapshot)}
          {block('请求体', row.body_snapshot)}
          {block('响应头', row.response_header_snapshot)}
          {block('响应体', row.response_body_snapshot)}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={detailQuery.isFetching}
            style={{ marginTop: 4 }}
            onClick={() => detailQuery.refetch()}
          >
            刷新
          </Button>
          {row.mock_context_id && (
            <Button
              size="small"
              style={{ marginLeft: 8, marginTop: 4 }}
              onClick={() => {
                onFilter(row.mock_context_id!);
                onClose();
              }}
            >
              按此作用域筛选
            </Button>
          )}
        </div>
      ) : (
        <EmptyState description="调用记录不存在" />
      )}
    </Drawer>
  );
}

