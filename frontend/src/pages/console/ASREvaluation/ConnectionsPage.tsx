// 旧 ASR 配置入口保留为书签兼容，模型资源现仅由平台管理后台维护。
import { Navigate } from 'react-router-dom';

/** 把旧书签引导至受平台管理员权限保护的模型中心。 */
export function ConnectionsPage() {
  return <Navigate to="/admin/model-configs?category=ASR" replace />;
}
