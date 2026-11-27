// 项目缺陷设置抽屉：队列灰度开关、积压提醒与缺陷模板（草稿→预览→发布，按版本生效于本项目新建缺陷）。
// 权限：editor+ 才能保存；不含任何人员指派字段。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Button, Drawer, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag, Typography,
} from 'antd';
import { useEffect, useState } from 'react';
import { bugsApi } from '@/features/defects/api/defects';
import type { DefectTemplateConfig, DefectTemplatePreview } from '@/features/defects/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { App } from 'antd';
import { CATEGORY_OPTIONS, PRIORITY_OPTIONS, SEVERITY_OPTIONS } from './constants';

const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  category: '前后端划分',
  description: '描述',
  expected_result: '预期结果',
  actual_result: '实际结果',
  severity: '严重度',
  priority: '优先级',
  steps_to_reproduce: '复现步骤',
  environment: '环境',
  affected_version: '影响版本',
  api_method: '请求方法',
  api_url: '请求地址',
  api_request_headers: '请求头',
  api_request_body: '请求体',
  api_response: '实际响应',
};
const FIELD_OPTIONS = Object.entries(FIELD_LABELS).map(([value, label]) => ({ value, label }));
const TEMPLATE_STATUS_LABEL: Record<string, string> = { draft: '草稿', published: '已发布', retired: '已退役' };
const TEMPLATE_STATUS_COLOR: Record<string, string> = { draft: 'orange', published: 'green', retired: 'default' };

const EMPTY_CONFIG: DefectTemplateConfig = {
  hidden_fields: [],
  defaults: {},
  required_on_create: [],
  required_on_confirm: [],
  required_on_regression: [],
};

/**
 * 项目缺陷设置抽屉：保存灰度开关与提醒配置（editor+），管理模板草稿并预览、发布。
 * 会发请求：['defect-project-setting'] / ['defect-templates'] / 预览 / 建草稿 / 发布；
 * 发布成功后失效模板缓存，使新建表单立即取到新版本。失败用 message.error 呈现。
 */
