import { ConsoleScopeProvider } from '@/app/providers/ConsoleScopeProvider';
import { ModelCenterPage } from '@/pages/console/ModelCenterPage';

/** 管理端统一维护全平台共享模型，不按当前项目筛选。 */
export function AdminModelConfigsPage() {
  return (
    <ConsoleScopeProvider>
      <ModelCenterPage />
    </ConsoleScopeProvider>
  );
}
