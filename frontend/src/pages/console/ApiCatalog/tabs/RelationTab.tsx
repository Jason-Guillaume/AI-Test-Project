// 接口关联 Tab：维护当前接口参与的关联（前置条件 / 输出→输入 / 后续步骤）。
// 列表同时返回「当前接口是 source（发出）」与「当前接口是 target（被依赖）」两个方向，
// 故用「方向」列区分，「对端接口」按方向取另一侧名称；新增固定以当前接口为 source。
// 新增：选目标接口 + 关联类型 + 可选变量名/提取路径；删除：行内按钮。
import { useState } from 'react';
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import { ResourceTable } from '@/components/ResourceTable';
import { RELATION_TYPE_OPTIONS } from '../constants';
import type {
  ApiInterface,
  ApiInterfaceDetail,
  ApiRelation,
  ApiRelationCreate,
  RelationType,
} from '@/types';

const RELATION_LABEL: Record<RelationType, string> = {
  PRECONDITION: '前置条件',
  OUTPUT_INPUT: '输出→输入',
  FOLLOW_UP: '后续步骤',
};

interface FormValues {
  target_api_id: number;
  relation_type: RelationType;
  variable_name?: string;
  extract_path?: string;
}

/**
 * 接口关联 Tab。
 *
 * 查询：当前接口参与的关联列表（发出 + 被依赖两个方向）+ 项目内全部接口（page_size=200，供目标下拉）。
 * 新增/删除走 mutation，成功后失效 ['api-catalog']。
 */
export function RelationTab({
  api,
  projectId,
}: {
  api: ApiInterfaceDetail;
  projectId: number;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const listQuery = useQuery({
    queryKey: ['api-catalog', 'api', api.id, 'relations'],
    queryFn: () => apiCatalogApi.listRelations(api.id),
  });

  // 项目内全部接口，供目标接口下拉（排除自身）。
  const apisQuery = useQuery({
    queryKey: ['api-catalog', projectId, 'apis', { page: 1, page_size: 200 }],
    queryFn: () =>
      apiCatalogApi.listApis(projectId, { page: 1, page_size: 200 }),
  });

  const createMutation = useMutation({
    mutationFn: (body: ApiRelationCreate) =>
      apiCatalogApi.createRelation(api.id, body),
    onSuccess: () => {
      message.success('关联已添加');
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
      setOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const removeMutation = useMutation({
    mutationFn: (relationId: number) => apiCatalogApi.removeRelation(relationId),
    onSuccess: () => {
      message.success('关联已删除');
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const apiOptions = (apisQuery.data?.items ?? [])
    .filter((a: ApiInterface) => a.id !== api.id)
    .map((a: ApiInterface) => ({
      label: `${a.method} ${a.path} · ${a.name}`,
      value: a.id,
    }));

  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)
    return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const data = listQuery.data;
  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={() => { form.resetFields(); setOpen(true); }}>
          新增关联
        </Button>
      </Space>

      <ResourceTable<ApiRelation>
        rowKey={(r) => r.id}
        columns={[
          {
            title: '类型',
            dataIndex: 'relation_type',
            width: 130,
            render: (v: RelationType) => (
              <Tag color="blue">{RELATION_LABEL[v]}</Tag>
            ),
          },
          {
            title: '方向',
            key: 'direction',
            width: 90,
            render: (_: unknown, row: ApiRelation) =>
              row.source_api_id === api.id ? (
                <Tag>发出</Tag>
              ) : (
                <Tag color="purple">被依赖</Tag>
              ),
          },
          {
            title: '对端接口',
            render: (_: unknown, row: ApiRelation) => (
              <Typography.Text>
                {row.source_api_id === api.id
                  ? row.target_api_name ?? `#${row.target_api_id}`
                  : row.source_api_name ?? `#${row.source_api_id}`}
              </Typography.Text>
            ),
          },
          {
            title: '传递变量',
            dataIndex: 'variable_name',
            width: 150,
            render: (v: string | null) => v ?? '-',
          },
          {
            title: '提取路径',
            dataIndex: 'extract_path',
            width: 200,
            render: (v: string | null, row: ApiRelation) =>
              v ? (
                <Tooltip
                  title={
                    row.source_api_id === api.id
                      ? '从本接口（source）响应中提取'
                      : '从对端接口（target）响应中提取'
                  }
                >
                  <Typography.Text code>{v}</Typography.Text>
                </Tooltip>
              ) : (
                '-'
              ),
          },
          {
            title: '操作',
            key: 'actions',
            width: 80,
            render: (_: unknown, row: ApiRelation) => (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() =>
                  modal.confirm({
                    title: '删除该关联？',
                    okText: '删除',
                    okType: 'danger',
                    cancelText: '取消',
                    onOk: () => removeMutation.mutateAsync(row.id),
                  })
                }
              />
            ),
          },
        ]}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={{ page: 1, page_size: data.total || 10 }}
        onPaginationChange={() => undefined}
        emptyText="暂无关联"
      />

      <Modal
        title="新增关联"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={async () => {
          const values = await form.validateFields();
          await createMutation.mutateAsync({
            source_api_id: api.id,
            target_api_id: values.target_api_id,
            relation_type: values.relation_type,
            variable_name: values.variable_name || null,
            extract_path: values.extract_path || null,
          });
        }}
        confirmLoading={createMutation.isPending}
        okText="添加"
        cancelText="取消"
        destroyOnClose
      >
        <Form<FormValues> form={form} layout="vertical">
          <Form.Item
            name="target_api_id"
            label="目标接口"
            rules={[{ required: true, message: '请选择目标接口' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择项目内接口"
              options={apiOptions}
              loading={apisQuery.isPending}
              notFoundContent={
                apisQuery.isPending ? '加载中...' : '项目内暂无其他接口'
              }
            />
          </Form.Item>
          <Form.Item
            name="relation_type"
            label="关联类型"
            rules={[{ required: true, message: '请选择关联类型' }]}
          >
            <Select options={RELATION_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="variable_name" label="传递变量名" tooltip="如 token / id，用于后续用例串联">
            <Input maxLength={100} placeholder="token" />
          </Form.Item>
          <Form.Item name="extract_path" label="提取路径" tooltip="如 data.token / $.token">
            <Input maxLength={500} placeholder="data.token" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
