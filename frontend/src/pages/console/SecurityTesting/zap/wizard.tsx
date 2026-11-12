// 安全扫描 · 发起扫描四步向导。
//
// ① 选目标 → ② 选策略与认证 → ③ 授权确认 → ④ 计划预览并提交。
// 第 ④ 步必须先调 POST /scan-jobs/plan 拿到计划预览，预览成功前「提交扫描」不可点；
// 后端 plan 是纯读取（不写库、不发 ZAP 请求），提交前必须过一次。
//
// 主动扫描（profile.is_active_scan 或 plan.is_active_scan）在第 ③ 步必须由人勾选确认并
// 填写批准说明，作为 confirmed / approval_note 传给后端；后端仍独立校验批准行为。
// 被动扫描不需要确认，confirmed 传 false。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Col,
  Descriptions,
  Empty,
  Input,
  Modal,
  Row,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanJobCreate, ScanPlan, ScanProfile, ScanTarget } from '@/features/security-testing/zap/contracts';
import { JsonView } from '@/shared/ui/JsonView';
import { getErrorMessage } from '@/shared/api/client';
import {
  authModeLabel,
  authStatusLabel,
  authStatusColor,
  scanModeLabel,
} from './constants';

/** 发起扫描向导。projectId 由父页传入（已确保非空）。 */
export function ScanWizardModal({
  projectId,
  onCancel,
  onSubmitted,
}: {
  projectId: number;
  onCancel: () => void;
  onSubmitted: () => void;
}) {
  const { message } = App.useApp();
  const [step, setStep] = useState(0);
  const [targetId, setTargetId] = useState<number | undefined>(undefined);
  const [profileId, setProfileId] = useState<number | undefined>(undefined);
  const [confirmed, setConfirmed] = useState(false);
  const [approvalNote, setApprovalNote] = useState('');

  // 只拉启用的目标；策略与认证配置全拉（策略表要能显示平台内置）。
  const targetsQuery = useQuery({
    queryKey: ['zap-targets', projectId, 'wizard'],
    queryFn: () => zapApi.listScanTargets(projectId, { page: 1, page_size: 100, enabled: true }),
  });
  const profilesQuery = useQuery({
    queryKey: ['zap-profiles', projectId, 'wizard'],
    queryFn: () => zapApi.listScanProfiles(projectId, { page: 1, page_size: 100 }),
  });
  const authProfilesQuery = useQuery({
    queryKey: ['zap-auth-profiles', projectId, 'wizard'],
    queryFn: () =>
      zapApi.listScanAuthProfiles(projectId, { page: 1, page_size: 100 }),
  });

  const targets = targetsQuery.data?.items ?? [];
  const profiles = profilesQuery.data?.items ?? [];
  const authProfiles = authProfilesQuery.data?.items ?? [];

  const selectedTarget = targets.find((t) => t.id === targetId);
  const selectedProfile = profiles.find((p) => p.id === profileId);
  const boundAuth = selectedProfile
    ? authProfiles.find((a) => a.id === selectedProfile.authentication_profile_id)
    : undefined;

  const needConfirm = selectedProfile?.is_active_scan ?? false;

  const jobBody: ScanJobCreate | null =
    targetId != null && profileId != null
      ? {
          target_id: targetId,
          scan_profile_id: profileId,
          // 被动扫描不需要确认，confirmed 显式传 false，避免后端把它当成「未确认的主动扫描」。
          confirmed: needConfirm && confirmed,
          approval_note: approvalNote.trim() || null,
        }
      : null;

  // 计划预览：只在进入第 ④ 步后触发；改动目标 / 策略 / 确认状态会重新预览。
  const planQuery = useQuery({
    queryKey: ['zap-plan', projectId, targetId, profileId, needConfirm ? confirmed : null],
    queryFn: () => {
      if (!jobBody) return Promise.reject(new Error('尚未选择目标或策略'));
      return zapApi.planScanJob(projectId, jobBody);
    },
    enabled: step === 3 && jobBody != null,
  });

  const submitMutation = useMutation({
    mutationFn: () => {
      if (!jobBody) return Promise.reject(new Error('尚未选择目标或策略'));
      return zapApi.createScanJob(projectId, jobBody);
    },
    onSuccess: (job) => {
      message.success(`扫描任务 #${job.id} 已登记，等待执行`);
      onSubmitted();
      onCancel();
    },
    onError: (e) => message.error(getErrorMessage(e, '提交失败')),
  });

  const canNext = (() => {
    switch (step) {
      case 0:
        return targetId != null;
      case 1:
        return profileId != null;
      case 2:
        return !needConfirm || confirmed;
      case 3:
        return false;
      default:
        return false;
    }
  })();

  // 下一步要填批准说明：主动扫描缺说明时给出中文提示，不让用户白点。
  const goNext = () => {
    if (step === 2 && needConfirm && !approvalNote.trim()) {
      message.warning('请填写授权批准说明');
      return;
    }
    setStep((s) => Math.min(s + 1, 3));
  };

  const footer = (
    <Space>
      {step > 0 && <Button onClick={() => setStep((s) => Math.max(s - 1, 0))}>上一步</Button>}
      {step < 3 && (
        <Button type="primary" disabled={!canNext} onClick={goNext}>
          下一步
        </Button>
      )}
      {step === 3 && (
        <Button
          type="primary"
          danger
          loading={submitMutation.isPending}
          disabled={!planQuery.data || planQuery.data.production_blocked}
          onClick={() => submitMutation.mutate()}
        >
          提交扫描
        </Button>
      )}
      <Button onClick={onCancel}>取消</Button>
    </Space>
  );

  const loading = targetsQuery.isLoading || profilesQuery.isLoading || authProfilesQuery.isLoading;

  const targetColumns: TableColumnsType<ScanTarget> = [
    { title: '目标', dataIndex: 'name', render: (_, r) => <Typography.Text strong>{r.name}</Typography.Text> },
    {
      title: 'base_url',
      dataIndex: 'base_url',
      render: (v: string) => <Typography.Text style={{ fontSize: 12 }}>{v}</Typography.Text>,
    },
    {
      title: '授权状态',
      dataIndex: 'authorization_status',
      width: 130,
      render: (v: string) => <Tag color={authStatusColor(v)}>{authStatusLabel(v)}</Tag>,
    },
    {
      title: '主动扫描',
      dataIndex: 'active_scan_allowed',
      width: 100,
      render: (v: boolean) => (v ? <Tag color="volcano">已允许</Tag> : <Tag>不允许</Tag>),
    },
    {
      title: '环境',
      width: 90,
      render: (_, r) =>
        r.is_production ? <Tag color="red">生产</Tag> : <Tag color="green">非生产</Tag>,
    },
  ];

  const profileColumns: TableColumnsType<ScanProfile> = [
    {
      title: '策略',
      dataIndex: 'name',
      render: (_, r) => (
        <Space size={6}>
          <Typography.Text strong>{r.name}</Typography.Text>
          {r.is_builtin ? <Tag color="purple">平台内置</Tag> : <Tag color="blue">项目</Tag>}
        </Space>
      ),
    },
    {
      title: '扫描模式',
      width: 150,
      render: (_, r) => (
        <Tag color={r.is_active_scan ? 'volcano' : 'cyan'}>{scanModeLabel(r.scan_mode)}</Tag>
      ),
    },
    {
      title: '参数',
      width: 190,
      render: (_, r) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.max_duration} 分钟 · 深度 {r.max_depth} · 并发 {r.max_concurrency} · 间隔{' '}
          {r.request_delay}ms
        </Typography.Text>
      ),
    },
    {
      title: '绑定认证',
      width: 150,
      render: (_, r) =>
        r.authentication_profile_id ? (
          <Tag>{authProfiles.find((a) => a.id === r.authentication_profile_id)?.name ?? `#${r.authentication_profile_id}`}</Tag>
        ) : (
          <Tag>无认证</Tag>
        ),
    },
  ];

  return (
    <Modal
      title="发起扫描"
      open
      width={880}
      onCancel={onCancel}
      footer={footer}
      destroyOnClose
    >
      <Steps
        size="small"
        current={step}
        items={[
          { title: '选目标' },
          { title: '选策略与认证' },
          { title: '授权确认' },
          { title: '计划预览并提交' },
        ]}
        style={{ marginBottom: 20 }}
      />

      {loading ? (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : step === 0 ? (
        targets.length === 0 ? (
          <Empty description="没有已启用的扫描目标，请先到「扫描目标」新建" />
        ) : (
          <Table<ScanTarget> scroll={{ x: 'max-content' }}
            rowKey="id"
            size="small"
            columns={targetColumns}
            dataSource={targets}
            pagination={false}
            rowSelection={{
              type: 'radio',
              selectedRowKeys: targetId != null ? [targetId] : [],
              onChange: (keys) => {
                const first = keys[0];
                setTargetId(typeof first === 'number' ? first : undefined);
              },
            }}
          />
        )
      ) : step === 1 ? (
        <div>
          {profiles.length === 0 ? (
            <Empty description="没有可用的扫描策略，请先到「扫描策略与认证」新建" />
          ) : (
            <Table<ScanProfile> scroll={{ x: 'max-content' }}
              rowKey="id"
              size="small"
              columns={profileColumns}
              dataSource={profiles}
              pagination={false}
              rowSelection={{
                type: 'radio',
                selectedRowKeys: profileId != null ? [profileId] : [],
                onChange: (keys) => setProfileId(typeof keys[0] === 'number' ? keys[0] : undefined),
              }}
            />
          )}
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 12 }}
            message="认证配置绑定在扫描策略上，发起任务时不能单独选择"
            description={
              selectedProfile
                ? selectedProfile.authentication_profile_id
                  ? `当前策略绑定了「${boundAuth?.name ?? `#${selectedProfile.authentication_profile_id}`}」`
                    : `「${selectedProfile.name}」未绑定认证配置，将以 NONE（无认证）模式扫描`
                : '选择策略后会显示它绑定的认证配置。'
            }
          />
          {selectedProfile && (
            <Descriptions
              size="small"
              column={3}
              bordered
              style={{ marginTop: 12 }}
              items={[
                { key: 'mode', label: '扫描模式', children: scanModeLabel(selectedProfile.scan_mode) },
                { key: 'active', label: '是否主动扫描', children: selectedProfile.is_active_scan ? '是（需确认）' : '否（被动）' },
                { key: 'auth', label: '认证模式', children: authModeLabel(selectedProfile.authentication_profile_id ? boundAuth?.auth_mode ?? 'NONE' : 'NONE') },
                { key: 'spider', label: '爬虫', children: selectedProfile.spider_enabled ? '开启' : '关闭' },
                { key: 'passive', label: '被动扫描', children: selectedProfile.passive_enabled ? '开启' : '关闭' },
                { key: 'activeScan', label: '主动扫描', children: selectedProfile.active_enabled ? '开启' : '关闭' },
              ]}
            />
          )}
        </div>
      ) : step === 2 ? (
        <div>
          {needConfirm ? (
            <>
              <Alert
                type="warning"
                showIcon
                message="该策略属于受控主动扫描，需要人工授权确认"
                description="勾选即表示你已获得目标系统所有者的书面授权；后端会独立校验批准行为，前端勾选只是体验。"
                style={{ marginBottom: 16 }}
              />
              {selectedTarget && !selectedTarget.active_scan_allowed && (
                <Alert
                  type="error"
                  showIcon
                  message="该目标未允许主动扫描（active_scan_allowed=false）"
                  description="后端会直接拒绝这次扫描，请先在「扫描目标」里允许主动扫描。"
                  style={{ marginBottom: 16 }}
                />
              )}
              {selectedTarget?.is_production && (
                <Alert
                  type="error"
                  showIcon
                  message="该目标属于生产环境"
                  description="生产环境禁止主动扫描，后端会直接拒绝。请换一个非生产目标，或改用被动扫描策略。"
                  style={{ marginBottom: 16 }}
                />
              )}
              <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>
                我已获得目标系统所有者的书面授权，并同意按所选策略的范围发起主动扫描
              </Checkbox>
              <div style={{ marginTop: 12 }}>
                <Typography.Text>授权批准说明</Typography.Text>
                <Input.TextArea
                  rows={3}
                  maxLength={500}
                  value={approvalNote}
                  onChange={(e) => setApprovalNote(e.target.value)}
                  placeholder="必填：如 安全负责人已邮件批准，范围限测试环境，窗口 2026-10-20 14:00-16:00"
                />
              </div>
            </>
          ) : (
            <Alert
              type="success"
              showIcon
              message="所选策略为被动扫描，无需授权确认"
              description="被动扫描只观察流量与响应，不发送主动探测请求。提交时 confirmed 会传 false。"
            />
          )}
        </div>
      ) : (
        <div>
          {planQuery.isError && (
            <Alert
              type="error"
              showIcon
              message="计划预览失败"
              description={getErrorMessage(planQuery.error)}
              style={{ marginBottom: 16 }}
            />
          )}
          {!planQuery.data && !planQuery.isError && (
            <div style={{ padding: 40, textAlign: 'center' }}>
              <Spin />
            </div>
          )}
          {planQuery.data && <PlanPreview plan={planQuery.data} />}
        </div>
      )}
    </Modal>
  );
}

