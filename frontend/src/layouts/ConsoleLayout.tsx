// 用户控制台布局：左侧菜单 + 顶部组织/项目选择器与用户菜单。
// 不在此处做鉴权（由 RequireAuth 守卫完成）；也不在此处请求项目/组织之外的数据。
// 不做菜单级权限过滤：权限与路由逻辑保持现状，由路由守卫与页面自身控制。
import {
  Avatar,
  Breadcrumb,
  Dropdown,
  Flex,
  Layout,
  Menu,
  Select,
  theme,
} from 'antd';
import {
  ApiOutlined,
  AppstoreOutlined,
  BellOutlined,
  BlockOutlined,
  ChromeOutlined,
  CloudServerOutlined,
  BugOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LogoutOutlined,
  PartitionOutlined,
  PlayCircleOutlined,
  ProjectOutlined,
  RobotOutlined,
  SafetyOutlined,
  ScheduleOutlined,
  SendOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/hooks/useAuth';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { organizationsApi } from '@/api/organizations';
import { projectsApi } from '@/api/projects';
import { prefersDarkScheme } from '@/theme';
import { TaskSchedulerDrawer } from '@/components/tasks/TaskSchedulerDrawer';

// antd Layout 子部件解构：侧边栏、头部、内容区。
const { Header, Sider, Content } = Layout;

// 控制台左侧导航项：key 与 App.tsx 的路由 path 保持一致，
// 用于 selectedKeys 高亮以及跳转目标。
// 分组父 key 使用无对应路由的虚拟 key（/console/test-design 等），
// 只作为可展开容器，绝不复用在册真实路由，避免被当成可点击链接。
interface MenuLeaf {
  key: string;
  icon: ReactNode;
  label: string;
}
interface MenuGroup {
  key: string;
  icon: ReactNode;
  label: string;
  children: MenuLeaf[];
}
type MenuItem = MenuLeaf | MenuGroup;

// 分组父 key 常量：与菜单结构共用，避免字符串重复定义后漂移。
const GROUP_TEST_DESIGN = '/console/test-design'; // 测试设计
const GROUP_TEST_EXECUTION = '/console/test-execution'; // 测试执行
const GROUP_TEST_CAPABILITY = '/console/test-capability'; // 测试能力
const GROUP_NOTIFICATION_CENTER = '/console/notification-center'; // 通知中心

const MENU_ITEMS: MenuItem[] = [
  { key: '/console', icon: <AppstoreOutlined />, label: '工作台' }, // 工作台
  { key: '/console/projects', icon: <ProjectOutlined />, label: '项目管理' }, // 项目管理
  {
    key: GROUP_TEST_DESIGN, // 测试设计（分组）
    icon: <ExperimentOutlined />,
    label: '测试设计',
    children: [
      { key: '/console/api-catalog', icon: <ApiOutlined />, label: '接口管理' },
      { key: '/console/business-management', icon: <PartitionOutlined />, label: '业务管理' },
      { key: '/console/test-asset', icon: <FileTextOutlined />, label: '测试资产' },
      { key: '/console/test-suites', icon: <BlockOutlined />, label: '测试套件' },
    ],
  },
  {
    key: GROUP_TEST_EXECUTION, // 测试执行（分组）
    icon: <ThunderboltOutlined />,
    label: '测试执行',
    children: [
      { key: '/console/test-plans', icon: <ScheduleOutlined />, label: '测试计划' },
      { key: '/console/execution-center', icon: <PlayCircleOutlined />, label: '执行中心' },
      { key: '/console/execution-history', icon: <HistoryOutlined />, label: '执行历史' },
      { key: '/console/test-reports', icon: <FileSearchOutlined />, label: '测试报告' },
    ],
  },
  {
    key: GROUP_TEST_CAPABILITY, // 测试能力（分组）
    icon: <ToolOutlined />,
    label: '测试能力',
    children: [
      { key: '/console/test-data', icon: <DatabaseOutlined />, label: '测试数据' },
      // 接口 Mock 的执行记录页（/console/mock-management/executions）有意不占菜单位：
      // 它从「接口 Mock」列表与端点详情里的链接进入，属于 Mock 模块内部路径，
      // 不提升为一级入口以免稀释本分组的 IA。ROUTE_TITLES 里仍保留其标题以支持面包屑。
      { key: '/console/mock-management', icon: <CloudServerOutlined />, label: '接口 Mock' },
      { key: '/console/web-ui', icon: <ChromeOutlined />, label: 'Web UI 自动化' },
      { key: '/console/web-ui-agent', icon: <RobotOutlined />, label: 'Web UI 智能体' },
      { key: '/console/security-testing', icon: <SafetyOutlined />, label: '安全测试' },
    ],
  },
  { key: '/console/agent', icon: <RobotOutlined />, label: 'AI Agent' }, // AI Agent
  { key: '/console/tasks', icon: <ScheduleOutlined />, label: '统一任务' }, // 持久化任务与多 Agent 团队
  { key: '/console/defects', icon: <BugOutlined />, label: '缺陷管理' }, // 缺陷管理
  {
    key: GROUP_NOTIFICATION_CENTER, // 通知中心（分组）
    icon: <BellOutlined />,
    label: '通知中心',
    children: [
      { key: '/console/notifications', icon: <BellOutlined />, label: '通知记录' },
      { key: '/console/notification-channels', icon: <SendOutlined />, label: '通知渠道' },
    ],
  },
];

// 所有可命中菜单 key（含分组父 key 与子菜单叶子），
// 用于 selectedMenuKey 的精确/前缀匹配。
const ALL_MENU_KEYS: string[] = (() => {
  const keys: string[] = [];
  for (const item of MENU_ITEMS) {
    keys.push(item.key);
    if ('children' in item) item.children.forEach((c) => keys.push(c.key));
  }
  return keys;
})();

// 叶子 key -> 分组父 key：路由变化时据此自动展开所属分组。
const GROUP_OF_LEAF: Record<string, string> = (() => {
  const map: Record<string, string> = {};
  for (const item of MENU_ITEMS) {
    if ('children' in item) {
      item.children.forEach((c) => {
        map[c.key] = item.key;
      });
    }
  }
  return map;
})();

// 合法分组 key 集合：用于清洗 localStorage 里残留的已改名/已下线分组。
const GROUP_KEYS: Set<string> = new Set(
  MENU_ITEMS.filter((i): i is MenuGroup => 'children' in i).map((i) => i.key),
);

// 分组展开态在 localStorage 中的键名，沿用 useConsoleScope 的 console.* 前缀约定。
const OPEN_KEYS_STORAGE = 'console.menu.open_keys';

// 默认展开全部分组：与重构前「所有条目平铺可见」的信息量保持一致。
const DEFAULT_OPEN_KEYS: string[] = [...GROUP_KEYS];

// 从 localStorage 读取展开态；读取失败、数据损坏或全部为失效 key 时静默降级到默认值。
function loadOpenKeys(): string[] {
  try {
    if (typeof window === 'undefined') return [...DEFAULT_OPEN_KEYS]; // SSR 无 localStorage
    const raw = window.localStorage.getItem(OPEN_KEYS_STORAGE);
    if (!raw) return [...DEFAULT_OPEN_KEYS];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_OPEN_KEYS];
    // 只保留仍然存在的分组 key，丢弃历史版本写入的脏数据。
    const valid = parsed.filter(
      (k): k is string => typeof k === 'string' && GROUP_KEYS.has(k),
    );
    return valid.length > 0 ? valid : [...DEFAULT_OPEN_KEYS];
  } catch {
    // localStorage 不可用（隐私模式、配额满）或数据非 JSON 时静默降级。
    return [...DEFAULT_OPEN_KEYS];
  }
}

