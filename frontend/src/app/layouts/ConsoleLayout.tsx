// 用户控制台布局：左侧菜单 + 顶部项目选择器与用户菜单。
// 不在此处做鉴权（由 RequireAuth 守卫完成）；也不在此处请求项目/组织之外的数据。
// 不做菜单级权限过滤：权限与路由逻辑保持现状，由路由守卫与页面自身控制。
import {
  Alert,
  Avatar,
  Button,
  Breadcrumb,
  Dropdown,
  Flex,
  Layout,
  Menu,
  Select,
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
  DeleteOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  ProfileOutlined,
  ExperimentOutlined,
  HistoryOutlined,
  AudioOutlined,
  LogoutOutlined,
  PartitionOutlined,
  PlayCircleOutlined,
  ProjectOutlined,
  RobotOutlined,
  SafetyOutlined,
  ScheduleOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/app/providers/AuthProvider';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { RouteErrorBoundary } from '@/app/router/AppErrorBoundary';
import { projectsApi } from '@/features/projects/api/projects';
import { collectPages } from '@/shared/api/pagination';
import { TaskSchedulerDrawer } from '@/widgets/task-assistant/TaskSchedulerDrawer';

// antd Layout 子部件解构：侧边栏、头部、内容区。
const { Header, Sider, Content } = Layout;

// 控制台左侧导航项：key 与 App.tsx 的路由 path 保持一致，
// 用于 selectedKeys 高亮以及跳转目标。
// 分组项仅作导航标题，叶子 key 与 App.tsx 的路由 path 保持一致。
interface MenuLeaf {
  type?: undefined;
  key: string;
  icon: ReactNode;
  label: string;
}
interface MenuSection {
  type: 'submenu';
  key: string;
  label: string;
  icon: ReactNode;
  children: MenuLeaf[];
}

// 六组导航保留所有既有专业页面地址；消息和个人中心位于顶栏菜单。
const BASE_MENU_ITEMS: MenuSection[] = [
  {
    type: 'submenu', key: 'workbench', label: '工作台', icon: <AppstoreOutlined />,
    children: [{ key: '/console', icon: <AppstoreOutlined />, label: '工作台首页' }],
  },
  {
    type: 'submenu', key: 'tasks', label: '任务', icon: <ScheduleOutlined />,
    children: [
      { key: '/console/tasks', icon: <ScheduleOutlined />, label: '统一任务' },
      { key: '/console/tasks/inbox', icon: <BellOutlined />, label: '待我处理' },
      { key: '/console/tasks/templates', icon: <FileTextOutlined />, label: '任务模板' },
      { key: '/console/agent', icon: <RobotOutlined />, label: 'AI 助手' },
    ],
  },
  {
    type: 'submenu', key: 'assets', label: '资产', icon: <BlockOutlined />,
    children: [
      { key: '/console/api-catalog', icon: <ApiOutlined />, label: '接口管理' },
      { key: '/console/business-management', icon: <PartitionOutlined />, label: '业务管理' },
      { key: '/console/test-asset', icon: <FileTextOutlined />, label: '测试资产' },
      { key: '/console/test-cases', icon: <ProfileOutlined />, label: '测试用例' },
      { key: '/console/asr/audio', icon: <AudioOutlined />, label: 'ASR 评测' },
      { key: '/console/test-suites', icon: <BlockOutlined />, label: '测试套件' },
      { key: '/console/test-plans', icon: <ScheduleOutlined />, label: '测试计划' },
      { key: '/console/web-ui', icon: <ChromeOutlined />, label: 'Web UI 工作区' },
      { key: '/console/security-testing', icon: <SafetyOutlined />, label: '安全测试工作区' },
      { key: '/console/test-data', icon: <DatabaseOutlined />, label: '测试数据' },
      { key: '/console/mock-management', icon: <CloudServerOutlined />, label: '接口 Mock' },
    ],
  },
  {
    type: 'submenu', key: 'results', label: '结果', icon: <HistoryOutlined />,
    children: [
      { key: '/console/execution-center', icon: <PlayCircleOutlined />, label: '执行中心' },
      { key: '/console/execution-history', icon: <HistoryOutlined />, label: '执行历史' },
      { key: '/console/test-reports', icon: <FileSearchOutlined />, label: '测试报告' },
      { key: '/console/defects', icon: <BugOutlined />, label: '缺陷管理' },
    ],
  },
  {
    type: 'submenu', key: 'automation-center', label: '自动化测试中心', icon: <ExperimentOutlined />,
    children: [
      { key: '/console/automation-projects', icon: <ProjectOutlined />, label: '自动化项目' },
      { key: '/console/automation-runs', icon: <PlayCircleOutlined />, label: '执行任务' },
      { key: '/console/automation-history', icon: <HistoryOutlined />, label: '执行历史' },
      { key: '/console/automation-integration', icon: <ApiOutlined />, label: '集成配置' },
    ],
  },
  {
    type: 'submenu', key: 'project-settings', label: '项目设置', icon: <ProjectOutlined />,
    children: [
      { key: '/console/projects', icon: <ProjectOutlined />, label: '项目管理' },
      { key: '/console/notification-channels', icon: <SendOutlined />, label: '通知渠道' },
      { key: '/console/recycle-bin', icon: <DeleteOutlined />, label: '回收站' },
    ],
  },
];

const ADMIN_MENU_ITEM: MenuSection = {
  type: 'submenu', key: 'management', label: '管理', icon: <AppstoreOutlined />,
  children: [{ key: '/admin/dashboard', icon: <AppstoreOutlined />, label: '管理后台' }],
};

// 面包屑用的路由标题映射；带 :param 的 key 是动态路由占位符，
// 由 matchRouteTitle 按路径段数匹配，不用于精确查找。
const ROUTE_TITLES: Record<string, string> = {
  '/console': '工作台', // 工作台
  '/console/projects': '项目管理', // 项目管理
  '/console/projects/:id': '项目详情', // 项目详情（动态）
  '/admin/dashboard': '管理后台',
  '/console/defects': '缺陷管理', // 缺陷管理
  '/console/api-catalog': '接口管理', // 接口管理
  '/console/business-management': '业务管理', // 业务管理
  '/console/test-asset': '测试资产', // 测试资产
  '/console/test-cases': '测试用例',
  '/console/test-suites': '测试套件', // 测试套件
  '/console/test-plans': '测试计划', // 测试计划
  '/console/execution-center': '执行中心', // 执行中心
  '/console/execution-history': '执行历史', // 执行历史
  '/console/test-reports': '测试报告', // 测试报告
  '/console/test-reports/:reportId': '报告详情', // 报告详情（动态，与列表页区分）
  '/console/automation-projects': '自动化项目',
  '/console/automation-runs': '执行任务',
  '/console/automation-history': '执行历史',
  '/console/automation-reports/:reportId': 'Allure 报告',
  '/console/automation-integration': '集成配置',
  '/console/mock-management': '接口 Mock', // 接口 Mock
  '/console/mock-management/services/:serviceId': '服务详情', // 服务详情（动态）
  '/console/mock-management/endpoints/:endpointId': '端点详情', // 端点详情（动态）
  '/console/mock-management/executions': '接口 Mock 执行', // 接口 Mock 执行
  '/console/web-ui': 'Web UI 工作区',
  '/console/web-ui-agent': '浏览器智能编写',
  '/console/security-testing': '安全测试工作区',
  '/console/asr/audio': '音频列表',
  '/console/asr/connections': '接口配置',
  '/console/asr/jobs': '评测任务',
  '/console/asr/jobs/:jobId': '评测任务详情',
  '/console/asr/comparisons': '识别结果对比',
  '/console/asr/comparisons/:comparisonId': '识别结果对比',
  '/console/asr/experiments': '参数对比',
  '/console/test-data': '测试数据', // 测试数据
  '/console/agent': 'AI 助手',
  '/console/tasks': '统一任务', // 全局任务列表
  '/console/tasks/inbox': '待我处理',
  '/console/tasks/templates': '任务模板',
  '/console/tasks/:taskId': '任务执行台', // 任务详情
  '/console/notifications': '消息中心',
  '/console/notification-channels': '通知渠道', // 通知渠道
  '/console/profile': '个人中心', // 个人中心
  '/console/recycle-bin': '回收站',
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
 * 用户控制台布局：左侧导航 + 按组织分组的项目选择器 + 面包屑 + 路由出口。
 *
 * 会发请求：拉取当前用户的全部可见项目，项目按所属组织分组。
 * 失败/空态：项目接口失败或列表为空时选择器展示占位，不阻塞子页面渲染。
 * 副作用：选择项目时自动同步所属组织作用域；无项目时清除旧组织作用域。
 */
export function ConsoleLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth(); // 当前用户与登出操作
  const { currentOrgId, setOrgId, currentProjectId, setProjectId } =
    useConsoleScope(); // 当前项目与其组织作用域
  const menuItems = useMemo(
    () => user?.role === 'admin' ? [...BASE_MENU_ITEMS, ADMIN_MENU_ITEM] : BASE_MENU_ITEMS,
    [user?.role],
  );
  const allMenuKeys = useMemo(
    () => menuItems.flatMap((section) => section.children.map((child) => child.key)),
    [menuItems],
  );
  const menuStorageKey = user?.id == null ? null : `console.menu-open-sections:${user.id}`;
  const [openMenuKeys, setOpenMenuKeys] = useState<string[]>([]);
  const initializedMenuForRef = useRef<string | null>(null);

  // 分页读取当前用户可见项目并限制收集规模；超限或请求失败时显示重试入口。
  const projectsQuery = useQuery({
    queryKey: ['projects', 'console-scope-options', user?.id],
    enabled: Boolean(user?.id),
    queryFn: ({ signal }) => collectPages((page) =>
      projectsApi.list({ page, page_size: 200 }, { signal }),
    ),
  });
  const projectsData = projectsQuery.data;

  const selectedMenuKey = useMemo(() => {
    if (location.pathname === '/console/web-ui-agent') return '/console/web-ui';
    if (location.pathname.startsWith('/console/asr/')) return '/console/asr/audio';
    if (allMenuKeys.includes(location.pathname)) return location.pathname;
    const prefixes = allMenuKeys.filter((key) => location.pathname.startsWith(`${key}/`));
    if (prefixes.length > 0) return prefixes.reduce((a, b) => b.length > a.length ? b : a);
    return '/console';
  }, [allMenuKeys, location.pathname]);
  const activeSectionKey = menuItems.find((section) =>
    section.children.some((child) => child.key === selectedMenuKey),
  )?.key ?? 'workbench';

  // 每个用户的分组展开状态独立记忆；首次进入时只展开当前路由所在组。
  useEffect(() => {
    if (!menuStorageKey || initializedMenuForRef.current === menuStorageKey) return;
    initializedMenuForRef.current = menuStorageKey;
    try {
      const raw = localStorage.getItem(menuStorageKey);
      const stored = raw == null ? [activeSectionKey] : JSON.parse(raw) as string[];
      setOpenMenuKeys(stored.filter((key) => menuItems.some((section) => section.key === key)));
    } catch {
      setOpenMenuKeys([activeSectionKey]);
    }
  }, [activeSectionKey, menuItems, menuStorageKey]);

  const handleMenuOpenChange = (keys: string[]) => {
    const valid = keys.filter((key) => menuItems.some((section) => section.key === key));
    setOpenMenuKeys(valid);
    if (!menuStorageKey) return;
    try { localStorage.setItem(menuStorageKey, JSON.stringify(valid)); } catch { /* storage may be disabled */ }
  };

  const projects = useMemo(() => projectsData?.items ?? [], [projectsData?.items]); // 项目候选项，未加载完或为空组织时为 []

  const projectOptions = useMemo(() => {
    const groups = new Map<
      string,
      { label: string; options: { value: number; label: string }[] }
    >();
    for (const project of projects) {
      const key =
        project.organization_id == null
          ? 'unassigned'
          : `organization-${project.organization_id}`;
      const label = project.organization_name ?? '未归属组织';
      const group = groups.get(key) ?? { label, options: [] };
      group.options.push({ value: project.id, label: project.name });
      groups.set(key, group);
    }
    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        options: group.options.sort((a, b) => a.label.localeCompare(b.label, 'zh-CN')),
      }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
  }, [projects]);

  // 组织不再由用户单独选择：恢复已保存项目后同步项目所属组织，
  // 若项目已不可见则清掉旧选择，避免其他用户或过期组织作用域残留。
  useEffect(() => {
    if (!projectsData) return;
    const selectedProject = projects.find((project) => project.id === currentProjectId);
    if (selectedProject) {
      if (currentOrgId !== selectedProject.organization_id) {
        setOrgId(selectedProject.organization_id);
      }
      return;
    }
    if (currentProjectId !== null) setProjectId(null);
    if (currentOrgId !== null) setOrgId(null);
  }, [projectsData, projects, currentOrgId, currentProjectId, setOrgId, setProjectId]);

  // 面包屑：命中分组子项时展示「控制台 / 分组名 / 页面名」三级，其余两段。
  // 页面名走 matchRouteTitle，动态子路由（报告详情等）与列表页标题可区分。
  const breadcrumbItems = useMemo(() => {
    const items: { title: string }[] = [{ title: '控制台' }];
    const currentTitle = matchRouteTitle(location.pathname) ?? '工作台';
    const group = menuItems.find((section) => section.children.some((child) => child.key === selectedMenuKey));
    if (group) items.push({ title: group.label });
    items.push({ title: currentTitle });
    return items;
  }, [location.pathname, menuItems, selectedMenuKey]);

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

  // 项目选择器按组织分组并可搜索；清空后回到不限定项目的作用域。
  return (
      <Layout className={`app-layout${location.pathname === '/console/agent' ? ' app-layout--workspace' : ''}`}>
      <Sider
        className="app-sidebar"
        theme="light"
        width={248}
        collapsedWidth={72}
        breakpoint="lg"
      >
        <div className="app-brand">
          <span className="app-brand-mark" aria-hidden="true">Q</span>
          <span className="app-brand-copy">
            <span className="app-brand-name">测试开发平台</span>
            <span className="app-brand-caption">QUALITY ENGINEERING</span>
          </span>
        </div>
        <Menu
          className="app-sidebar-menu"
          theme="light"
          mode="inline"
          openKeys={openMenuKeys}
          onOpenChange={handleMenuOpenChange}
          selectedKeys={[selectedMenuKey]}
          items={menuItems.map((item) => {
            return {
              key: item.key,
              label: item.label,
              icon: item.icon,
              children: item.children.map((child) => ({
                key: child.key,
                icon: child.icon,
                label: <Link to={child.key}>{child.label}</Link>,
              })),
            };
          })}
        />
        <div className="app-sidebar-profile">
          <Avatar size={34} icon={<UserOutlined />} />
          <span className="app-sidebar-profile-copy">
            <span>{user?.username ?? '用户'}</span>
            <small>{user?.role === 'admin' ? '平台管理员' : '测试工程师'}</small>
          </span>
        </div>
      </Sider>
      <Layout>
        <Header className="app-topbar">
          {/* 窄屏时项目选择器按视口宽度收窄，并允许整体换行 */}
          <Flex className="app-topbar-left" wrap="wrap" gap="middle" align="center">
            <Select
              className="app-scope-select"
              style={{ width: 'min(300px, 52vw)' }}
              placeholder="选择项目"
              loading={projectsQuery.isLoading}
              value={currentProjectId ?? undefined}
              onChange={(value) => {
                const project = projects.find((item) => item.id === value);
                setOrgId(project?.organization_id ?? null);
                setProjectId(value ?? null);
              }}
              options={projectOptions}
              showSearch
              optionFilterProp="label"
              allowClear
            />
            {projectsQuery.isError && (
              <Alert
                type="error"
                showIcon
                message="项目列表加载失败"
                action={<Button type="link" size="small" onClick={() => void projectsQuery.refetch()}>重试</Button>}
              />
            )}
          </Flex>
          <Flex className="app-topbar-actions" gap="small" align="center">
            <TaskSchedulerDrawer />
            {user?.role === 'admin' && (
              <Button
                icon={<AppstoreOutlined />}
                onClick={() => navigate('/admin/dashboard')}
              >
                管理后台
              </Button>
            )}
            <Button
              type="text"
              shape="circle"
              icon={<BellOutlined />}
              aria-label="通知中心"
              onClick={() => navigate('/console/notifications')}
            />
            <Dropdown menu={userMenu} placement="bottomRight">
              <Button type="text" className="app-user-trigger">
                <Avatar size={30} icon={<UserOutlined />} />
                <span>{user?.username}</span>
              </Button>
            </Dropdown>
          </Flex>
        </Header>
        <Content className="app-content">
          <div className="app-breadcrumb-wrap">
            <Breadcrumb className="app-breadcrumb" items={breadcrumbItems} />
          </div>
          <RouteErrorBoundary><Outlet /></RouteErrorBoundary>
        </Content>
      </Layout>
    </Layout>
  );
}
