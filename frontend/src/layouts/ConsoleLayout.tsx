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
  BugOutlined,
  LogoutOutlined,
  PartitionOutlined,
  ProjectOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/hooks/useAuth';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { organizationsApi } from '@/api/organizations';
import { projectsApi } from '@/api/projects';

// antd Layout 子部件解构：侧边栏、头部、内容区。
const { Header, Sider, Content } = Layout;

/**
 * 控制台左侧导航项：key 与 App.tsx 的路由 path 保持一致，
 * 用于 selectedKeys 高亮以及跳转目标。
 */
const MENU_ITEMS = [
  { key: '/console', icon: <AppstoreOutlined />, label: '工作台' }, // 工作台
  { key: '/console/projects', icon: <ProjectOutlined />, label: '我的项目' }, // 我的项目
  { key: '/console/defects', icon: <BugOutlined />, label: '缺陷管理' }, // 缺陷管理
  { key: '/console/api-catalog', icon: <ApiOutlined />, label: '接口管理' }, // 接口管理
  { key: '/console/business-management', icon: <PartitionOutlined />, label: '业务管理' }, // 业务管理
  { key: '/console/notifications', icon: <BellOutlined />, label: '通知中心' }, // 通知中心
  { key: '/console/profile', icon: <UserOutlined />, label: '个人中心' }, // 个人中心
];

// 面包屑用的路由标题映射；不在表中的路径由 breadcrumbTitle 单独兜底。
const ROUTE_TITLES: Record<string, string> = {
  '/console': '工作台', // 工作台
  '/console/projects': '我的项目', // 我的项目
  '/console/defects': '缺陷管理', // 缺陷管理
  '/console/api-catalog': '接口管理', // 接口管理
  '/console/business-management': '业务管理', // 业务管理
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

  // 高亮当前菜单：先精确匹配，再退化为前缀匹配（覆盖 /console/projects/123）。
  const selectedMenuKey = useMemo(() => {
    const exact = MENU_ITEMS.find((i) => i.key === location.pathname);
    if (exact) return exact.key;
    const prefix = MENU_ITEMS.find((i) =>
      location.pathname.startsWith(i.key + '/'),
    );
    // 都不是时默认高亮工作台，避免菜单全灰。
    return prefix?.key ?? '/console';
  }, [location.pathname]);

  // 面包屑末段标题：项目详情路由不在标题表中，需单独判断。
  const breadcrumbTitle = useMemo(() => {
    if (location.pathname.startsWith('/console/projects/')) {
      return '项目详情';
    }
    return ROUTE_TITLES[selectedMenuKey] ?? '工作台';
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
          items={MENU_ITEMS.map((item) => ({
            ...item,
            // 用 Link 替换纯文本，让菜单项走路由跳转而非整页刷新。
            label: <Link to={item.key}>{item.label}</Link>,
          }))}
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
            <Breadcrumb items={[{ title: '控制台' }, { title: breadcrumbTitle }]} />
          </div>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
