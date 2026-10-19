// 用户控制台布局：左侧菜单 + 顶部组织/项目选择器与用户菜单。
// 不在此处做鉴权（由 RequireAuth 守卫完成）；也不在此处请求项目/组织之外的数据。
import {
  Avatar,
  Breadcrumb,
  Dropdown,
  Layout,
  Menu,
  Select,
  Space,
  theme,
} from 'antd';
import {
  ApiOutlined,
  AppstoreOutlined,
  BellOutlined,
  BlockOutlined,
  BugOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  RobotOutlined,
  HistoryOutlined,
  LogoutOutlined,
  PartitionOutlined,
  ProjectOutlined,
  SafetyOutlined,
  ScheduleOutlined,
  SendOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, type ReactNode } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/hooks/useAuth';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { organizationsApi } from '@/api/organizations';
import { projectsApi } from '@/api/projects';

// antd Layout 子部件解构：侧边栏、头部、内容区。
const { Header, Sider, Content } = Layout;

// 控制台左侧导航项：key 与 App.tsx 的路由 path 保持一致，
// 用于 selectedKeys 高亮以及跳转目标。
// 测试管理为分组（SubMenu）：父节点 key 无对应路由，仅展开；叶子项才包 Link 跳转。
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

const MENU_ITEMS: MenuItem[] = [
  { key: '/console', icon: <AppstoreOutlined />, label: '工作台' }, // 工作台
  { key: '/console/projects', icon: <ProjectOutlined />, label: '我的项目' }, // 我的项目
  { key: '/console/defects', icon: <BugOutlined />, label: '缺陷管理' }, // 缺陷管理
  { key: '/console/api-catalog', icon: <ApiOutlined />, label: '接口管理' }, // 接口管理
  { key: '/console/business-management', icon: <PartitionOutlined />, label: '业务管理' }, // 业务管理
  {
    key: '/console/test-management', // 测试管理（分组）
    icon: <ExperimentOutlined />,
    label: '测试管理',
    children: [
      { key: '/console/test-asset', icon: <FileTextOutlined />, label: '测试资产' },
      { key: '/console/test-suites', icon: <BlockOutlined />, label: '测试套件' },
      { key: '/console/test-plans', icon: <ScheduleOutlined />, label: '测试计划' },
      { key: '/console/execution-center', icon: <ThunderboltOutlined />, label: '执行中心' },
      { key: '/console/execution-history', icon: <HistoryOutlined />, label: '执行历史' },
      { key: '/console/test-reports', icon: <FileTextOutlined />, label: '测试报告' },
      { key: '/console/notification-channels', icon: <SendOutlined />, label: '飞书通知' },
      { key: '/console/test-data', icon: <DatabaseOutlined />, label: '测试数据' },
      { key: '/console/security-testing', icon: <SafetyOutlined />, label: '安全测试' },
    ],
  },
  { key: '/console/agent', icon: <RobotOutlined />, label: '接口测试 Agent' }, // 接口测试 Agent
  { key: '/console/notifications', icon: <BellOutlined />, label: '通知中心' }, // 通知中心
  { key: '/console/profile', icon: <UserOutlined />, label: '个人中心' }, // 个人中心
];

// 所有可命中菜单 key（含子菜单叶子），用于 selectedMenuKey 的精确/前缀匹配。
const ALL_MENU_KEYS: string[] = (() => {
  const keys: string[] = [];
  for (const item of MENU_ITEMS) {
    keys.push(item.key);
    if ('children' in item) item.children.forEach((c) => keys.push(c.key));
  }
  return keys;
})();

// 面包屑用的路由标题映射；不在表中的路径由 breadcrumbItems 单独兜底。
const ROUTE_TITLES: Record<string, string> = {
  '/console': '工作台', // 工作台
  '/console/projects': '我的项目', // 我的项目
  '/console/defects': '缺陷管理', // 缺陷管理
  '/console/api-catalog': '接口管理', // 接口管理
  '/console/business-management': '业务管理', // 业务管理
  '/console/test-asset': '测试资产', // 测试资产
  '/console/test-suites': '测试套件', // 测试套件
  '/console/test-plans': '测试计划', // 测试计划
  '/console/execution-center': '执行中心', // 执行中心
  '/console/execution-history': '执行历史', // 执行历史
  '/console/test-reports': '测试报告', // 测试报告
  '/console/notification-channels': '飞书通知', // 飞书通知
  '/console/test-data': '测试数据', // 测试数据
  '/console/security-testing': '安全测试', // 安全测试
  '/console/agent': '接口测试 Agent', // 接口测试 Agent
  '/console/notifications': '通知中心', // 通知中心
  '/console/profile': '个人中心', // 个人中心
};

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

  // 高亮当前菜单：先在全部 key（含子菜单叶子）中精确匹配，再退化为最长前缀匹配
  // （最长前缀优先，避免 '/console' 抢占 '/console/projects/123' 的叶子项）。
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

  // 面包屑：命中分组子项时展示「控制台 / 分组名 / 叶子名」三级；其余按标题表兜底。
  const breadcrumbItems = useMemo(() => {
    const items: { title: string }[] = [{ title: '控制台' }];
    const group = MENU_ITEMS.find(
      (i): i is MenuGroup =>
        'children' in i && i.children.some((c) => c.key === selectedMenuKey),
    );
    if (group) {
      const child = group.children.find((c) => c.key === selectedMenuKey);
      items.push({ title: group.label });
      if (child) items.push({ title: child.label });
    } else if (location.pathname.startsWith('/console/projects/')) {
      items.push({ title: '项目详情' });
    } else {
      items.push({ title: ROUTE_TITLES[selectedMenuKey] ?? '工作台' });
    }
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
      <Sider theme="dark" width={220} breakpoint="lg">
        <div
          style={{
            height: 56,
            color: '#fff',
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
          theme="dark"
          mode="inline"
          selectedKeys={[selectedMenuKey]}
          // 测试管理分组默认展开；命中子项时 antd 会自动展开其父级。
          defaultOpenKeys={['/console/test-management']}
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
          <Space size="large">
            <Select
              style={{ width: 180 }}
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
              style={{ width: 220 }}
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
          </Space>
          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} />
              <span>{user?.username}</span>
            </Space>
          </Dropdown>
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