// 面包屑用的路由标题映射；带 :param 的 key 是动态路由占位符，
// 由 matchRouteTitle 按路径段数匹配，不用于精确查找。
const ROUTE_TITLES: Record<string, string> = {
  '/console': '工作台', // 工作台
  '/console/projects': '项目管理', // 项目管理
  '/console/projects/:id': '项目详情', // 项目详情（动态）
  '/console/defects': '缺陷管理', // 缺陷管理
  '/console/api-catalog': '接口管理', // 接口管理
  '/console/business-management': '业务管理', // 业务管理
  '/console/test-asset': '测试资产', // 测试资产
  '/console/test-suites': '测试套件', // 测试套件
  '/console/test-plans': '测试计划', // 测试计划
  '/console/execution-center': '执行中心', // 执行中心
  '/console/execution-history': '执行历史', // 执行历史
  '/console/test-reports': '测试报告', // 测试报告
  '/console/test-reports/:reportId': '报告详情', // 报告详情（动态，与列表页区分）
  '/console/mock-management': '接口 Mock', // 接口 Mock
  '/console/mock-management/services/:serviceId': '服务详情', // 服务详情（动态）
  '/console/mock-management/endpoints/:endpointId': '端点详情', // 端点详情（动态）
  '/console/mock-management/executions': '接口 Mock 执行', // 接口 Mock 执行
  '/console/web-ui': 'Web UI 自动化', // Web UI 自动化
  '/console/web-ui-agent': 'Web UI 智能体', // Web UI 智能体交互式编写
  '/console/security-testing': '安全测试', // 安全测试
  '/console/test-data': '测试数据', // 测试数据
  '/console/agent': 'AI Agent', // AI Agent
  '/console/tasks': '统一任务', // 全局任务列表
  '/console/tasks/:taskId': '任务执行台', // 任务详情
  '/console/notifications': '通知记录', // 通知记录
  '/console/notification-channels': '通知渠道', // 通知渠道
  '/console/profile': '个人中心', // 个人中心
};

