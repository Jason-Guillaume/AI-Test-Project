// 禅道式缺陷提交/编辑弹窗。
// 主列：标题 → 复现步骤 → 实际结果 → 预期结果；侧栏：归属/环境/影响版本/严重度/优先级。
// 新建支持保存草稿、提交、提交并继续（仅继承项目/归属/环境/影响版本）；
// 携带 request_key 幂等键，超时重试不会重复建单；附件部分失败只重试失败文件。
// 编辑只改事实字段，携带 expected_version 做乐观并发；状态变更走队列动作。
import { InboxOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, App, Button, Col, Form, Input, Modal, Radio, Row, Select, Typography, Upload,
} from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { bugsApi } from '@/features/defects/api/defects';
import type { ApiMethod, Bug, BugCategory, BugPriority, BugSeverity, DefectTemplateConfig } from '@/features/defects/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { API_METHOD_OPTIONS, CATEGORY_OPTIONS, PRIORITY_OPTIONS, SEVERITY_OPTIONS } from './constants';

interface DefectFormValues {
  project_id?: number;
  title: string;
  category?: BugCategory;
  description?: string;
  expected_result?: string;
  actual_result?: string;
  api_method?: ApiMethod;
  api_url?: string;
  api_request_headers?: string;
  api_request_body?: string;
  api_response?: string;
  severity?: BugSeverity;
  priority?: BugPriority;
  steps_to_reproduce?: string;
  environment?: string;
  affected_version?: string;
}

