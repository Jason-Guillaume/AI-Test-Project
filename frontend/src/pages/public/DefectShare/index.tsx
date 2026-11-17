// 免登录缺陷详情。
// 本页不使用控制台布局，也不读取平台登录态。
// 凭证只从 URL Fragment 读取，并通过 Authorization 调用公开接口。
import { App, Button, Input, Tag, Typography } from 'antd';
import { isAxiosError } from 'axios';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { publicDefectApi, type PublicDefect } from '@/features/defects/api/publicShare';
import { captureShareToken, forgetShareToken } from '@/features/defects/api/shareToken';
import { getErrorMessage } from '@/shared/api/client';
import './share.css';

const STATUS_COLOR: Record<string, string> = {
  待确认: 'orange', 处理中: 'blue', 已修复: 'cyan', 已关闭: 'default', 已拒绝: 'red',
};

/**
 * 把公开接口错误变成不包含内部信息的说明。
 * 不打印原始错误对象，避免凭证随 Authorization 头进入控制台。
 */
function friendlyError(error: unknown): string {
  if (!isAxiosError(error)) return '网络异常，请稍后重试';
  return getErrorMessage(error, '分享链接暂时无法打开');
}

function isTokenRejected(error: unknown): boolean {
  if (!isAxiosError(error) || !error.response) return false;
  return [401, 403, 404, 410].includes(error.response.status);
}

