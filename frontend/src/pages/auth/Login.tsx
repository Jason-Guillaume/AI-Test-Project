// 登录页。登录后跳转 query.redirect（经过安全校验）或按角色进入管理端/控制台。
// 本模块导出 LoginPage，由路由 /login 挂载；登录成功后写入全局登录态。
import { App, Button, Card, Form, Input, Typography } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';

/**
 * 登录表单的数据结构，对应提交给后端 /login 的字段。
 */
interface LoginForm {
  // 用户名，后端按 username 唯一键查找账号
  username: string;
  // 明文密码，仅随本次请求发送，前端不做任何持久化
  password: string;
}

/**
 * 登录页组件。
 *
 * 用途：提供用户名/密码表单，提交后调用 useAuth().login 建立登录态，
 *       再按 query.redirect 或用户角色跳转。
 * 数据来源：不发独立请求，完全依赖 useAuth().login 内部的网络调用。
 * 失败呈现：捕获异常后统一 message.error 提示「用户名或密码错误」，
 *       不区分账号不存在/密码错误，避免泄露账号是否存在。
 * 空态：表单无数据即空态，由 antd Form 的 rules 就地提示必填项。
 */
export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  // redirect 从地址栏 query 读取，由 useSearchParams 暴露为 URLSearchParams
  const [params] = useSearchParams();
  const { message } = App.useApp();
  // 提交进行中标记：驱动按钮 loading，同时防止用户重复点击
  const [loading, setLoading] = useState(false);

  /**
   * 表单提交：调用 useAuth().login 建立登录态，再按 redirect 或角色跳转。
   * 异常全部折叠为同一句提示，不区分账号不存在与密码错误，避免泄露账号是否存在。
   */
  const onSubmit = async (values: LoginForm) => {
    setLoading(true);
    try {
      // 返回登录用户对象，其中的 role 决定后续落地页
      const user = await login(values.username, values.password);
      // 记录被登录页拦截前的原始路径，登录成功后回到那里
      const redirect = params.get('redirect');
      // 安全校验：只接受同源相对路径；必须以单个 / 开头，且不能以 // 开头
      // （//evil.com 会被浏览器解析成协议相对 URL，等价于跳转外部域名）
      const safe =
        redirect && redirect.startsWith('/') && !redirect.startsWith('//');
      // 优先跳回 redirect；redirect 缺失或不合法时按角色分派：
      // admin 进管理端 /admin/dashboard，其余角色进用户控制台 /console
      const target = safe
        ? redirect
        : user.role === 'admin'
          ? '/admin/dashboard'
          : '/console';
      message.success('登录成功');
      // replace: true 把登录页从历史栈中抹掉，避免返回键再次回到登录页
      navigate(target, { replace: true });
    } catch {
      // 后端 400/401 一律折叠成同一句提示，避免通过文案差异泄露账号是否存在
      message.error('用户名或密码错误');
    } finally {
      // 无论成败都复位 loading，否则按钮会永久卡在转圈状态
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
      }}
    >
      <Card style={{ width: 380 }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>
          测试开发平台
        </Typography.Title>
        <Form<LoginForm> /* onFinish 收到的是已通过 rules 校验的表单值，可直接提交 */ layout="vertical" onFinish={onSubmit}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input /* autoComplete 提示浏览器自动填充用户名 */ autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password /* current-password 表示这是已存在账号的登录密码 */ autoComplete="current-password" />
          </Form.Item>
          <Button /* block 撑满卡片宽度；loading 复用上面的 loading 状态 */ type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>
        <div /* 提供从登录页跳到注册页的入口，走前端路由不刷新页面 */ style={{ textAlign: 'center', marginTop: 16 }}>
          还没有账号？<a onClick={() => navigate('/register')}>立即注册</a>
        </div>
      </Card>
    </div>
  );
}
