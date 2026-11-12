import { useState } from 'react';
import { Alert, App, Button, Checkbox, Form, Modal, Radio, Select, Space, Table, Tag } from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery } from '@tanstack/react-query';
import { collectPages, collectArrayPages } from '@/shared/api/pagination';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { projectsApi } from '@/features/projects/api/projects';
import { getErrorMessage } from '@/shared/api/client';
import { LoadingState } from '@/shared/ui/PageState';
import type { ApiInterface } from '@/features/api-catalog/contracts';
import type { Environment } from '@/features/environments/contracts';
import type { PlanPreviewItem, PlanPreviewResponse, SecurityStrategy } from '@/features/security-testing/contracts';
import type { TestCase } from '@/features/test-management/contracts';
import { expectationLabel, severityColor, severityLabel } from './constants';

/** 新建安全计划预览 + 确认弹窗。 */
export function PlanPreviewModal({
  projectId,
  onCancel,
  onConfirmed,
}: {
  projectId: number;
  onCancel: () => void;
  onConfirmed: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<{
    target_kind: 'api' | 'case';
    api_id?: number;
    baseline_case_id?: number;
    strategy_ids: number[];
    environment_id?: number;
  }>();

  // 接口 / 基线用例 / 策略 候选项。
  const apisQuery = useQuery({
    queryKey: ['security-preview', projectId, 'apis'],
    queryFn: () => collectPages((page) => apiCatalogApi.listApis(projectId, { page, page_size: 100 })),
  });
  const casesQuery = useQuery({
    queryKey: ['security-preview', projectId, 'baseline-cases'],
    queryFn: () => collectArrayPages((page) => testManagementApi.listCases(projectId, { page, page_size: 100 }), 100),
  });
  const strategiesQuery = useQuery({
    queryKey: ['security-preview', projectId, 'enabled-strategies'],
    queryFn: () => collectPages((page) => securityApi.listStrategies(projectId, { page, page_size: 100, enabled: true })),
  });
  const envsQuery = useQuery({
    queryKey: ['security-preview', projectId, 'envs'],
    queryFn: () => projectsApi.listEnvironments(projectId),
  });

  const apis: ApiInterface[] = apisQuery.data?.items ?? [];
  const baselineCases: TestCase[] = casesQuery.data ?? [];
  const strategies: SecurityStrategy[] = strategiesQuery.data?.items ?? [];
  const envs: Environment[] = (envsQuery.data?.items ?? []).filter((e) => e.id != null);

  const [preview, setPreview] = useState<PlanPreviewResponse | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());

  const previewMutation = useMutation({
    mutationFn: (body: Parameters<typeof securityApi.previewPlan>[1]) =>
      securityApi.previewPlan(projectId, body),
    onSuccess: (data) => {
      setPreview(data);
      // 缺省勾选所有未阻断项（blocked_reason 为空）。
      setAccepted(
        new Set(
          (data.items ?? [])
            .filter((i) => !i.blocked_reason)
            .map((i) => i.index),
        ),
      );
    },
    onError: (e) => message.error(getErrorMessage(e, '预览失败')),
  });

  const confirmMutation = useMutation({
    mutationFn: (planId: number) =>
      securityApi.confirmPlan(planId, { accepted_item_indexes: Array.from(accepted) }),
    onSuccess: (res) => {
      message.success(`已生成 ${res.created_count} 条安全用例${res.skipped_count ? `（跳过 ${res.skipped_count} 条）` : ''}`);
      onConfirmed();
    },
    onError: (e) => message.error(getErrorMessage(e, '确认失败')),
  });

  const handlePreview = async () => {
    const v = await form.validateFields();
    setPreview(null);
    setAccepted(new Set());
    previewMutation.mutate({
      api_id: v.target_kind === 'api' ? v.api_id : undefined,
      baseline_case_id: v.target_kind === 'case' ? v.baseline_case_id : undefined,
      strategy_ids: v.strategy_ids,
      environment_id: v.environment_id,
    });
  };

  const previewColumns: TableColumnsType<PlanPreviewItem> = [
    {
      title: '勾选',
      width: 60,
      render: (_, r) => (
        <Checkbox
          disabled={!!r.blocked_reason}
          checked={accepted.has(r.index)}
          onChange={(e) => {
            const next = new Set(accepted);
            if (e.target.checked) next.add(r.index);
            else next.delete(r.index);
            setAccepted(next);
          }}
        />
      ),
    },
    { title: '变异项', dataIndex: 'name' },
    { title: '类型', dataIndex: 'mutation_type', width: 160 },
    {
      title: '期望',
      dataIndex: 'expectation',
      width: 110,
      render: (v: string) => expectationLabel(v),
    },
    {
      title: '期望码',
      dataIndex: 'expected_status_codes',
      width: 90,
      render: (v: number[] | null) => (v && v.length ? v.join(',') : '-'),
    },
    {
      title: '严重级别',
      dataIndex: 'severity',
      width: 90,
      render: (v: string) => <Tag color={severityColor(v)}>{severityLabel(v)}</Tag>,
    },
    {
      title: '高风险',
      dataIndex: 'confirmation_required',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="orange">需确认</Tag> : '-'),
    },
  ];

  return (
    <Modal
      title="新建安全计划"
      open
      onCancel={onCancel}
      width={860}
      footer={
        preview ? (
          <Space>
            <Button onClick={onCancel}>取消</Button>
            <Button
              type="primary"
              disabled={accepted.size === 0}
              loading={confirmMutation.isPending}
              onClick={() => preview && confirmMutation.mutate(preview.plan_id)}
            >
              确认生成（{accepted.size}）
            </Button>
          </Space>
        ) : (
          <Space>
            <Button onClick={onCancel}>取消</Button>
            <Button
              type="primary"
              loading={previewMutation.isPending}
              onClick={handlePreview}
            >
              预览
            </Button>
          </Space>
        )
      }
    >
      {[apisQuery, casesQuery, strategiesQuery, envsQuery].some((query) => query.isError) && (
        <Alert type="error" showIcon message="候选数据加载失败" description="请关闭并重新打开窗口重试。" />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ target_kind: 'api', strategy_ids: [] }}
      >
        <Form.Item name="target_kind" label="目标类型">
          <Radio.Group>
            <Radio value="api">按接口</Radio>
            <Radio value="case">按基线用例</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item shouldUpdate noStyle>
          {({ getFieldValue }) =>
            getFieldValue('target_kind') === 'api' ? (
              <Form.Item
                name="api_id"
                label="接口"
                rules={[{ required: true, message: '请选择接口' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择接口"
                  options={apis.map((a) => ({ value: a.id, label: `${a.name} (${a.method} ${a.path})` }))}
                />
              </Form.Item>
            ) : (
              <Form.Item
                name="baseline_case_id"
                label="基线用例"
                rules={[{ required: true, message: '请选择基线用例' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择基线用例"
                  options={baselineCases.map((c) => ({ value: c.id, label: c.name }))}
                />
              </Form.Item>
            )
          }
        </Form.Item>
        <Form.Item
          name="strategy_ids"
          label="启用策略"
          rules={[{ required: true, message: '至少选择一个策略', type: 'array', min: 1 }]}
        >
          <Select
            mode="multiple"
            placeholder="勾选要应用的策略"
            options={strategies.map((s) => ({ value: s.id, label: `${s.name}（${s.category}）` }))}
          />
        </Form.Item>
        <Form.Item name="environment_id" label="执行环境（可选，预览时不发请求）">
          <Select
            allowClear
            placeholder="执行时再选也可"
            options={envs.map((e) => ({ value: e.id, label: e.display_name }))}
          />
        </Form.Item>
      </Form>

      {previewMutation.isPending && !preview && <LoadingState />}

      {preview && (
        <div style={{ marginTop: 8 }}>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 8 }}
            message={`预计 ${preview.estimated_count} 个变异项${preview.truncated ? '（已截断至 50）' : ''}${
              preview.baseline_case_name ? ` · 基线：${preview.baseline_case_name}` : ''
            }`}
          />
          <Table<PlanPreviewItem>
            rowKey="index"
            size="small"
            columns={previewColumns}
            dataSource={preview.items}
            pagination={false}
            scroll={{ x: 'max-content', y: 320 }}
            rowClassName={(r) => (r.blocked_reason ? 'security-blocked-row' : '')}
          />
          <style>{`.security-blocked-row { background: #fffbe6 }`}</style>
        </div>
      )}
    </Modal>
  );
}

