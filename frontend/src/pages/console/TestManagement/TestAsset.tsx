// 测试资产路由页：切换项目时重建工作区，避免跨项目保留编辑状态。
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TestAssetWorkspace } from './TestAssetWorkspace';

export function ConsoleTestAssetPage() {
  const { currentProjectId } = useConsoleScope();
  return <TestAssetWorkspace key={currentProjectId ?? 'none'} />;
}
