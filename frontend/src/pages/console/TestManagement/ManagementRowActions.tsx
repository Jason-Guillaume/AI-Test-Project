import { App, Button, Dropdown, Space } from 'antd';
import { EditOutlined } from '@ant-design/icons';

export function ManagementRowActions({ onEdit, manageLabel, onManage, deleteTitle, onDelete }: {
  onEdit: () => void;
  manageLabel: string;
  onManage: () => void;
  deleteTitle: string;
  onDelete: () => Promise<unknown>;
}) {
  const { modal } = App.useApp();
  return (
    <Space size={4}>
      <Button size="small" icon={<EditOutlined />} onClick={onEdit}>编辑</Button>
      <Dropdown trigger={['click']} menu={{ items: [
        { key: 'manage', label: manageLabel, onClick: onManage },
        { key: 'delete', label: '删除', danger: true, onClick: () => modal.confirm({
          title: deleteTitle, okText: '删除', okType: 'danger', onOk: onDelete,
        }) },
      ] }}>
        <Button size="small">更多操作</Button>
      </Dropdown>
    </Space>
  );
}
