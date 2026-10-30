// 结构化 UI 步骤编辑器：固定操作和定位字段，禁止原始脚本。
import { App, Button, Card, Checkbox, Col, Form, Input, InputNumber, Row, Select, Space, Upload } from 'antd';
import type { WebPage, WebStep } from '@/features/web-testing/contracts';


export const LOCATORS = [
  { value: 'TEST_ID', label: 'data-testid（优先）' }, { value: 'ROLE', label: 'Role + 名称' },
  { value: 'LABEL', label: 'Label' }, { value: 'TEXT', label: 'Text' },
  { value: 'CSS', label: 'CSS（兜底）' }, { value: 'XPATH', label: 'XPath（兜底）' },
];

/** 顺序编辑与重排 TestStep；文件上传只转成内存内容，不接受服务器路径。 */
export function StepEditor({ pages }: { pages: WebPage[] }) {
  return <Form.List name="steps" rules={[{ validator: async (_, steps) => { if (!steps?.length) throw new Error('至少一个步骤'); } }]}>
    {(fields, { add, remove, move }, { errors }) => <Space direction="vertical" style={{ width: '100%' }}>
      {fields.map(({ key, name, ...rest }, index) => <Card className="web-step-card" size="small" key={key} title={`步骤 ${index + 1}`} extra={<Space>
        <Button size="small" disabled={index === 0} onClick={() => move(index, index - 1)}>上移</Button>
        <Button size="small" disabled={index === fields.length - 1} onClick={() => move(index, index + 1)}>下移</Button>
        <Button danger size="small" onClick={() => remove(name)}>删除</Button>
      </Space>}>
        <Row gutter={12}>
          <Col xs={24} sm={12} lg={8}><Form.Item {...rest} name={[name, 'name']} label="步骤名" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'operation']} label="操作" rules={[{ required: true }]}><Select options={['NAVIGATE', 'CLICK', 'FILL', 'SELECT', 'UPLOAD', 'WAIT', 'ASSERT'].map(value => ({ value, label: value }))} /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'timeout_ms']} label="步骤超时(ms)"><InputNumber min={100} max={60000} style={{ width: '100%' }} /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'locator', 'strategy']} label="定位策略"><Select options={LOCATORS} /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'locator', 'value']} label="定位值"><Input placeholder="testid / role / label / text" /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'locator', 'name']} label="Role 可访问名称"><Input /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name={[name, 'page_object_id']} label="或引用页面对象"><Select allowClear options={pages.map(p => ({ value: p.id, label: p.name }))} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name={[name, 'element_key']} label="页面元素 key"><Input placeholder="页面对象中的稳定命名元素" /></Form.Item></Col>
          <Col xs={24} lg={16}><Form.Item name={[name, 'value']} label="导航地址 / 输入值 / 选项值"><Input placeholder="/login 或 ${data.auth_username} / ${fixture.KEY.output}" /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'sensitive']} label="敏感信息" valuePropName="checked"><Checkbox>遮罩元素、使用变量填入</Checkbox></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'assertion']} label="断言来源"><Select options={['TEXT', 'VALUE', 'VISIBLE', 'COUNT', 'URL', 'TITLE'].map(value => ({ value }))} /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'operator']} label="比较方式"><Select options={['EQ', 'NE', 'CONTAINS', 'GT', 'GE', 'LT', 'LE'].map(value => ({ value }))} /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'expected']} label="期望值"><Input placeholder="可见性填 True / False" /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'wait_state']} label="WAIT 目标状态"><Select options={['visible', 'hidden', 'attached', 'detached'].map(value => ({ value }))} /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'output_variable']} label="断言结果输出变量"><Input placeholder="供后续业务动作使用" /></Form.Item></Col>
          <Col xs={24} sm={12} lg={8}><Form.Item name={[name, 'upload']} label="UPLOAD 文件（≤1MiB）"><MemoryUpload /></Form.Item></Col>
        </Row>
      </Card>)}
      <Form.ErrorList errors={errors} />
      <Button block onClick={() => add({ name: '新步骤', operation: 'CLICK', locator: { strategy: 'TEST_ID', value: '' }, assertion: 'TEXT', operator: 'EQ', wait_state: 'visible' })}>添加结构化步骤</Button>
    </Space>}
  </Form.List>;
}


/** 文件以受控结构保存到步骤表单，不读取服务器路径；大文件在读取内存前拒绝。 */
function MemoryUpload({ value, onChange }: { value?: WebStep['upload']; onChange?: (value: WebStep['upload']) => void }) {
  const { message } = App.useApp();
  return <Upload maxCount={1} fileList={value ? [{ uid: value.name, name: value.name, status: 'done' }] : []}
    beforeUpload={file => {
      if (file.size > 1048576) { void message.error('上传文件不能超过 1MiB'); return Upload.LIST_IGNORE; }
      const reader = new FileReader();
      reader.onload = () => onChange?.({ name: file.name, mime_type: file.type || 'application/octet-stream', content_base64: String(reader.result).split(',')[1] ?? '' });
      reader.onerror = () => void message.error('文件读取失败');
      reader.readAsDataURL(file);
      return false;
    }} onRemove={() => { onChange?.(null); return true; }}><Button>选择上传文件</Button></Upload>;
}