function textOf(value: unknown): string {
  if (value == null || value === '') return '未记录';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

/**
 * 公开缺陷页。按 shareId 隔离视图；加载时采集并立即清理 Fragment 凭证，不写入持久化存储。
 */
export function PublicDefectSharePage() {
  const { shareId = '' } = useParams();
  return <PublicDefectShareView key={shareId} shareId={shareId} />;
}

function PublicDefectShareView({ shareId }: { shareId: string }) {
  const { message, modal } = App.useApp();
  const [tokenState] = useState(() => captureShareToken(shareId));
  const token = tokenState.status === 'present' ? tokenState.token : '';
  const [data, setData] = useState<PublicDefect | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [description, setDescription] = useState('');
  const [version, setVersion] = useState('');
  const [commitSha, setCommitSha] = useState('');
  const [name, setName] = useState('');

  useEffect(() => {
    document.title = '缺陷详情';
    const robots = document.createElement('meta');
    robots.name = 'robots';
    robots.content = 'noindex, nofollow';
    const referrer = document.createElement('meta');
    referrer.name = 'referrer';
    referrer.content = 'no-referrer';
    document.head.append(robots, referrer);
    return () => {
      robots.remove();
      referrer.remove();
    };
  }, []);

  useEffect(() => {
    if (!shareId || tokenState.status !== 'present') {
      setLoading(false);
      setError('未检测到访问凭证，请重新使用飞书分享链接进入；为保障安全，页面刷新不会保留凭证。');
      return;
    }
    let cancelled = false;
    publicDefectApi.get(shareId, token)
      .then((detail) => {
        if (cancelled) return;
        setData(detail);
        document.title = detail.content.title ? `${detail.content.bug_no || '缺陷'} ${detail.content.title}` : '缺陷详情';
        publicDefectApi.recordView(shareId, token).catch(() => undefined);
      })
      .catch((reason) => {
        if (isTokenRejected(reason)) forgetShareToken(shareId);
        if (!cancelled) setError(friendlyError(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [shareId, token, tokenState.status]);

  /**
   * 二次确认后提交已解决。提交期间按钮保持 loading，避免重复点击。
   */
  function submit() {
    if (!data?.can_submit || !token) return;
    const repair = description.trim();
    if (!repair) {
      message.warning('请填写修复说明');
      return;
    }
    modal.confirm({
      title: '确认提交已解决？',
      content: '是否确认该缺陷已经修复，并提交修复结果？',
      okText: '确认已解决',
      cancelText: '取消',
      onOk: async () => {
        setSubmitting(true);
        try {
          const result = await publicDefectApi.resolve(shareId, token, {
            repair_description: repair,
            fix_version: version.trim() || undefined,
            commit_sha: commitSha.trim() || undefined,
            reporter_name: name.trim() || undefined,
          });
          const latest = await publicDefectApi.get(shareId, token);
          setData(latest);
          message.success(result.message);
        } catch (reason) {
          if (isTokenRejected(reason)) forgetShareToken(shareId);
          message.error(friendlyError(reason));
        } finally {
          setSubmitting(false);
        }
      },
    });
  }

  const content = data?.content;
  return (
    <main className="public-defect">
      <div className="public-defect-main">
        <header className="public-defect-card">
          <Typography.Text type="secondary">测试开发平台 · 免登录缺陷详情</Typography.Text>
          {loading && <Typography.Title level={3}>正在读取缺陷</Typography.Title>}
          {!loading && error && (
            <>
              <Typography.Title level={3} style={{ marginBottom: 8 }}>无法打开分享链接</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>{error}</Typography.Paragraph>
            </>
          )}
          {data && content && <>
            <Typography.Title level={3} style={{ marginBottom: 8 }}>{content.bug_no || '缺陷'} {content.title || ''}</Typography.Title>
            <div className="public-defect-meta">
              {content.severity_label && <Tag color="red">{content.severity_label}</Tag>}
              <Tag color={STATUS_COLOR[data.live_status] || 'blue'}>当前状态：{data.live_status}</Tag>
              {content.created_at && <Tag>创建于 {content.created_at}</Tag>}
            </div>
          </>}
        </header>
        {data && content && <>
          <section className="public-defect-panel">
            <Typography.Title level={4}>基本信息</Typography.Title>
            <div className="public-defect-grid">
              {Object.entries({
                所属项目: content.project_name, 创建人: content.reporter_name, 当前处理人: content.assignee_name, 发现环境: content.environment,
              }).filter(([, value]) => value !== undefined).map(([label, value]) => <div key={label} style={{ display: 'contents' }}>
                <Typography.Text type="secondary">{label}</Typography.Text>
                <Typography.Text>{textOf(value)}</Typography.Text>
              </div>)}
            </div>
          </section>
          <section className="public-defect-panel">
            <Typography.Title level={4}>问题详情</Typography.Title>
            {([
              ['缺陷描述', content.description], ['复现步骤', content.steps_to_reproduce],
              ['预期结果', content.expected_result], ['实际结果', content.actual_result],
            ] as Array<[string, unknown]>).filter(([, value]) => value !== undefined).map(([label, value]) => (
              <Typography.Paragraph key={label}><Typography.Text strong>{label}</Typography.Text><br />{textOf(value)}</Typography.Paragraph>
            ))}
          </section>
          {(content.sources || content.agent_executions || content.allure !== undefined) && (
            <section className="public-defect-panel">
              <Typography.Title level={4}>测试证据</Typography.Title>
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{textOf({
                sources: content.sources, agent_executions: content.agent_executions, allure: content.allure,
              })}</pre>
            </section>
          )}
          <section className="public-defect-panel">
            <Typography.Title level={4}>开发处理</Typography.Title>
            <Typography.Paragraph type="secondary">{data.identity_note} 当前操作来自免登录分享链接。</Typography.Paragraph>
            <Typography.Paragraph>当前状态：{data.live_status}</Typography.Paragraph>
            {data.resolution && <Typography.Paragraph>
              已提交修复结果：{data.resolution.repair_description}<br />
              提交时间：{new Date(data.resolution.submitted_at).toLocaleString()}
              {data.resolution.actor_display_name ? ` · 自报姓名：${data.resolution.actor_display_name}` : ''}
            </Typography.Paragraph>}
            {data.can_submit && <>
              <Input.TextArea value={description} onChange={(event) => setDescription(event.target.value)} rows={4} maxLength={2000} placeholder="请填写修复说明" />
              <Input style={{ marginTop: 8 }} value={version} onChange={(event) => setVersion(event.target.value)} maxLength={80} placeholder="修复版本（选填）" />
              <Input style={{ marginTop: 8 }} value={commitSha} onChange={(event) => setCommitSha(event.target.value)} maxLength={64} placeholder="Commit SHA（选填）" />
              <Input style={{ marginTop: 8 }} value={name} onChange={(event) => setName(event.target.value)} maxLength={40} placeholder="你的姓名（选填，自报且未认证）" />
              <div className="public-defect-actions" style={{ marginTop: 12 }}>
                <Button type="primary" loading={submitting} onClick={submit}>已解决</Button>
              </div>
            </>}
            {!data.can_submit && <Typography.Text type="secondary">{data.allow_resolve ? '当前状态不能再次提交修复。' : '该链接不允许提交修复结果。'}</Typography.Text>}
          </section>
        </>}
      </div>
    </main>
  );
}
