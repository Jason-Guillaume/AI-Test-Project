// 测试资产路由页。带用例编号的旧链接改去用例库，避免资产页再承担用例详情。
import { Navigate, useSearchParams } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TestAssetWorkspace } from './TestAssetWorkspace';

/** 测试资产入口。caseId 深链交给用例库。 */
export function ConsoleTestAssetPage() {
  const { currentProjectId } = useConsoleScope();
  const [searchParams] = useSearchParams();
  if (searchParams.get('caseId')) {
    return <Navigate to={`/console/test-cases?${searchParams.toString()}`} replace />;
  }
  return <TestAssetWorkspace key={currentProjectId ?? 'none'} />;
}