export function DefectSettingsDrawer({
  projectId, projectName, canEdit, onClose,
}: {
  projectId: number;
  projectName?: string;
  canEdit: boolean;
  onClose: () => void;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [settingForm] = Form.useForm();
  const [templateForm] = Form.useForm();
  const [preview, setPreview] = useState<DefectTemplatePreview | null>(null);

  const settingQuery = useQuery({
    queryKey: ['defect-project-setting', projectId],
    queryFn: () => bugsApi.projectSetting(projectId),
  });
  const templatesQuery = useQuery({
    queryKey: ['defect-templates', projectId],
    queryFn: () => bugsApi.templates(projectId),
  });

  useEffect(() => {
    if (settingQuery.data) settingForm.setFieldsValue(settingQuery.data);
  }, [settingQuery.data, settingForm]);

  const refreshTemplates = () => {
    queryClient.invalidateQueries({ queryKey: ['defect-templates', projectId] });
  };

  const saveSetting = useMutation({
    mutationFn: (values: { queue_enabled: boolean; reminder_enabled: boolean; stale_reminder_days: number }) =>
      bugsApi.updateProjectSetting(projectId, values),
    onSuccess: () => {
      message.success('项目缺陷设置已保存');
      queryClient.invalidateQueries({ queryKey: ['defect-project-setting', projectId] });
      queryClient.invalidateQueries({ queryKey: ['defect-queues'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '保存失败')),
  });

  const buildConfig = (): DefectTemplateConfig => {
    const values = templateForm.getFieldsValue();
    const defaults: Record<string, unknown> = {};
    for (const [field, value] of Object.entries(values.defaults ?? {})) {
      if (value !== undefined && value !== null && value !== '') defaults[field] = value;
    }
    return {
      hidden_fields: values.hidden_fields ?? [],
      defaults,
      required_on_create: values.required_on_create ?? [],
      required_on_confirm: values.required_on_confirm ?? [],
      required_on_regression: values.required_on_regression ?? [],
    };
  };

  const previewMutation = useMutation({
    mutationFn: () => bugsApi.previewTemplate(buildConfig()),
    onSuccess: (data) => setPreview(data),
    onError: (error) => message.error(getErrorMessage(error, '预览失败')),
  });
  const createDraft = useMutation({
    mutationFn: () => bugsApi.createTemplate(projectId, buildConfig()),
    onSuccess: () => { message.success('模板草稿已保存，发布后对本项目新建缺陷生效'); refreshTemplates(); },
    onError: (error) => message.error(getErrorMessage(error, '保存草稿失败')),
  });
  const publish = useMutation({
    mutationFn: (templateId: number) => bugsApi.publishTemplate(templateId),
    onSuccess: () => {
      message.success('模板已发布，旧版本自动退役');
      refreshTemplates();
      queryClient.invalidateQueries({ queryKey: ['defect-templates', projectId] });
    },
    onError: (error) => message.error(getErrorMessage(error, '发布失败')),
  });

  return (
    <Drawer
      open
      width={720}
      title={`缺陷设置：${projectName ?? `项目 #${projectId}`}`}
      onClose={onClose}
      destroyOnHidden
    >
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {!canEdit && <Alert type="info" showIcon message="仅 editor 及以上角色可修改项目缺陷设置与模板。" />}
        <div>
          <Typography.Title level={5}>队列与提醒</Typography.Title>
          <Form form={settingForm} layout="vertical" disabled={!canEdit}>
            <Form.Item
              name="queue_enabled"
              label="启用状态队列工作台（灰度开关）"
              valuePropName="checked"
              extra="关闭后本项目退回普通列表视图；处理人字段已全面停用，不受此开关影响。"
            >
              <Switch />
            </Form.Item>
            <Form.Item name="reminder_enabled" label="积压提醒（每日汇总站内信）" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="stale_reminder_days" label="积压判定天数" rules={[{ required: true, message: '请填写天数' }]}>
              <InputNumber min={1} max={90} style={{ width: 160 }} />
            </Form.Item>
            {canEdit && (
              <Button
                type="primary"
                loading={saveSetting.isPending}
                onClick={async () => {
                  const values = await settingForm.validateFields();
                  saveSetting.mutate(values);
                }}
              >保存设置</Button>
            )}
          </Form>
        </div>

        <div>
          <Typography.Title level={5}>模板版本</Typography.Title>
          <Table
            rowKey="id"
            size="small"
            pagination={false}
            loading={templatesQuery.isLoading}
            dataSource={templatesQuery.data ?? []}
            columns={[
              { title: '版本', dataIndex: 'version', width: 70, render: (value: number) => `v${value}` },
              {
                title: '状态', dataIndex: 'status', width: 90,
                render: (value: string) => <Tag color={TEMPLATE_STATUS_COLOR[value]}>{TEMPLATE_STATUS_LABEL[value]}</Tag>,
              },
              { title: '创建人', dataIndex: 'created_by_username', render: (value: string | null) => value ?? '-' },
              { title: '发布时间', dataIndex: 'published_at', render: (value: string | null) => value ? new Date(value).toLocaleString() : '-' },
              {
                title: '操作', width: 140,
                render: (_, row) => (
                  <Space>
                    <Button size="small" onClick={() => {
                      templateForm.setFieldsValue({
                        hidden_fields: row.config.hidden_fields,
                        defaults: row.config.defaults,
                        required_on_create: row.config.required_on_create,
                        required_on_confirm: row.config.required_on_confirm,
                        required_on_regression: row.config.required_on_regression,
                      });
                      message.info(`已载入 v${row.version} 配置，可修改后另存草稿`);
                    }}>载入</Button>
                    {row.status === 'draft' && canEdit && (
                      <Button size="small" type="primary" onClick={() => modal.confirm({
                        title: `发布模板 v${row.version}？`,
                        content: '发布后立即对本项目新建缺陷生效，当前已发布版本自动退役；存量缺陷不受影响。',
                        onOk: () => publish.mutateAsync(row.id),
                      })}>发布</Button>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </div>

        <div>
          <Typography.Title level={5}>编辑模板草稿</Typography.Title>
          <Typography.Paragraph type="secondary">
            模板只控制事实字段的显隐、默认值与分阶段必填，不包含人员指派。发布后仅作用于本项目新建缺陷。
          </Typography.Paragraph>
          <Form form={templateForm} layout="vertical" disabled={!canEdit} initialValues={EMPTY_CONFIG}>
            <Form.Item name="hidden_fields" label="隐藏字段">
              <Select mode="multiple" options={FIELD_OPTIONS} placeholder="选择本项目提单时不展示的字段" allowClear />
            </Form.Item>
            <Space wrap>
              <Form.Item name={['defaults', 'category']} label="默认划分">
                <Select options={CATEGORY_OPTIONS} allowClear style={{ width: 130 }} placeholder="不设置" />
              </Form.Item>
              <Form.Item name={['defaults', 'severity']} label="默认严重度">
                <Select options={SEVERITY_OPTIONS} allowClear style={{ width: 130 }} placeholder="不设置" />
              </Form.Item>
              <Form.Item name={['defaults', 'priority']} label="默认优先级">
                <Select options={PRIORITY_OPTIONS} allowClear style={{ width: 130 }} placeholder="不设置" />
              </Form.Item>
              <Form.Item name={['defaults', 'environment']} label="默认环境">
                <Input style={{ width: 130 }} placeholder="不设置" />
              </Form.Item>
              <Form.Item name={['defaults', 'affected_version']} label="默认影响版本">
                <Input style={{ width: 140 }} placeholder="不设置" />
              </Form.Item>
            </Space>
            <Form.Item name="required_on_create" label="提交时必填" extra="保存草稿不校验；提交进入待确认队列时校验。">
              <Select mode="multiple" options={FIELD_OPTIONS} placeholder="选择提交前必须填写的字段" allowClear />
            </Form.Item>
            <Form.Item name="required_on_confirm" label="确认时必填">
              <Select mode="multiple" options={FIELD_OPTIONS} placeholder="确认问题前必须补齐的字段" allowClear />
            </Form.Item>
            <Form.Item name="required_on_regression" label="登记可回归时必填">
              <Select mode="multiple" options={FIELD_OPTIONS} placeholder="登记可回归前必须补齐的字段" allowClear />
            </Form.Item>
            {canEdit && (
              <Space>
                <Button loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>预览效果</Button>
                <Button type="primary" loading={createDraft.isPending} onClick={() => createDraft.mutate()}>保存草稿</Button>
              </Space>
            )}
          </Form>
        </div>
      </Space>
      <Modal open={preview != null} title="模板预览（示例填充后）" footer={null} onCancel={() => setPreview(null)} width={640}>
        {preview && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text type="secondary">隐藏字段：{preview.hidden_fields.map((f) => FIELD_LABELS[f] ?? f).join('、') || '无'}</Typography.Text>
            <Typography.Text type="secondary">提交必填：{preview.required_on_create.map((f) => FIELD_LABELS[f] ?? f).join('、') || '无'}</Typography.Text>
            <Typography.Text type="secondary">确认必填：{preview.required_on_confirm.map((f) => FIELD_LABELS[f] ?? f).join('、') || '无'}</Typography.Text>
            <Typography.Text type="secondary">登记可回归必填：{preview.required_on_regression.map((f) => FIELD_LABELS[f] ?? f).join('、') || '无'}</Typography.Text>
            <pre className="bug-api-pre">{JSON.stringify(preview.sample, null, 2)}</pre>
          </Space>
        )}
      </Modal>
    </Drawer>
  );
}