/**
 * 解析当前路径对应的标题。
 *
 * 先精确匹配；未命中再按「路径段数一致 + :param 段通配」匹配动态路由，
 * 使 /console/test-reports/5 得到「报告详情」而不是列表页的「测试报告」。
 *
 * @param pathname 当前路径
 * @returns 命中的标题；未命中返回 undefined
 */
function matchRouteTitle(pathname: string): string | undefined {
  const exact = ROUTE_TITLES[pathname];
  if (exact) return exact;
  const segs = pathname.split('/').filter(Boolean);
  for (const [pattern, title] of Object.entries(ROUTE_TITLES)) {
    const pSegs = pattern.split('/').filter(Boolean);
    if (pSegs.length !== segs.length) continue;
    if (pSegs.every((s, i) => s.startsWith(':') || s === segs[i])) return title;
  }
  return undefined;
}

/**
 * 用户控制台布局：左侧导航 + 顶部作用域选择器 + 面包屑 + 路由出口。
 *
 * 会发请求：拉取当前用户可见的组织列表，以及当前组织下的项目列表（page_size 固定 100）。
 * 失败/空态：接口失败或列表为空时两个选择器只渲染 placeholder，不阻塞子页面渲染。
 * 副作用：切换组织会清空项目作用域并触发项目列表失效。
 */
