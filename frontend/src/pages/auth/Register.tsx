// 自助注册页。注册即创建个人组织（后端规则），成功后后端直接返回 token，前端
// 写入 tokenStore 后跳转到 /console（或 /admin/dashboard 若为 admin）；无需再走 login。
// 页面包含图形验证码：图片点击进入时自动刷新；验证码错误 / 过期会清空 challenge_id
// 并刷新图片，用户重新输入。
import { App, Button, Card, Form, Input, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { captchaApi } from '@/api/captcha';
import { useAuth } from '@/hooks/useAuth';
import { getErrorMessage } from '@/api/client';

/** 注册表单的数据结构。 */
interface RegisterForm {
  username: string; // 3-50 字符，后端唯一
  password: string; // 至少 6 位
  confirm: string; // 仅前端比对
  captcha: string; // 用户从图片上读出的字符
}

/**
 * 自助注册页组件。
 *
 * 会发请求：
 *   1) 挂载时调用 captchaApi.issue() 拿到 challenge_id + 图片；
 *   2) 提交时调用 useAuth().register（自动写 token 与 user 缓存）。
 * 失败呈现：验证码错误或过期 → 提示并自动刷新图片；其他错误 → 折叠为「注册失败，用户名可能已存在」。
 * 成功跳转：/console（test/dev 角色）或 /admin/dashboard（admin 角色）。
 */
export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  // 验证码状态：challenge_id 是提交时回传给后端的关键；image_base64 直接作为 <img src>。
  // refresh 是递增 nonce：图片加载失败的兜底，点击图片也会用它强制重新签发。
  const [challengeId, setChallengeId] = useState('');
  const [imageBase64, setImageBase64] = useState('');
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const [captchaNonce, setCaptchaNonce] = useState(0);

  /** 拉取一张新的验证码；出错不阻塞注册，只清空状态。 */
  useEffect(() => {
    let cancelled = false;
    setCaptchaLoading(true);
    captchaApi
      .issue()
      .then((res) => {
        if (cancelled) return;
        setChallengeId(res.challenge_id);
        setImageBase64(res.image_base64);
      })
      .catch(() => {
        if (cancelled) return;
        setChallengeId('');
        setImageBase64('');
      })
      .finally(() => {
        if (!cancelled) setCaptchaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [captchaNonce]);

  /** 点击图片刷新：递增 nonce 触发 useEffect 重新拉取，同时清空输入框。 */
  const refreshCaptcha = () => {
    setCaptchaNonce((n) => n + 1);
  };

  const onSubmit = async (values: RegisterForm) => {
    // 前端先做二次确认比对，减少一次注定失败的网络往返。
    if (values.password !== values.confirm) {
      message.error('两次输入的密码不一致');
      return;
    }
    if (!challengeId) {
      // 极端情况：验证码尚未签发成功。提示用户刷新后再试。
      message.error('验证码尚未加载完成，请刷新后重试');
      refreshCaptcha();
      return;
    }
    setLoading(true);
    try {
      // 注册成功：后端已经把 token 写入 tokenStore，直接用 user 决定跳转。
      const user = await register(
        values.username,
        values.password,
        challengeId,
        values.captcha,
      );
      message.success('注册成功');
      // admin 直跳管理端首页；其余用户进控制台。
      navigate(
        user.role === 'admin' ? '/admin/dashboard' : '/console',
        { replace: true },
      );
    } catch (err) {
      // 区分验证码错误与其他错误：后端 400 且 message 命中「验证码」时刷新图片。
      const raw = (err as { response?: { status: number; data?: { code?: string; message?: string } } }).response;
      const status = raw?.status ?? 0;
      const msg = raw?.data?.message ?? '';
      const code = raw?.data?.code ?? '';
      if (status === 400 && (msg.includes('验证码') || code === 'ERR_BAD_REQUEST')) {
        message.error('验证码错误或已过期，请重新输入');
        refreshCaptcha();
      } else {
        // 用户名已存在（409）、密码不合规（400/422）、限流（429）等，统一折叠提示。
        message.error(getErrorMessage(err, '注册失败'));
      }
    } finally {
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
      <Card style={{ width: 420 }}>
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>
          注册新账号
        </Typography.Title>
        <Form<RegisterForm> layout="vertical" onFinish={onSubmit}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, max: 50, message: '用户名 3-50 个字符' },
            ]}
          >
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: '请输入密码' },
              { min: 6, max: 100, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认密码"
            rules={[{ required: true, message: '请再次输入密码' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="captcha"
            label="验证码"
            rules={[
              { required: true, message: '请输入验证码' },
              { len: 5, message: '验证码长度应为 5 位' },
            ]}
          >
            {/* 图片与输入框并排：右侧点击图片刷新；加载中显示占位图 */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Input
                placeholder="输入图片中的字符"
                style={{ flex: 1 }}
                maxLength={5}
              />
              {captchaLoading || !imageBase64 ? (
                <div
                  style={{
                    width: 120,
                    height: 40,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: '#fafafa',
                    border: '1px solid #d9d9d9',
                    color: '#999',
                    fontSize: 12,
                  }}
                >
                  加载中...
                </div>
              ) : (
                <img
                  src={imageBase64}
                  alt="验证码"
                  onClick={refreshCaptcha}
                  title="点击刷新"
                  style={{
                    width: 120,
                    height: 40,
                    cursor: 'pointer',
                    userSelect: 'none',
                    border: '1px solid #d9d9d9',
                  }}
                />
              )}
            </div>
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            注册
          </Button>
        </Form>
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          已有账号？<a onClick={() => navigate('/login')}>去登录</a>
        </div>
      </Card>
    </div>
  );
}
