// 登录页。登录后跳转安全校验过的 query.redirect，否则进入用户工作台。
// 本模块导出 LoginPage，由路由 /login 挂载；登录成功后写入全局登录态。
import { App, Button, Form, Input, Typography } from 'antd';
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { safeInternalPath } from '@/utils/safeRedirect';
import { AuthFrame } from './AuthFrame';

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
 *       再按安全的 query.redirect 跳转，默认进入用户工作台。
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
   * 表单提交：调用 useAuth().login 建立登录态，再按 redirect 或默认工作台跳转。
   * 异常全部折叠为同一句提示，不区分账号不存在与密码错误，避免泄露账号是否存在。
   */
  const onSubmit = async (values: LoginForm) => {
    setLoading(true);
    try {
      // 返回登录用户对象，其中的 role 决定后续落地页
      await login(values.username, values.password);
      // 记录被登录页拦截前的原始路径，登录成功后回到那里
      const redirect = params.get('redirect');
      // 反斜杠也可能被路由库解析为外部跳转分隔符，统一交给站内路径校验器。
      const target = safeInternalPath(redirect);
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
    <AuthFrame>
      <div className="auth-form-body">
        <div className="auth-eyebrow">ACCOUNT ACCESS</div>
        <Typography.Title level={2} className="auth-form-title">
          欢迎回来
        </Typography.Title>
        <Typography.Text className="auth-form-subtitle">
          登录后继续管理项目与测试工作
        </Typography.Text>
        <Form<LoginForm>
          className="auth-form"
          layout="vertical"
          onFinish={onSubmit}
          requiredMark={false}
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              size="large"
              prefix={<UserOutlined />}
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </Form.Item>
          <Button
            className="auth-submit"
            type="primary"
            htmlType="submit"
            block
            size="large"
            loading={loading}
          >
            登录平台
          </Button>
        </Form>
        <div className="auth-footer">
          还没有账号？<Link to="/register">立即注册</Link>
        </div>
      </div>
      <div className="auth-security-note">
        <SafetyCertificateOutlined />
        <span>平台账号统一认证，登录信息受安全保护</span>
      </div>
    </AuthFrame>
  );
}