export function ConsoleLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth(); // 当前用户与登出操作
  const { currentOrgId, setOrgId, currentProjectId, setProjectId } =
    useConsoleScope(); // 当前组织/项目选择态与切换操作
  const { token: themeToken } = theme.useToken(); // antd 设计令牌，用于主题色
  const darkMode = prefersDarkScheme(); // 侧栏主题与全局主题共用同一判定

  // 组织列表：不依赖任何作用域，作为组织下拉的候选项。
  const { data: orgsData } = useQuery({
    queryKey: ['organizations'],
    queryFn: () => organizationsApi.list(),
  });

  // 项目列表：作用域是当前组织；currentOrgId 为 null 时不传 organization_id，
  // 此时后端按“全部可见项目”返回。
  const { data: projectsData } = useQuery({
    queryKey: ['projects', { orgId: currentOrgId }],
    queryFn: () =>
      projectsApi.list({
        page: 1,
        page_size: 100,
        organization_id: currentOrgId ?? undefined,
      }),
  });

  const orgs = orgsData?.items ?? []; // 组织候选项，未加载完时为 []
  const projects = projectsData?.items ?? []; // 项目候选项，未加载完或为空组织时为 []

  // 当前组织失效（被移除）时自动回退到第一个组织。
  // 必须在 effect 中回写，不能在渲染期间 setState。
  useEffect(() => {
    // 组织仍在候选列表中时不做任何处理，避免无谓的状态更新。
    if (
      currentOrgId !== null &&
      orgs.length > 0 &&
      !orgs.some((o) => o.id === currentOrgId)
    ) {
      setOrgId(orgs[0].id); // 回退会连带清空项目作用域
    }
  }, [currentOrgId, orgs, setOrgId]);

  // 分组展开态：惰性从 localStorage 恢复，用户折叠/展开后持久化。
  const [openKeys, setOpenKeys] = useState<string[]>(() => loadOpenKeys());

  useEffect(() => {
    try {
      window.localStorage.setItem(OPEN_KEYS_STORAGE, JSON.stringify(openKeys));
    } catch {
      // 写入失败（隐私模式、配额满）时静默忽略，不影响菜单交互。
    }
  }, [openKeys]);

  // 高亮当前菜单：先在全部 key（含分组父 key 与叶子）中精确匹配，
  // 再退化为最长前缀匹配（最长前缀优先，避免 '/console' 抢占 '/console/projects/123'）。
  const selectedMenuKey = useMemo(() => {
    if (ALL_MENU_KEYS.includes(location.pathname)) return location.pathname;
    const prefixes = ALL_MENU_KEYS.filter((k) =>
      location.pathname.startsWith(k + '/'),
    );
    if (prefixes.length > 0) {
      return prefixes.reduce((a, b) => (b.length > a.length ? b : a));
    }
    // 都不是时默认高亮工作台，避免菜单全灰。
    return '/console';
  }, [location.pathname]);

  // 路由变化时自动展开所属分组，保证深链进入子页时分组处于展开态。
  // 已在展开列表中时返回原数组引用，避免无谓的重渲染。
  useEffect(() => {
    const groupKey = GROUP_OF_LEAF[selectedMenuKey];
    if (!groupKey) return;
    setOpenKeys((prev) => (prev.includes(groupKey) ? prev : [...prev, groupKey]));
  }, [selectedMenuKey]);

  // 面包屑：命中分组子项时展示「控制台 / 分组名 / 页面名」三级，其余两段。
  // 页面名走 matchRouteTitle，动态子路由（报告详情等）与列表页标题可区分。
  const breadcrumbItems = useMemo(() => {
    const items: { title: string }[] = [{ title: '控制台' }];
    const currentTitle = matchRouteTitle(location.pathname) ?? '工作台';
    const group = MENU_ITEMS.find(
      (i): i is MenuGroup =>
        'children' in i && i.children.some((c) => c.key === selectedMenuKey),
    );
    if (group) items.push({ title: group.label });
    items.push({ title: currentTitle });
    return items;
  }, [location.pathname, selectedMenuKey]);

  // 顶部用户菜单：个人中心与退出登录两个可操作项。
  const userMenu = {
    items: [
      {
        key: 'profile',
        icon: <UserOutlined />,
        label: '个人中心',
        onClick: () => navigate('/console/profile'),
      },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: async () => {
          await logout(); // 登出接口失败也会清除本地态
          navigate('/login', { replace: true }); // replace 避免登录页留在历史中
        },
      },
    ],
  };

  // 顶部两个选择器都开启按名称搜索（showSearch + optionFilterProp="label"）；
  // 项目选择器额外 allowClear，清空后回到“不限定项目”的作用域。
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme={darkMode ? 'dark' : 'light'} width={220} breakpoint="lg">
        <div
          style={{
            height: 56,
            // 深色侧栏用白色文字，浅色侧栏改用 token 正文色：
            // 侧栏改浅底后若仍是 #fff 会白字压白底直接消失。
            color: darkMode ? themeToken.colorTextLightSolid : themeToken.colorText,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 600,
            fontSize: 15,
          }}
        >
          用户控制台
        </div>
        <Menu
          theme={darkMode ? 'dark' : 'light'}
          mode="inline"
          selectedKeys={[selectedMenuKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={MENU_ITEMS.map((item) => {
            if ('children' in item) {
              // 分组父节点：不包 Link（无对应路由），仅作为可展开容器；叶子项包 Link。
              return {
                key: item.key,
                icon: item.icon,
                label: item.label,
                children: item.children.map((c) => ({
                  key: c.key,
                  icon: c.icon,
                  label: <Link to={c.key}>{c.label}</Link>,
                })),
              };
            }
            return {
              key: item.key,
              icon: item.icon,
              label: <Link to={item.key}>{item.label}</Link>,
            };
          })}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: themeToken.colorBgContainer,
            padding: '0 24px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderBottom: `1px solid ${themeToken.colorBorderSecondary}`,
            gap: 16,
          }}
        >
          {/* 窄屏时两个选择器按视口宽度收窄（min()），并允许整体换行，避免挤爆顶部栏 */}
          <Flex wrap="wrap" gap="middle" align="center" style={{ flex: 1, minWidth: 0 }}>
            <Select
              style={{ width: 'min(180px, 36vw)' }}
              placeholder="选择组织"
              value={currentOrgId ?? undefined}
              onChange={(v) => {
                setOrgId(v); // 切换组织
                setProjectId(null); // 组织变了，原项目选择已无意义
              }}
              options={orgs.map((o) => ({ value: o.id, label: o.name }))}
              showSearch
              optionFilterProp="label"
            />
            <Select
              style={{ width: 'min(220px, 44vw)' }}
              placeholder="选择项目"
              value={currentProjectId ?? undefined}
              onChange={(v) => setProjectId(v)}
              options={projects.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
              showSearch
              optionFilterProp="label"
              allowClear
            />
          </Flex>
          <Flex gap="middle" align="center">
            <TaskSchedulerDrawer />
            <Dropdown menu={userMenu} placement="bottomRight">
              <Flex gap="small" style={{ cursor: 'pointer' }}>
                <Avatar icon={<UserOutlined />} />
                <span>{user?.username}</span>
              </Flex>
            </Dropdown>
          </Flex>
        </Header>
        <Content style={{ background: themeToken.colorBgLayout }}>
          <div style={{ padding: '16px 24px 0' }}>
            <Breadcrumb items={breadcrumbItems} />
          </div>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
