// 用户控制台的作用域上下文：当前选中的项目，以及该项目派生的组织范围。
//
// 同步组织范围或切换项目时通过 queryClient.invalidateQueries 清空相关缓存，
// 避免显示上一项目的数据。作用域通过 query 参数传给后端，不依赖请求头。
//
// 状态来源：localStorage（console.current_org_id / console.current_project_id），刷新页面后仍保留。
// 失效条件：显式传入 null、本地存储值不是合法数字、登出时调用 clear。
// 对子树的副作用：作用域变化会批量失效 react-query 缓存，触发相关列表与看板重新拉取。
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/app/providers/AuthProvider';
import {
  parsePositiveSafeInteger,
  subscribeToSessionLifecycle,
} from '../../shared/session/sessionLifecycle.mjs';

// 组织与项目在 localStorage 中的键名；用 null 表示“未选择”而不是删掉 key 后再判空。
const ORG_KEY = 'console.current_org_id';
const PROJECT_KEY = 'console.current_project_id';
const SCOPE_USER_KEY = 'console.scope_user_id';

/** 只恢复由当前已验证账号保存的正安全整数作用域。 */
function readStoredScope(key: string, userId: number): number | null {
  try {
    const owner = localStorage.getItem(SCOPE_USER_KEY);
    if (owner !== String(userId)) {
      // 旧版本没有作用域所有者，必须重新由当前账号选择，避免跨账号复用。
      localStorage.removeItem(ORG_KEY);
      localStorage.removeItem(PROJECT_KEY);
      localStorage.removeItem(SCOPE_USER_KEY);
      return null;
    }
    const raw = localStorage.getItem(key);
    const id = parsePositiveSafeInteger(raw);
    if (raw !== null && id === null) localStorage.removeItem(key);
    return id;
  } catch {
    // localStorage 不可用或被浏览器策略拒绝时按未选择处理。
    return null;
  }
}

/** 安全保存或删除作用域值，并在至少保留一个范围时登记当前用户。 */
function persistScope(key: string, id: number | null, userId: number) {
  try {
    if (id === null) localStorage.removeItem(key);
    else {
      localStorage.setItem(key, String(id));
      localStorage.setItem(SCOPE_USER_KEY, String(userId));
    }
    if (!localStorage.getItem(ORG_KEY) && !localStorage.getItem(PROJECT_KEY)) {
      localStorage.removeItem(SCOPE_USER_KEY);
    }
  } catch {
    // 状态仍在 React Context 内可用，不因浏览器禁用存储而阻止继续操作。
  }
}

/**
 * ConsoleScopeProvider 对外暴露的当前项目作用域与同步操作。
 * currentOrgId 由 ConsoleLayout 按所选项目自动同步，不再由用户单独选择组织。
 */
interface ConsoleScopeState {
  currentOrgId: number | null; // 当前项目所属组织 ID；无项目或未归属组织时为 null
  currentProjectId: number | null; // 当前选中项目 ID；null 表示不限定项目
  setOrgId: (id: number | null) => void; // 同步项目所属组织范围
  setProjectId: (id: number | null) => void; // 切换项目：持久化并失效项目级缓存
  clear: () => void; // 清空组织与项目（登出或离开控制台时使用）
}

// null 表示上下文尚未挂载；useConsoleScope 会在未包裹时直接抛错。
const ConsoleScopeContext = createContext<ConsoleScopeState | null>(null);

/**
 * 作用域 Provider：持有“当前组织/项目”选择态，并在切换时清理相关查询缓存。
 *
 * 不发请求（只改状态与失效缓存，实际拉取由各页面的 useQuery 触发）。
 * 空态呈现：初值来自 localStorage，没有历史项目选择时两个 ID 均为 null。
 *
 * @param props.children 控制台子树（ConsoleLayout 及其页面）
 */
