// 自助注册页。注册即创建个人组织，成功后后端设置 HttpOnly Cookie 并自动登录。
import { App, Button, Form, Input, Typography } from 'antd';
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { getErrorMessage } from '@/api/client';
import { AuthFrame } from './AuthFrame';

/** 注册表单的数据结构。 */
interface RegisterForm {
  username: string; // 3-50 字符，后端唯一
  password: string; // 至少 6 位
  confirm: string; // 仅前端比对
}

/**
 * 自助注册页组件。
 *
 * 会发请求：提交时调用 useAuth().register（建立 Cookie 会话并缓存用户资料）。
 * 失败呈现：用户名、密码或限流错误统一显示后端错误文案。
 * 成功跳转：/console（test/dev 角色）或 /admin/dashboard（admin 角色）。
 */
export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  const onSubmit = async (values: RegisterForm) => {
    // 前端先做二次确认比对，减少一次注定失败的网络往返。
    if (values.password !== values.confirm) {
      message.error('两次输入的密码不一致');
      return;
    }
    setLoading(true);
    try {
      // 注册成功后后端已写入认证 Cookie，直接用用户角色决定跳转。
      const user = await register(values.username, values.password);
      message.success('注册成功');
      // admin 直跳管理端首页；其余用户进控制台。
      navigate(
        user.role === 'admin' ? '/admin/dashboard' : '/console',
        { replace: true },
      );
    } catch (err) {
      // 用户名已存在、密码不合规、限流等情况显示后端返回的错误文案。
      message.error(getErrorMessage(err, '注册失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthFrame variant="register">
      <div className="auth-form-body">
        <div className="auth-eyebrow">CREATE YOUR ACCOUNT</div>
        <Typography.Title level={2} className="auth-form-title">
          创建账号
        </Typography.Title>
        <Typography.Text className="auth-form-subtitle">
          完成注册后即可进入测试开发工作区
        </Typography.Text>
        <Form<RegisterForm>
          className="auth-form"
          layout="vertical"
          onFinish={onSubmit}
          requiredMark={false}
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, max: 50, message: '用户名 3-50 个字符' },
            ]}
          >
            <Input
              size="large"
              prefix={<UserOutlined />}
              placeholder="3–50 个字符"
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, max: 100, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="至少 6 位"
              autoComplete="new-password"
            />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认密码"
            rules={[{ required: true, message: '请再次输入密码' }]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="再次输入密码"
              autoComplete="new-password"
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
            创建账号
          </Button>
        </Form>
        <div className="auth-footer">
          已有账号？<Link to="/login">返回登录</Link>
        </div>
      </div>
      <div className="auth-security-note">
        <SafetyCertificateOutlined />
        <span>平台账号统一认证，登录信息受安全保护</span>
      </div>
    </AuthFrame>
  );
}
