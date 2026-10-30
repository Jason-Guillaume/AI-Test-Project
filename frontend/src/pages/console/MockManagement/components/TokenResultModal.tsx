// Runtime Token 明文仅在新建/重置响应后一次性显示。
import { Alert, App, Button, Modal, Tag, Typography } from 'antd';
import { CopyOutlined, SafetyOutlined } from '@ant-design/icons';

export function TokenResultModal({
  token,
  serviceKey,
  projectId,
  title,
  onClose,
}: {
  token: string | null;
  serviceKey: string;
  projectId: number;
  title: string;
  onClose: () => void;
}) {
  const { message: msg } = App.useApp();
  return (
    <Modal
      title={title}
      open={token != null}
      closable={false}
      footer={[
        <Button key="copy" icon={<CopyOutlined />} onClick={() => { void navigator.clipboard.writeText(token!); msg.success('已复制到剪贴板'); }}>
          复制 Token
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>
          我已保存，关闭
        </Button>,
      ]}
      onCancel={onClose}
    >
      <Alert
        type="warning"
        showIcon
        icon={<SafetyOutlined />}
        message="Token 只显示这一次"
        description="平台只保存 Token 的哈希，明文关闭后无法再查看。请立即复制并配置到被测系统的 X-Mock-Token 请求头；丢失请点「重置 Token」重新生成（旧 Token 会立即失效）。"
      />
      <div style={{ margin: '12px 0 8px' }}>
        <Typography.Text type="secondary">service_key</Typography.Text>
        <div><Tag>{serviceKey}</Tag></div>
      </div>
      <Typography.Paragraph copyable={{ text: token ?? '' }} code style={{ fontSize: 13, wordBreak: 'break-all' }}>
        {token}
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message="被测系统调用地址"
        description={`\`/api/v1/mock/${projectId}/${serviceKey}/{path}\`（执行面不需要平台登录态）`}
      />
    </Modal>
  );
}

/** 新建 / 编辑 Mock 服务弹窗。 */