/** 计划预览展示：预计请求数、是否主动扫描、被拒绝项，提交前必须看到这块内容。 */
function PlanPreview({ plan }: { plan: ScanPlan }) {
  const blocked = plan.production_blocked;

  return (
    <div>
      <Alert
        type={blocked ? 'error' : 'info'}
        showIcon
        style={{ marginBottom: 16 }}
        message={blocked ? '该计划被拒绝：目标属于生产环境' : '计划预览（预览通过后可提交）'}
        description={
          blocked
            ? '生产环境禁止扫描，提交会被后端拒绝。请换一个非生产目标，或改用被动扫描策略。'
            : plan.warning ?? '以下为后端按目标与策略计算出的实际扫描范围。'
        }
      />

      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <Descriptions
            size="small"
            bordered
            column={1}
            title="扫描参数"
            items={[
              { key: 'active', label: '是否主动扫描', children: plan.is_active_scan ? <Tag color="volcano">主动扫描</Tag> : <Tag color="cyan">被动扫描</Tag> },
              { key: 'estimated', label: '预计请求数', children: plan.estimated_requests ?? '未知' },
              { key: 'duration', label: '最长时长（分钟）', children: plan.max_duration_minutes },
              { key: 'depth', label: '最大深度', children: plan.max_depth },
              { key: 'concurrency', label: '最大并发', children: plan.max_concurrency },
              { key: 'delay', label: '请求间隔（毫秒）', children: plan.request_delay_ms },
              { key: 'auth', label: '认证模式', children: authModeLabel(plan.authentication_mode ?? 'NONE') },
              { key: 'browser', label: '浏览器会话', children: plan.browser_session_established ? '已建立' : '未建立' },
              { key: 'zap', label: 'ZAP 可用', children: plan.zap_available ? <Tag color="green">可用</Tag> : <Tag color="orange">不可用（受限）</Tag> },
            ]}
          />
        </Col>
        <Col xs={24} lg={12}>
          <Descriptions
            size="small"
            bordered
            column={1}
            title="范围与受限项"
            items={[
              { key: 'exclude', label: '排除路径', children: plan.exclude_paths.length ? plan.exclude_paths.join(', ') : '无' },
              { key: 'limitations', label: '受限 / 被拒绝项', children: plan.limitations.length ? plan.limitations.join('；') : '无' },
            ]}
          />
        </Col>
      </Row>

      {plan.limitations.length === 0 && !blocked && (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
          未列出任何受限项，表示后端没有拒绝任何能力；这不等于 ZAP 服务一定在线。
        </Typography.Text>
      )}

      <div style={{ marginTop: 16 }}>
        <Typography.Text strong>计划上下文（后端算出的实际范围）</Typography.Text>
        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col xs={24} md={8}>
            <JsonView value={plan.target} title="目标" maxHeight={220} />
          </Col>
          <Col xs={24} md={8}>
            <JsonView value={plan.profile} title="策略" maxHeight={220} />
          </Col>
          <Col xs={24} md={8}>
            <JsonView value={plan.environment} title="环境" maxHeight={220} />
          </Col>
        </Row>
      </div>
    </div>
  );
}