export function ConsoleScopeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const userId = user?.id ?? 0;
  const [currentOrgId, setOrgIdState] = useState<number | null>(() => {
    // 只有属于已通过 /me 校验的当前用户的范围才可恢复。
    return userId > 0 ? readStoredScope(ORG_KEY, userId) : null;
  });
  const [currentProjectId, setProjectIdState] = useState<number | null>(() => {
    return userId > 0 ? readStoredScope(PROJECT_KEY, userId) : null;
  });

  // 同步项目所属组织范围；只有工作台的组织统计依赖此字段。
  const setOrgId = useCallback((id: number | null) => {
    const safeId = id === null ? null : parsePositiveSafeInteger(id);
    setOrgIdState(safeId);
    persistScope(ORG_KEY, safeId, userId);
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  }, [queryClient, userId]);

  // 切换项目：项目级数据全部以 ['project', id, ...] 为 key，整体失效即可。
  const setProjectId = useCallback((id: number | null) => {
    const safeId = id === null ? null : parsePositiveSafeInteger(id);
    setProjectIdState(safeId);
    persistScope(PROJECT_KEY, safeId, userId);
    // 项目级数据全部以 ['project', id, ...] 为 key，整体失效；缺陷列表若按
    // 项目过滤也会失效（虽然缺陷页面主要靠 keyword 过滤，双保险稳妥）。
    queryClient.invalidateQueries({ queryKey: ['project'] });
    queryClient.invalidateQueries({ queryKey: ['notifications'] });
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    // 接口管理按项目作用域过滤，切换项目后整棵 ['api-catalog'] 缓存失效。
    queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
    // 业务管理同样按项目作用域过滤，切换项目后整棵 ['business'] 缓存失效。
    queryClient.invalidateQueries({ queryKey: ['business'] });
    // Agent 会话按项目隔离，切换项目后整棵 ['agent'] 缓存失效。
    queryClient.invalidateQueries({ queryKey: ['agent'] });
    // 测试数据中心按项目隔离，切换项目后整棵 ['test-data'] 缓存失效。
    queryClient.invalidateQueries({ queryKey: ['test-data'] });
  }, [queryClient, userId]);

  // 清空作用域：复用 setOrgId / setProjectId，保证持久化与缓存失效逻辑一致。
  const clear = useCallback(() => {
    setOrgId(null);
    setProjectId(null);
  }, [setOrgId, setProjectId]);

  // 身份边界变化时同步清 React 作用域，不能依赖一次性挂载时的 localStorage 读取。
  useEffect(() => {
    return subscribeToSessionLifecycle(() => {
      setOrgIdState(null);
      setProjectIdState(null);
    });
  }, []);

  // Provider 可能在同一挂载周期观察到登录身份改变，旧账号的 scope 不能继续生效。
  useEffect(() => {
    if (!userId) {
      setOrgIdState(null);
      setProjectIdState(null);
      return;
    }
    const owner = (() => {
      try { return localStorage.getItem(SCOPE_USER_KEY); } catch { return null; }
    })();
    if (owner !== String(userId)) {
      setOrgIdState(null);
      setProjectIdState(null);
    }
  }, [userId]);

  // 聚合为稳定对象，避免作用域不变时子树被无谓重渲染。
  const value = useMemo<ConsoleScopeState>(
    () => ({ currentOrgId, currentProjectId, setOrgId, setProjectId, clear }),
    [currentOrgId, currentProjectId, setOrgId, setProjectId, clear],
  );

  return (
    <ConsoleScopeContext.Provider value={value}>
      {children}
    </ConsoleScopeContext.Provider>
  );
}

/**
 * 读取控制台作用域。
 *
 * 必须在 <ConsoleScopeProvider> 子树内调用；未包裹时直接抛错。
 * 不发请求。
 *
 * @returns 当前组织/项目 ID 与切换、清空操作
 */
export function useConsoleScope(): ConsoleScopeState {
  const ctx = useContext(ConsoleScopeContext);
  if (!ctx) throw new Error('useConsoleScope must be used within ConsoleScopeProvider');
  return ctx;
}
