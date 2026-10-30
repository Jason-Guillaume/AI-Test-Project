// Axios 会话竞态回归，使用请求适配器模拟延迟响应，不连接后端或外部服务。
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { AxiosError, CanceledError } from 'axios';

/** 提供最小 localStorage 替身，测试不读取或写入用户真实浏览器数据。 */
function installStorageStub() {
  const values = new Map();
  globalThis.localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

/** 延迟一个写请求，身份切换后确认其成功响应不会被旧组件接收。 */
test('迟到的写请求响应在身份变化后被屏蔽', async () => {
  installStorageStub();
  const [{ client }, lifecycle] = await Promise.all([
    import('../src/shared/api/client.ts'),
    import('../src/shared/session/sessionLifecycle.mjs'),
  ]);
  let resolveAdapter;
  const pending = client.post('/example', {}, {
    adapter: (config) => new Promise((resolve) => { resolveAdapter = () => resolve({
      config,
      data: { ok: true },
      status: 200,
      statusText: 'OK',
      headers: {},
    }); }),
  });
  await new Promise((resolve) => setImmediate(resolve));
  lifecycle.transitionSession('logout');
  resolveAdapter();

  await assert.rejects(pending, (error) => error instanceof CanceledError);
});

/** 验证登录表单的凭据错误不会触发全局会话失效导航。 */
test('登录接口的 401 保留为表单错误', async () => {
  installStorageStub();
  const [{ client, registerAuthExpiredHandler }, lifecycle] = await Promise.all([
    import('../src/shared/api/client.ts'),
    import('../src/shared/session/sessionLifecycle.mjs'),
  ]);
  let redirects = 0;
  const unregister = registerAuthExpiredHandler(() => { redirects += 1; });
  const generation = lifecycle.getSessionGeneration();
  await assert.rejects(client.post('/session/login', {}, {
    adapter: async (config) => {
      const response = {
        config,
        data: { code: 'ERR_AUTH', message: '用户名或密码错误', request_id: 'test' },
        status: 401,
        statusText: 'Unauthorized',
        headers: {},
      };
      throw new AxiosError('登录失败', 'ERR_BAD_REQUEST', config, {}, response);
    },
  }));
  unregister();

  assert.equal(redirects, 0);
  assert.equal(lifecycle.getSessionGeneration(), generation);
});
