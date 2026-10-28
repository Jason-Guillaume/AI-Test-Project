// 接口管理顶部工具条：关键字 / 方法 / 状态过滤 + 新建接口 + 导入 + 导入记录。
// 纯受控组件，状态由页面持有；按钮回调触发页面级动作。
import { Button, Input, Select, Space } from 'antd';
import { DownloadOutlined, HistoryOutlined, PlusOutlined } from '@ant-design/icons';
import { API_STATUS_OPTIONS, METHOD_OPTIONS } from './constants';
import type { ApiStatus } from '@/types';

/**
 * 工具条。
 *
 * 所有过滤态与按钮回调由父级控制，本组件不持有状态、不发请求。
 */
export function ApiToolbar({
  keyword,
  setKeyword,
  method,
  setMethod,
  status,
  setStatus,
  onCreate,
  onImport,
  onShowRecords,
}: {
  keyword: string;
  setKeyword: (v: string) => void;
  method: string | undefined;
  setMethod: (v: string | undefined) => void;
  status: ApiStatus | undefined;
  setStatus: (v: ApiStatus | undefined) => void;
  onCreate: () => void;
  onImport: () => void;
  onShowRecords: () => void;
}) {
  return (
    <Space wrap align="center" style={{ marginBottom: 12 }}>
      <Input.Search
        placeholder="按接口名或路径搜索"
        allowClear
        enterButton
        style={{ maxWidth: 240 }}
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        onSearch={(v) => setKeyword(v)}
      />
      <Select
        placeholder="全部方法"
        allowClear
        options={METHOD_OPTIONS}
        value={method}
        onChange={(v: string | undefined) => setMethod(v)}
        style={{ minWidth: 120 }}
      />
      <Select
        placeholder="全部状态"
        allowClear
        options={API_STATUS_OPTIONS}
        value={status}
        onChange={(v: ApiStatus | undefined) => setStatus(v)}
        style={{ minWidth: 140 }}
      />
      <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
        新建接口
      </Button>
      <Button icon={<DownloadOutlined />} onClick={onImport}>
        导入
      </Button>
      <Button icon={<HistoryOutlined />} onClick={onShowRecords}>
        导入记录
      </Button>
    </Space>
  );
}