const newRequestKey = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? `bug-${crypto.randomUUID()}`
    : `bug-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;

/**
 * 禅道式新建/编辑缺陷弹窗：主列标题→复现步骤→实际→预期，侧栏划分/环境/版本/严重度/优先级。
 * 会发请求：编辑拉 ['bug-detail']，新建拉已发布模板；提交走 create/update（带 request_key 幂等）。
 * 附件部分失败保留待重试文件；「提交并继续」只继承项目/划分/环境/影响版本。
 */
export function DefectFormModal({
  mode, bugId, initialProjectId, initialCategory, projectOptions, onClose, onSaved,
}: {
  mode: 'create' | 'edit';
  bugId?: number;
  initialProjectId?: number;
  initialCategory?: BugCategory;
  projectOptions: { label: string; value: number }[];
  onClose: () => void;
  onSaved: (bug: Bug, continueCreating: boolean) => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<DefectFormValues>();
  const [files, setFiles] = useState<File[]>([]);
  const [createdPendingUpload, setCreatedPendingUpload] = useState<Bug | null>(null);
  const [uploadPending, setUploadPending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const requestKey = useRef<{ signature: string; key: string } | null>(null);

  const detailQuery = useQuery({
    queryKey: ['bug-detail', bugId],
    queryFn: () => bugsApi.get(bugId!),
    enabled: mode === 'edit' && bugId != null,
  });
  const bug = detailQuery.data;

  const watchedProjectId = Form.useWatch('project_id', form);
  const projectId = mode === 'edit' ? bug?.project_id : (watchedProjectId ?? initialProjectId);
  const selectedCategory = Form.useWatch('category', form);

  // 已发布模板：默认值、字段显隐与创建必填（不含人员指派）。
  const templatesQuery = useQuery({
    queryKey: ['defect-templates', projectId],
    queryFn: () => bugsApi.templates(projectId!),
    enabled: projectId != null,
  });
  const template: DefectTemplateConfig | null = useMemo(() => {
    const published = (templatesQuery.data ?? []).find((item) => item.status === 'published');
    return published?.config ?? null;
  }, [templatesQuery.data]);
  const hidden = (field: string) => template?.hidden_fields.includes(field) ?? false;
  const requiredOnCreate = (field: string) =>
    mode === 'create' && (template?.required_on_create.includes(field) ?? false);

  const initialValues = useMemo<Partial<DefectFormValues>>(() => {
    if (mode === 'edit') {
      if (!bug) return {};
      return {
        title: bug.title,
        category: bug.category ?? undefined,
        description: bug.description ?? undefined,
        expected_result: bug.expected_result ?? undefined,
        actual_result: bug.actual_result ?? undefined,
        api_method: bug.api_method ?? undefined,
        api_url: bug.api_url ?? undefined,
        api_request_headers: bug.api_request_headers ?? undefined,
        api_request_body: bug.api_request_body ?? undefined,
        api_response: bug.api_response ?? undefined,
        severity: bug.severity,
        priority: bug.priority,
        steps_to_reproduce: bug.steps_to_reproduce ?? undefined,
        environment: bug.environment ?? undefined,
        affected_version: bug.affected_version ?? undefined,
      };
    }
    const defaults = (template?.defaults ?? {}) as Record<string, unknown>;
    return {
      project_id: initialProjectId ?? projectOptions[0]?.value,
      category: initialCategory ?? (defaults.category as BugCategory | undefined),
      severity: (defaults.severity as BugSeverity | undefined) ?? 2,
      priority: (defaults.priority as BugPriority | undefined) ?? 2,
      environment: (defaults.environment as string | undefined),
      affected_version: (defaults.affected_version as string | undefined),
    };
  }, [mode, bug, template, initialProjectId, initialCategory, projectOptions]);

  const saveMutation = useMutation({
    mutationFn: async ({ asDraft }: { asDraft: boolean }) => {
      const values = await form.validateFields();
      const isApiBug = values.category === '接口';
      const payload = {
        title: values.title,
        category: values.category,
        description: values.description,
        expected_result: values.expected_result ?? null,
        actual_result: values.actual_result ?? null,
        api_method: isApiBug ? (values.api_method ?? null) : null,
        api_url: isApiBug ? (values.api_url ?? null) : null,
        api_request_headers: isApiBug ? (values.api_request_headers ?? null) : null,
        api_request_body: isApiBug ? (values.api_request_body ?? null) : null,
        api_response: isApiBug ? (values.api_response ?? null) : null,
        severity: values.severity,
        priority: values.priority,
        steps_to_reproduce: values.steps_to_reproduce,
        environment: values.environment,
        affected_version: values.affected_version,
      };
      if (mode === 'edit') {
        return bugsApi.update(bug!.id, { ...payload, expected_version: bug!.record_version });
      }
      const bodyWithoutKey = { ...payload, project_id: values.project_id!, is_draft: asDraft };
      const signature = JSON.stringify(bodyWithoutKey);
      if (!requestKey.current || requestKey.current.signature !== signature) {
        requestKey.current = { signature, key: newRequestKey() };
      }
      if (createdPendingUpload) return createdPendingUpload;
      return bugsApi.create({ ...bodyWithoutKey, request_key: requestKey.current.key });
    },
    onSuccess: async (saved, { asDraft }) => {
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      queryClient.invalidateQueries({ queryKey: ['bug-detail'] });
      queryClient.invalidateQueries({ queryKey: ['defect-queues'] });
      if (mode === 'edit') {
        message.success('缺陷已更新');
        onSaved(saved, false);
        return;
      }
      if (!createdPendingUpload) setCreatedPendingUpload(saved);
      if (files.length) {
        setUploadPending(true);
        const results = await Promise.allSettled(files.map((file) => bugsApi.uploadAttachment(saved.id, file)));
        const failedFiles = files.filter((_file, index) => results[index]?.status === 'rejected');
        setUploadPending(false);
        setFiles(failedFiles);
        if (failedFiles.length) {
          message.warning(`缺陷 #${saved.id} 已创建，${failedFiles.length} 个附件未上传；再次保存可重试`);
          return;
        }
      }
      setFiles([]);
      setCreatedPendingUpload(null);
      requestKey.current = null;
      message.success(asDraft ? '草稿已保存，可在「我的草稿」中继续提交' : '缺陷已提交，进入待确认队列');
      handleSaved(saved);
    },
    onError: (error) => setSubmitError(getErrorMessage(error, '保存失败')),
  });

  const [continueNext, setContinueNext] = useState(false);
  const submit = (asDraft: boolean, keepCreating = false) => {
    setSubmitError(null);
    setContinueNext(keepCreating);
    saveMutation.mutate({ asDraft });
  };

  // 「提交并继续」：仅继承项目/归属/环境/影响版本，清空其余内容字段。
  const handleSaved = (saved: Bug) => {
    if (continueNext && mode === 'create') {
      const keep = form.getFieldsValue(['project_id', 'category', 'environment', 'affected_version']);
      form.resetFields();
      form.setFieldsValue(keep);
      setContinueNext(false);
      message.success(`缺陷 #${saved.id} 已提交，可继续录入下一条`);
    } else {
      onSaved(saved, false);
    }
  };

  // 模板异步加载后，把默认值补进尚未填写的字段。
  useEffect(() => {
    if (mode !== 'create' || !template) return;
    const defaults = template.defaults ?? {};
    const patch: Record<string, unknown> = {};
    for (const field of ['category', 'environment', 'affected_version', 'severity', 'priority'] as const) {
      const current = form.getFieldValue(field);
      if ((current == null || current === '') && defaults[field] != null) patch[field] = defaults[field];
    }
    if (Object.keys(patch).length) form.setFieldsValue(patch);
  }, [mode, template, form]);

  const busy = saveMutation.isPending || uploadPending;
  // 只按缺陷 ID 固定表单实例：后台详情刷新导致 record_version 变化时不重挂，
  // 避免把用户尚未提交的编辑内容（含冲突说明）清空。
  const formKey = mode === 'edit' ? `edit-${bug?.id}` : 'create';
  const requiredRule = (field: string, label: string) =>
    requiredOnCreate(field) ? [{ required: true, whitespace: true, message: `项目模板要求填写${label}` }] : [];

  return (
    <Modal
      open
      title={mode === 'edit' ? `编辑缺陷 #${bugId}` : '新建缺陷'}
      width={860}
      onCancel={() => { if (!busy) onClose(); }}
      destroyOnHidden
      footer={mode === 'edit' ? [
        <Button key="cancel" onClick={onClose} disabled={busy}>取消</Button>,
        <Button key="save" type="primary" loading={busy} onClick={() => submit(false)}>保存</Button>,
      ] : [
        <Button key="cancel" onClick={onClose} disabled={busy}>取消</Button>,
        <Button key="draft" loading={busy} onClick={() => submit(true)}>保存草稿</Button>,
        <Button key="continue" loading={busy} onClick={() => submit(false, true)}>提交并继续</Button>,
        <Button key="submit" type="primary" loading={busy} onClick={() => submit(false)}>提交</Button>,
      ]}
    >
      {mode === 'edit' && detailQuery.isPending ? <Typography.Text type="secondary">正在加载缺陷详情…</Typography.Text> : (
        <Form<DefectFormValues>
          form={form}
          layout="vertical"
          initialValues={initialValues}
          key={formKey}
        >
          {submitError && <Alert style={{ marginBottom: 12 }} type="error" showIcon message={submitError} />}
          {createdPendingUpload && files.length > 0 && (
            <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={`缺陷 #${createdPendingUpload.id} 已创建，保存会重试 ${files.length} 个失败附件`} />
          )}
          <Row gutter={16}>
            <Col xs={24} md={16}>
              <Form.Item name="title" label="缺陷标题" rules={[{ required: true, whitespace: true, message: '请输入缺陷标题' }]}>
                <Input placeholder="一句话描述问题" maxLength={200} />
              </Form.Item>
              {!hidden('steps_to_reproduce') && (
                <Form.Item name="steps_to_reproduce" label="复现步骤" rules={requiredRule('steps_to_reproduce', '复现步骤')} tooltip="多行文本，编号或换行均可">
                  <Input.TextArea rows={4} placeholder={'1. 打开登录页\n2. 输入错误密码\n3. 点击登录'} />
                </Form.Item>
              )}
              {!hidden('actual_result') && (
                <Form.Item name="actual_result" label="实际结果" rules={requiredRule('actual_result', '实际结果')}>
                  <Input.TextArea rows={3} placeholder="填写实际表现" maxLength={4000} />
                </Form.Item>
              )}
              {!hidden('expected_result') && (
                <Form.Item name="expected_result" label="预期结果" rules={requiredRule('expected_result', '预期结果')}>
                  <Input.TextArea rows={3} placeholder="填写预期表现" maxLength={4000} />
                </Form.Item>
              )}
              {!hidden('description') && (
                <Form.Item name="description" label="补充描述">
                  <Input.TextArea rows={2} placeholder="其他需要说明的信息" maxLength={1000} />
                </Form.Item>
              )}
              {selectedCategory === '接口' && (
                <>
                  <Typography.Title level={5} style={{ marginTop: 8, marginBottom: 8 }}>接口信息</Typography.Title>
                  <div className="form-field-row">
                    <Form.Item name="api_method" label="请求方法" style={{ width: 160, flex: 'none', margin: 0 }}>
                      <Select placeholder="GET" options={API_METHOD_OPTIONS} allowClear />
                    </Form.Item>
                    <Form.Item name="api_url" label="请求地址" style={{ flex: 1, margin: 0 }}>
                      <Input placeholder="如 https://api.example.com/v1/orders 或 /v1/orders" maxLength={500} />
                    </Form.Item>
                  </div>
                  {!hidden('api_request_headers') && (
                    <Form.Item name="api_request_headers" label="请求头" tooltip="JSON 或原始文本；请勿填写真实密钥，敏感值请脱敏">
                      <Input.TextArea rows={2} placeholder={'{"Authorization": "Bearer ***", "Content-Type": "application/json"}'} maxLength={2000} />
                    </Form.Item>
                  )}
                  {!hidden('api_request_body') && (
                    <Form.Item name="api_request_body" label="请求体">
                      <Input.TextArea rows={3} placeholder='{"order_no": "SO-12345"}' maxLength={5000} />
                    </Form.Item>
                  )}
                  <Form.Item name="api_response" label="实际响应" tooltip="接口返回的错误响应或异常报文；请脱敏后填写">
                    <Input.TextArea rows={3} placeholder='{"code": 500, "message": "internal error"}' maxLength={5000} />
                  </Form.Item>
                </>
              )}
              {mode === 'create' && (
                <Form.Item label="附件" extra="每个文件不超过 10 MB；保存时上传，失败文件可再次保存重试">
                  <Upload.Dragger
                    disabled={uploadPending}
                    multiple
                    beforeUpload={(file) => {
                      if (!file.size || file.size > 10 * 1024 * 1024) {
                        message.error('附件不能为空且不能超过 10 MB');
                        return Upload.LIST_IGNORE;
                      }
                      setFiles((previous) => [...previous, file]);
                      return false;
                    }}
                    onRemove={(file) => { setFiles((previous) => previous.filter((item) => item !== file.originFileObj)); }}
                  >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p className="ant-upload-text">点击或拖拽文件到此处</p>
                    <p className="ant-upload-hint">支持同时选择多个文件</p>
                  </Upload.Dragger>
                </Form.Item>
              )}
            </Col>
            <Col xs={24} md={8}>
              {mode === 'create' && (
                <Form.Item name="project_id" label="所属项目" rules={[{ required: true, message: '请选择所属项目' }]}>
                  <Select showSearch optionFilterProp="label" options={projectOptions} placeholder="请选择所属项目" />
                </Form.Item>
              )}
              {!hidden('category') && (
                <Form.Item name="category" label="前后端划分" tooltip="可暂不选择，待确认时补齐；接口缺陷展开请求详情">
                  <Radio.Group options={CATEGORY_OPTIONS} optionType="button" buttonStyle="solid" />
                </Form.Item>
              )}
              {!hidden('environment') && (
                <Form.Item name="environment" label="发现环境" rules={requiredRule('environment', '发现环境')}>
                  <Input placeholder="如 dev / test / prod，可填「待确认」" maxLength={200} />
                </Form.Item>
              )}
              {!hidden('affected_version') && (
                <Form.Item name="affected_version" label="影响版本" rules={requiredRule('affected_version', '影响版本')}>
                  <Input placeholder="如 v1.2.0，可填「待确认」" maxLength={100} />
                </Form.Item>
              )}
              {!hidden('severity') && (
                <Form.Item name="severity" label="严重度" rules={requiredRule('severity', '严重度')}>
                  <Select options={SEVERITY_OPTIONS} placeholder="默认 2 中" />
                </Form.Item>
              )}
              {!hidden('priority') && (
                <Form.Item name="priority" label="处理优先级" rules={requiredRule('priority', '处理优先级')}>
                  <Select options={PRIORITY_OPTIONS} placeholder="默认 2 中" />
                </Form.Item>
              )}
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                提交后进入项目「待确认」队列，由测试团队按队列跟进；无需选择处理人。
              </Typography.Paragraph>
            </Col>
          </Row>
        </Form>
      )}
    </Modal>
  );
}