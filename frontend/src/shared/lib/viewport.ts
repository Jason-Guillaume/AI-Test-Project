// Ant Design `lg` 断点（992px）以下的窄屏检测，用于同步初始化侧边栏折叠态，避免移动端首帧闪烁。
export function isNarrowViewport(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 991.98px)').matches;
}
