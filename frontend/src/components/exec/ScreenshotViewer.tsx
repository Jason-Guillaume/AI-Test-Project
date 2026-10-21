// Web 执行附件里的截图查看器。
//
// 后端强制 Content-Disposition: attachment，artifacts.url 不能直接作为 <img src>，
// 必须走 webUIApi.artifact(id) 取 Blob → URL.createObjectURL → <Image>。
// 卸载或切换时必须 URL.revokeObjectURL，避免内存泄漏（参考 WebUI/Artifacts.tsx L16-27）。
//
// 只渲染截图类附件（SCREENSHOT / FAILURE_SCREENSHOT），TRACE 类交给 TraceViewer。
// 下载是次级入口，主入口是 Image 内置的放大预览。
//
// 重试：调用方通过 key 变化让内部组件重建（`key={id:attempt}`），Blob URL 由卸载清理函数释放。

import { useEffect, useState } from 'react';
import { AxiosError } from 'axios';
import { App, Button, Image, Space, Spin, Tag, theme, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { webUIApi } from '@/api/webUI';
import type { WebArtifactRef } from '@/shared/webSnapshot';

/**
 * 附件接口的错误文案。
 *
 * webUIApi.artifact 用 responseType:'blob'，失败时 error.response.data 也是 Blob，
 * 通用 getErrorMessage 会把它 String() 成 "[object Blob]"。这里改成按状态码给确定文案。
 * 0012 版本回滚会清理历史 Web 附件，404 是真实会出现的常态，不是异常。
 */
function getErrorStatus(error: unknown): number | undefined {
  // instanceof 判据与 client.ts 一致（AxiosError.isAxiosError 在当前 axios 类型里不存在）
  return error instanceof AxiosError ? error.response?.status : undefined;
}

function artifactErrorText(error: unknown): string {
  const status = getErrorStatus(error);
  if (status === 401 || status === 403) return '无权限查看该附件';
  if (status === 404) return '截图已不可用（附件可能已被清理）';
  if (status === undefined) return '网络错误或请求被取消';
  return `请求失败（HTTP ${status}）`;
}

type Phase = 'loading' | 'ready' | 'error';

interface ScreenshotItemProps {
  artifact: WebArtifactRef;
  /** 触发一次重新加载（父组件通过 key 变化让本组件重建） */
  onRetry: () => void;
}

/** 单张截图卡片：加载态、失败态、重试入口。 */
function ScreenshotItem({ artifact, onRetry }: ScreenshotItemProps) {
  const { token } = theme.useToken();
  const { message } = App.useApp();
  const [phase, setPhase] = useState<Phase>('loading');
  const [url, setUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>('');

  useEffect(() => {
    let active = true;
    let created: string | undefined;

    setPhase('loading');
    setUrl(null);
    setErrorMsg('');

    webUIApi
      .artifact(artifact.id)
      .then((blob) => {
        const u = URL.createObjectURL(blob);
        created = u;
        if (active) {
          setUrl(u);
          setPhase('ready');
        } else {
          // 组件已卸载，立即释放，不残留内存 URL
          URL.revokeObjectURL(u);
        }
      })
      .catch((error: unknown) => {
        if (active) {
          const text = artifactErrorText(error);
          setErrorMsg(text);
          setPhase('error');
          // 面板内已显示同样的文案，不再弹 toast 重复打扰
        }
      });

    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
    };
    // 依赖仅 artifact.id：父组件通过 key 让本组件重建来触发重试
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifact.id]);

  async function handleDownload() {
    try {
      const blob = await webUIApi.artifact(artifact.id);
      const u = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = u;
      link.download = `${artifact.id}.png`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(u), 1000);
    } catch (error) {
      // 下载没有内联面板，保留 toast 作为唯一的错误反馈
      void message.error(artifactErrorText(error));
    }
  }

  const isFailure = artifact.kind === 'FAILURE_SCREENSHOT';

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: token.marginXS,
        padding: token.paddingSM,
        border: `1px solid ${isFailure ? token.colorErrorBorder : token.colorBorderSecondary}`,
        borderRadius: token.borderRadiusSM,
        background: isFailure ? token.colorErrorBg : token.colorBgContainer,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: token.marginXS }}>
        <Space size={4}>
          <Tag color={isFailure ? 'red' : 'blue'} bordered={false}>
            {isFailure ? '失败截图' : '执行截图'}
          </Tag>
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            {artifact.id.slice(0, 8)}…
          </Typography.Text>
        </Space>
        <Button
          type="text"
          size="small"
          icon={<DownloadOutlined />}
          onClick={() => void handleDownload()}
          aria-label="下载截图"
        >
          下载
        </Button>
      </div>

      {phase === 'loading' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: token.marginXS, color: token.colorTextTertiary }}>
          <Spin size="small" />
          <span style={{ fontSize: token.fontSizeSM }}>正在加载截图…</span>
        </div>
      )}

      {phase === 'error' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: token.marginXS, color: token.colorError }}>
          <span style={{ fontSize: token.fontSizeSM }}>加载失败：{errorMsg}</span>
          <Button type="link" size="small" onClick={onRetry}>
            重试
          </Button>
        </div>
      )}

      {phase === 'ready' && url ? (
        <Image
          src={url}
          alt={isFailure ? '失败时刻浏览器截图' : '执行时刻浏览器截图'}
          style={{
            maxWidth: '100%',
            maxHeight: 360,
            borderRadius: token.borderRadiusSM,
            display: 'block',
          }}
          preview={{ mask: '放大查看' }}
        />
      ) : null}
    </div>
  );
}

interface ScreenshotViewerProps {
  /** 附件清单，混合 SCREENSHOT / FAILURE_SCREENSHOT / TRACE；本组件只渲染前两者 */
  artifacts: WebArtifactRef[];
  /** 空态文案 */
  emptyText?: string;
}

/**
 * 截图查看器。
 *
 * 主入口：antd Image 内置放大预览。次级入口：下载按钮。
 * 每条截图独立管理 Blob URL 生命周期，卸载或切换时释放。
 */
export function ScreenshotViewer({ artifacts, emptyText = '无截图' }: ScreenshotViewerProps) {
  const { token } = theme.useToken();

  // 重试计数器：递增 attempt 并改变 key，让内部组件重建从而重新拉取
  const [attempts, setAttempts] = useState<Record<string, number>>({});
  function retry(id: string) {
    setAttempts((prev) => ({ ...prev, [id]: (prev[id] ?? 0) + 1 }));
  }

  const screenshots = artifacts.filter((a) => a.kind !== 'TRACE');
  if (screenshots.length === 0) {
    return <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{emptyText}</Typography.Text>;
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: token.marginXS }}>
      {screenshots.map((a) => {
        const attempt = attempts[a.id] ?? 0;
        return (
          <ScreenshotItem
            // key 变化会彻底重建组件，触发新的一次 blob 拉取
            key={`${a.id}:${attempt}`}
            artifact={a}
            onRetry={() => retry(a.id)}
          />
        );
      })}
    </div>
  );
}
