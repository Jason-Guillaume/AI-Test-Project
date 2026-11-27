// 队列动作弹窗：确认问题/登记可回归/回归通过/回归失败/拒绝/判重/重开。
// 携带 expected_version 做乐观并发；409 时展示服务端最新状态，保留未提交说明。
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Form, Input, InputNumber, Modal, Select, Space, Typography } from 'antd';
import { useState } from 'react';
import { bugsApi } from '@/features/defects/api/defects';
import type { Bug, BugAction, BugActionRequest, BugPriority, BugSeverity } from '@/features/defects/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { ACTION_LABELS, PRIORITY_OPTIONS, SEVERITY_OPTIONS, STATUS_DISPLAY } from './constants';

interface ActionFormValues {
  note?: string;
  fix_version?: string;
  feedback_source?: string;
  verification_environment?: string;
  verification_execution_id?: number;
  duplicate_of_bug_id?: number;
  severity?: BugSeverity;
  priority?: BugPriority;
  steps_to_reproduce?: string;
  expected_result?: string;
  actual_result?: string;
  environment?: string;
  affected_version?: string;
}

const NOTE_REQUIRED: Partial<Record<BugAction, string>> = {
  regression_pass: '请填写验证结论',
  regression_fail: '请填写回归失败原因',
  reject: '请填写拒绝原因',
  reopen: '请填写重开依据（新版本或新证据）',
};

/**
 * 队列动作弹窗：按动作收集必填项（修复版本/结论/原因/主缺陷），携带 expected_version 乐观并发。
 * 409 时展示服务端最新状态并失效详情缓存；成功后失效列表、详情、活动、队列与统计。
 */
