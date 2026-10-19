// Web UI 编辑表单：页面对象、结构化用例与只写加密认证配置，关闭弹窗即释放表单内容。
import { Alert, Button, Col, Form, Input, InputNumber, Modal, Row, Select, Space } from 'antd';
import type { WebEnvironment, WebAuthProfile, WebCase, WebCaseInput, WebPage, WebPageInput } from '@/types';
import { LOCATORS, StepEditor } from '@/pages/console/WebUI/StepEditor';

/** 页面对象编辑；元素名称与稳定定位器集中维护。 */
export function PageEditor({ initial, busy, onSave, onClose }: {
  initial: WebPage | null; busy: boolean; onSave: (body: WebPageInput) => void; onClose: () => void;
}) {
  const [form] = Form.useForm<WebPageInput>();
  return <Modal open title={initial ? '编辑页面对象' : '新增页面对象'} width={850} onCancel={onClose} confirmLoading={busy} onOk={() => form.submit()} destroyOnClose>
    <Form form={form} layout="vertical" initialValues={initial ?? { path: '/', elements: [] }} onFinish={body => onSave({ ...body, revision: initial?.revision })}>
      <Form.Item name="name" label="页面名称" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="path" label="页面路径" rules={[{ required: true }]}><Input placeholder="/login" /></Form.Item>
      <Form.List name="elements">{(fields, { add, remove }) => <>
        {fields.map(({ key, name }) => <Row key={key} gutter={8}>
          <Col span={5}><Form.Item name={[name, 'key']} rules={[{ required: true }]}><Input placeholder="元素 key" /></Form.Item></Col>
          <Col span={6}><Form.Item name={[name, 'locator', 'strategy']} rules={[{ required: true }]}><Select options={LOCATORS} /></Form.Item></Col>
          <Col span={6}><Form.Item name={[name, 'locator', 'value']} rules={[{ required: true }]}><Input placeholder="定位值" /></Form.Item></Col>
          <Col span={5}><Form.Item name={[name, 'locator', 'name']}><Input placeholder="Role 名称" /></Form.Item></Col>
          <Col span={2}><Button danger onClick={() => remove(name)}>删</Button></Col>
        </Row>)}
        <Button onClick={() => add({ key: '', locator: { strategy: 'TEST_ID', value: '', exact: true } })}>添加页面元素</Button>
      </>}</Form.List>
    </Form>
  </Modal>;
}

/** 用例保存时清除空定位器；步骤顺序通过 Form.List 上移/下移维护。 */
export function CaseEditor({ initial, pages, auth, busy, onSave, onClose }: {
  initial: WebCase | null; pages: WebPage[]; auth: WebAuthProfile[]; busy: boolean;
  onSave: (body: WebCaseInput) => void; onClose: () => void;
}) {
  const [form] = Form.useForm<WebCaseInput>();
  return <Modal open title={initial ? `编辑 Web 用例 #${initial.id}` : '新增 Web 用例'} width={1100} onCancel={onClose} confirmLoading={busy} onOk={() => form.submit()} destroyOnClose>
    <Alert type="info" showIcon message="保存会使旧确认失效。先审核全部步骤，再人工确认并调试；敏感值引用 ${data.auth_password} 等变量。" style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical" initialValues={initial ?? { timeout_ms: 30000, total_timeout_ms: 120000, steps: [{ name: '打开页面', operation: 'NAVIGATE', value: '/' }] }}
      onFinish={body => onSave({ ...body, revision: initial?.revision, auth_profile_id: body.auth_profile_id ?? null,
        steps: body.steps.map(s => ({ ...s, locator: s.locator?.value?.trim() ? s.locator : null })) })}>
      <Row gutter={12}>
        <Col span={12}><Form.Item name="name" label="用例名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
        <Col span={12}><Form.Item name="auth_profile_id" label="登录态 / 测试账号"><Select allowClear options={auth.map(a => ({ value: a.id, label: a.name }))} /></Form.Item></Col>
        <Col span={12}><Form.Item name="timeout_ms" label="默认步骤超时(ms)"><InputNumber min={100} max={60000} /></Form.Item></Col>
        <Col span={12}><Form.Item name="total_timeout_ms" label="用例总超时(ms)"><InputNumber min={1000} max={600000} /></Form.Item></Col>
      </Row>
      <Form.Item name="description" label="描述"><Input.TextArea /></Form.Item>
      <StepEditor pages={pages} />
    </Form>
  </Modal>;
}

/** 密码、Cookie、LocalStorage/JWT 只写；编辑意味着整体替换，永不读取历史明文。 */
export function AuthEditor({ initial, environments, busy, onSave, onClose }: {
  initial: WebAuthProfile | null; environments: WebEnvironment[]; busy: boolean;
  onSave: (body: unknown) => void; onClose: () => void;
}) {
  const [form] = Form.useForm();
  return <Modal open title={initial ? '替换认证配置（完整填写）' : '新增认证配置'} width={760} onCancel={onClose} confirmLoading={busy} onOk={() => form.submit()} destroyOnClose>
    <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type="info" showIcon message="支持测试账号、Cookie、Local Storage、JWT。飞书扫码请在人工浏览器完成登录，再导入该测试环境的 Playwright storage_state。凭据加密保存，历史值不回显。" />
      <Form form={form} layout="vertical" style={{ width: '100%' }} initialValues={{ name: initial?.name, environment_id: initial?.environment_id, storage_json: '{"cookies":[],"origins":[]}', jwt_storage_key: 'access_token', ttl_hours: 24 }}
        onFinish={body => { const { storage_json, ttl_hours, ...rest } = body; onSave({ ...rest, storage_state: JSON.parse(storage_json), expires_at: new Date(Date.now() + ttl_hours * 3600000).toISOString() }); }}>
        <Row gutter={12}>
          <Col span={12}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col span={12}><Form.Item name="environment_id" label="绑定环境" rules={[{ required: true }]}><Select options={environments.map(e => ({ value: e.id, label: `${e.display_name || e.name}（${e.name}）` }))} /></Form.Item></Col>
          <Col span={12}><Form.Item name="username" label="测试用户名"><Input autoComplete="off" /></Form.Item></Col>
          <Col span={12}><Form.Item name="password" label="测试密码"><Input.Password autoComplete="new-password" /></Form.Item></Col>
          <Col span={12}><Form.Item name="jwt" label="JWT"><Input.Password autoComplete="off" /></Form.Item></Col>
          <Col span={12}><Form.Item name="jwt_storage_key" label="JWT Local Storage key"><Input placeholder="access_token" /></Form.Item></Col>
        </Row>
        <Form.Item name="storage_json" label="人工会话 storage_state（Cookie / Local Storage）" rules={[{ validator: async (_, value) => { try { JSON.parse(value); } catch { throw new Error('请输入合法 JSON'); } } }]}><Input.TextArea rows={6} autoComplete="off" /></Form.Item>
        <Form.Item name="ttl_hours" label="有效时长（小时，最多 30 天）"><InputNumber min={1} max={720} /></Form.Item>
      </Form>
    </Space>
  </Modal>;
}
