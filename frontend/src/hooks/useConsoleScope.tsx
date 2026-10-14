// 用户控制台的作用域上下文：当前选中的组织与项目。
//
// 切换组织/项目时通过 queryClient.invalidateQueries 清空以旧作用域为 key 的缓存，
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

// 组织与项目在 localStorage 中的键名；用 null 表示“未选择”而不是删掉 key 后再判空。
const ORG_KEY = 'console.current_org_id';
const PROJECT_KEY = 'console.current_project_id';

/**
 * ConsoleScopeProvider 对外暴露的当前作用域与切换操作。
 * 作用域为 null 表示未选择，此时后端接口按“不限定作用域”处理。
 */
interface ConsoleScopeState {
  currentOrgId: number | null; // 当前选中组织 ID；null 表示未选择任何组织
  currentProjectId: number | null; // 当前选中项目 ID；null 表示仅按组织作用域过滤
  setOrgId: (id: number | null) => void; // 切换组织：持久化并失效项目级缓存
  setProjectId: (id: number | null) => void; // 切换项目：持久化并失效项目级缓存
  clear: () => void; // 清空组织与项目（登出或离开控制台时使用）
}

// null 表示上下文尚未挂载；useConsoleScope 会在未包裹时直接抛错。
const ConsoleScopeContext = createContext<ConsoleScopeState | null>(null);

/**
 * 作用域 Provider：持有“当前组织/项目”选择态，并在切换时清理相关查询缓存。
 *
 * 不发请求（只改状态与失效缓存，实际拉取由各页面的 useQuery 触发）。
 * 空态呈现：初值来自 localStorage，没有历史选择时两个 ID 均为 null，
 * 由 UI 展示“选择组织/项目”占位而不是报错。
 *
 * @param props.children 控制台子树（ConsoleLayout 及其页面）
 */
export function ConsoleScopeProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [currentOrgId, setOrgIdState] = useState<number | null>(() => {
    // 惰性初始化：从 localStorage 恢复上次选择，没有则保持 null。
    const raw = localStorage.getItem(ORG_KEY);
    return raw ? Number(raw) : null;
  });
  const [currentProjectId, setProjectIdState] = useState<number | null>(() => {
    const raw = localStorage.getItem(PROJECT_KEY);
    return raw ? Number(raw) : null;
  });

  // 切换组织：同步写 localStorage，并让项目列表与看板失效。
  const setOrgId = useCallback((id: number | null) => {
    setOrgIdState(id);
    if (id == null) localStorage.removeItem(ORG_KEY);
    else localStorage.setItem(ORG_KEY, String(id));
    // 组织切换会让项目列表与项目级数据全部失效；缺陷列表按当前作用域过滤，
    // 组织切换后可能命中新的项目集合，也一起刷新。
    queryClient.invalidateQueries({ queryKey: ['projects'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    // 业务管理按项目作用域过滤，组织切换后项目集合可能变化。
    queryClient.invalidateQueries({ queryKey: ['business'] });
  }, [queryClient]);

  // 切换项目：项目级数据全部以 ['project', id, ...] 为 key，整体失效即可。
  const setProjectId = useCallback((id: number | null) => {
    setProjectIdState(id);
    if (id == null) localStorage.removeItem(PROJECT_KEY);
    else localStorage.setItem(PROJECT_KEY, String(id));
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
  }, [queryClient]);

  // 清空作用域：复用 setOrgId / setProjectId，保证持久化与缓存失效逻辑一致。
  const clear = useCallback(() => {
    setOrgId(null);
    setProjectId(null);
  }, [setOrgId, setProjectId]);

  // 若本地存储的值不是合法数字，清理掉。
  useEffect(() => {
    // 兼容旧版本写入的脏数据：NaN 不能被持久化，也不应传给后端。
    if (currentOrgId !== null && Number.isNaN(currentOrgId)) {
      localStorage.removeItem(ORG_KEY);
      setOrgIdState(null);
    }
  }, [currentOrgId]);

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
