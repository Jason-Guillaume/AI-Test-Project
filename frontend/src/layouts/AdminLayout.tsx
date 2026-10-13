// 平台管理端布局：左侧菜单 + 顶部用户菜单。仅平台管理员可进入。
// 真正的权限拦截由路由层的 RequireAdmin 完成，本组件只做展示与导航。
import { Layout, Menu, Dropdown, Avatar, Space, theme } from 'antd';
import {
  AppstoreOutlined,
  DashboardOutlined,
  CloudOutlined,
  ApiOutlined,
  ProjectOutlined,
  TeamOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useMemo } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { PlatformRoleTag } from '@/components/RoleTag';

// antd Layout 的子部件解构，用于组合侧边栏/头部/内容区。
const { Header, Sider, Content } = Layout;

/**
 * 左侧导航项配置：key 必须与 App.tsx 中的路由 path 完全一致，
 * 否则 selectedKeys 无法高亮当前菜单。
 */
const MENU_ITEMS = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '管理首页' }, // 管理首页
  { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' }, // 用户管理
  { key: '/admin/organizations', icon: <AppstoreOutlined />, label: '组织管理' }, // 组织管理
  { key: '/admin/projects', icon: <ProjectOutlined />, label: '项目管理' }, // 项目管理
  { key: '/admin/model-configs', icon: <ApiOutlined />, label: '模型配置' }, // 模型配置
  { key: '/admin/environments', icon: <CloudOutlined />, label: '环境配置' }, // 环境配置
];

/**
 * 平台管理端布局：左侧导航 + 顶部用户菜单 + 路由出口。
 *
 * 不发请求（不拉取任何数据）；只依赖 useAuth 的当前用户做展示与登出。
 * 空态：user 为 null 时用户名与角色标签不渲染，但布局照常展示，
 * 因为到达此处必然已通过 RequireAdmin 守卫。
 */
export function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth(); // 当前用户与登出操作
  const { token: themeToken } = theme.useToken(); // antd 设计令牌，用于边框等主题色

  // 高亮当前菜单：用前缀匹配，这样 /admin/users/123 也会高亮“用户管理”。
  const selectedKey = useMemo(() => {
    const match = MENU_ITEMS.find((item) =>
      location.pathname.startsWith(item.key),
    );
    // 未匹配到时回退到管理首页，避免出现全灰菜单。
    return match?.key ?? '/admin/dashboard';
  }, [location.pathname]);

  // 顶部用户菜单：角色为只读展示项（disabled），唯一可操作项是退出登录。
  const userMenu = {
    items: [
      {
        key: 'role',
        // 只读项：把角色展示为禁用菜单，提示其不可切换。
        label: (
          <span style={{ color: themeToken.colorTextDisabled }}>角色</span>
        ),
        disabled: true,
      },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: async () => {
          await logout(); // 先等后端登出接口完成，失败也会清除本地态
          navigate('/login', { replace: true }); // replace 避免登录页留在历史记录中
        },
      },
    ],
  };

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
          测试开发平台
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={MENU_ITEMS.map((item) => ({
            ...item,
            // 用 Link 替换纯文本，让菜单项走路由跳转而不是 href 刷新。
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
            justifyContent: 'flex-end',
            alignItems: 'center',
            borderBottom: `1px solid ${themeToken.colorBorderSecondary}`,
          }}
        >
          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} />
              <span>{user?.username}</span>
              {user && <PlatformRoleTag role={user.role} />}
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ background: themeToken.colorBgLayout }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