export function DefectActionModal({
  bug, action, onClose, onDone,
}: {
  bug: Bug;
  action: BugAction;
  onClose: () => void;
  onDone: () => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<ActionFormValues>();
  const [conflict, setConflict] = useState<string | null>(null);

  // 判重需要同项目主单候选。
  const candidates = useQuery({
    queryKey: ['bugs', 'duplicate-candidates', bug.project_id],
    queryFn: () => bugsApi.list({ project_id: bug.project_id, page: 1, page_size: 100 }),
    enabled: action === 'mark_duplicate',
  });

  const mutation = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      const body: BugActionRequest = { action, expected_version: bug.record_version };
      if (values.note) body.note = values.note;
      if (action === 'ready_for_regression') {
        body.fix_version = values.fix_version;
        if (values.feedback_source) body.feedback_source = values.feedback_source;
      }
      if (action === 'regression_pass' || action === 'regression_fail') {
        if (values.verification_environment) body.verification_environment = values.verification_environment;
        if (values.verification_execution_id) body.verification_execution_id = values.verification_execution_id;
      }
      if (action === 'mark_duplicate') body.duplicate_of_bug_id = values.duplicate_of_bug_id;
      if (action === 'confirm') {
        for (const field of ['severity', 'priority', 'steps_to_reproduce', 'expected_result', 'actual_result', 'environment', 'affected_version'] as const) {
          if (values[field] != null && values[field] !== '') {
            Object.assign(body, { [field]: values[field] });
          }
        }
      }
      return bugsApi.action(bug.id, body);
    },
    onSuccess: (result) => {
      message.success(`已${ACTION_LABELS[action]}，当前状态「${result.bug.status_display}」`);
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      queryClient.invalidateQueries({ queryKey: ['bug-detail'] });
      queryClient.invalidateQueries({ queryKey: ['bug-activities', bug.id] });
      queryClient.invalidateQueries({ queryKey: ['defect-queues'] });
      queryClient.invalidateQueries({ queryKey: ['defect-stats'] });
      onDone();
    },
    onError: (error) => {
      const response = (error as { response?: { status?: number; data?: { message?: string; meta?: { status?: string } } } }).response;
      if (response?.status === 409) {
        const latest = response.data?.meta?.status;
        setConflict(
          `${response.data?.message ?? '缺陷已被他人更新'}${latest ? `；最新状态为「${STATUS_DISPLAY[latest as keyof typeof STATUS_DISPLAY] ?? latest}」` : ''}。请关闭后刷新详情再操作。`,
        );
        queryClient.invalidateQueries({ queryKey: ['bug-detail', bug.id] });
      } else {
        setConflict(getErrorMessage(error, '操作失败'));
      }
    },
  });

  return (
    <Modal
      open
      title={`${ACTION_LABELS[action]} · 缺陷 #${bug.id}`}
      onCancel={onClose}
      onOk={() => mutation.mutate()}
      confirmLoading={mutation.isPending}
      okText={`确认${ACTION_LABELS[action]}`}
      cancelText="取消"
      destroyOnHidden
      width={560}
    >
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          当前状态「{bug.status_display}」 · 记录版本 {bug.record_version}
        </Typography.Text>
        {conflict && <Alert type="error" showIcon message={conflict} />}
        <Form<ActionFormValues>
          form={form}
          layout="vertical"
          initialValues={action === 'confirm' ? {
            severity: bug.severity,
            priority: bug.priority,
            steps_to_reproduce: bug.steps_to_reproduce ?? undefined,
            expected_result: bug.expected_result ?? undefined,
            actual_result: bug.actual_result ?? undefined,
            environment: bug.environment ?? undefined,
            affected_version: bug.affected_version ?? undefined,
          } : {}}
        >
          {action === 'confirm' && (
            <>
              <Typography.Paragraph type="secondary">确认问题时可补齐事实字段；确认后进入「处理中」。</Typography.Paragraph>
              <div className="form-field-row">
                <Form.Item name="severity" label="严重度" style={{ flex: 1, margin: 0 }}>
                  <Select options={SEVERITY_OPTIONS} allowClear />
                </Form.Item>
                <Form.Item name="priority" label="优先级" style={{ flex: 1, margin: 0 }}>
                  <Select options={PRIORITY_OPTIONS} allowClear />
                </Form.Item>
              </div>
              <Form.Item name="steps_to_reproduce" label="复现步骤">
                <Input.TextArea rows={3} />
              </Form.Item>
              <Form.Item name="expected_result" label="预期结果">
                <Input.TextArea rows={2} maxLength={4000} />
              </Form.Item>
              <Form.Item name="actual_result" label="实际结果">
                <Input.TextArea rows={2} maxLength={4000} />
              </Form.Item>
              <div className="form-field-row">
                <Form.Item name="environment" label="发现环境" style={{ flex: 1, margin: 0 }}>
                  <Input maxLength={200} placeholder="可填「待确认」" />
                </Form.Item>
                <Form.Item name="affected_version" label="影响版本" style={{ flex: 1, margin: 0 }}>
                  <Input maxLength={100} placeholder="可填「待确认」" />
                </Form.Item>
              </div>
            </>
          )}
          {action === 'ready_for_regression' && (
            <>
              <Form.Item name="fix_version" label="可回归的版本 / 构建 / 环境" rules={[{ required: true, whitespace: true, message: '请填写可回归的版本、构建或环境' }]}>
                <Input placeholder="如 build-1024 / v1.2.3 / staging 环境" maxLength={200} />
              </Form.Item>
              <Form.Item name="feedback_source" label="处理反馈来源" tooltip="如飞书群外部开发反馈，便于追溯">
                <Input placeholder="如：飞书群 @王开发 反馈已修复" maxLength={200} />
              </Form.Item>
            </>
          )}
          {(action === 'regression_pass' || action === 'regression_fail') && (
            <>
              <Form.Item name="verification_environment" label="回归环境">
                <Input placeholder="如 staging / 预发" maxLength={200} />
              </Form.Item>
              <Form.Item name="verification_execution_id" label="关联回归执行 ID" tooltip="可填写新的用例执行 ID 留作证据；手工回归可不填">
                <InputNumber min={1} style={{ width: '100%' }} placeholder="可选" />
              </Form.Item>
            </>
          )}
          {action === 'mark_duplicate' && (
            <Form.Item name="duplicate_of_bug_id" label="同项目主单" rules={[{ required: true, message: '请选择同项目的主单' }]}>
              <Select
                showSearch
                optionFilterProp="label"
                loading={candidates.isPending}
                placeholder="选择重复指向的主单"
                options={(candidates.data?.items ?? [])
                  .filter((item) => item.id !== bug.id)
                  .map((item) => ({ label: `#${item.id} ${item.title}（${item.status_display}）`, value: item.id }))}
              />
            </Form.Item>
          )}
          {action !== 'confirm' && (
            <Form.Item
              name="note"
              label={action === 'regression_pass' ? '验证结论' : action === 'regression_fail' ? '失败原因' : action === 'reject' ? '拒绝原因' : action === 'reopen' ? '重开依据' : '操作说明'}
              rules={NOTE_REQUIRED[action] ? [{ required: true, whitespace: true, message: NOTE_REQUIRED[action] }] : []}
            >
              <Input.TextArea rows={3} maxLength={4000} placeholder="将记录到活动时间线，供团队追溯" />
            </Form.Item>
          )}
        </Form>
      </Space>
    </Modal>
  );
}