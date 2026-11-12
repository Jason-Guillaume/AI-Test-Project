import { useEffect, useState } from 'react';
import { Alert, App, Button, Descriptions, Modal, Space, Table, Tag, Typography, Upload } from 'antd';
import type { UploadFile } from 'antd';
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import type { ScopeNode, TestCaseExcelImportPreview } from '@/features/test-management/contracts';
import { getErrorMessage } from '@/shared/api/client';

const DIRECTION_LABELS: Record<string, string> = { API: 'API 接口测试', UI: 'UI 界面测试', AI: 'AI 专项测试' };

export function CaseExcelImportModal({
  open, projectId, direction, scopeNodeId, scopeNode, onCancel, onSuccess,
}: {
  open: boolean;
  projectId: number;
  direction: string;
  scopeNodeId: number | null;
  scopeNode: ScopeNode | null;
  onCancel: () => void;
  onSuccess: () => void;
}) {
  const { message } = App.useApp();
  const [file, setFile] = useState<File | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [preview, setPreview] = useState<TestCaseExcelImportPreview | null>(null);
  const [requestKey, setRequestKey] = useState('');
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setFileList([]);
    setPreview(null);
    setRequestKey('');
  }, [open]);

  const downloadTemplate = async () => {
    try {
      const blob = await testManagementApi.downloadCaseImportTemplate(projectId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'test-case-import-template.xlsx';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(getErrorMessage(error, '模板下载失败'));
    }
  };

  const previewFile = async () => {
    if (!file) return;
    setPreviewing(true);
    try {
      const result = await testManagementApi.previewCaseImport(projectId, file, direction, scopeNodeId);
      setPreview(result);
      if (result.errors.length) message.warning(`发现 ${result.errors.length} 项需要修正`);
    } catch (error) {
      message.error(getErrorMessage(error, '预览失败'));
    } finally {
      setPreviewing(false);
    }
  };

  const confirmImport = async () => {
    if (!file || !preview || preview.errors.length || !preview.items.length || confirming) return;
    setConfirming(true);
    try {
      const result = await testManagementApi.confirmCaseImport(
        projectId, file, direction, scopeNodeId, requestKey || crypto.randomUUID(), preview.source_hash,
      );
      message.success(`已导入 ${result.imported_count} 条用例`);
      onSuccess();
    } catch (error) {
      message.error(getErrorMessage(error, '导入失败；未写入部分用例'));
    } finally {
      setConfirming(false);
    }
  };

  return (
    <Modal
      title="导入 Excel 用例"
      open={open}
      onCancel={onCancel}
      width={820}
      destroyOnClose
      footer={null}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Descriptions size="small" bordered column={1}>
          <Descriptions.Item label="当前项目">#{projectId}</Descriptions.Item>
          <Descriptions.Item label="测试方向">{DIRECTION_LABELS[direction] ?? direction}</Descriptions.Item>
          <Descriptions.Item label="目标目录">{scopeNode?.name ?? (scopeNodeId == null ? '对应方向的待整理' : `目录 #${scopeNodeId}`)}</Descriptions.Item>
        </Descriptions>
        <Space wrap>
          <Button icon={<DownloadOutlined />} onClick={downloadTemplate}>下载 Excel 模板</Button>
          <Upload
            accept=".xlsx"
            maxCount={1}
            fileList={fileList}
            beforeUpload={(next) => {
              setFile(next);
              setFileList([{ uid: next.uid, name: next.name, status: 'done' }]);
              setPreview(null);
              setRequestKey(crypto.randomUUID());
              return false;
            }}
            onRemove={() => { setFile(null); setFileList([]); setPreview(null); setRequestKey(''); return true; }}
          >
            <Button icon={<InboxOutlined />}>选择 .xlsx 文件</Button>
          </Upload>
          <Button type="primary" loading={previewing} disabled={!file} onClick={previewFile}>上传并预览</Button>
        </Space>
        <Typography.Text type="secondary">模板只支持用例名称、优先级、测试维度和描述；最大 5 MiB、最多 1000 条。预览期间目标项目、方向和目录固定。</Typography.Text>
        {preview && (
          <>
            <Alert
              type={preview.errors.length ? 'warning' : 'success'}
              showIcon
              message={`工作簿共 ${preview.total_rows} 行用例，可导入 ${preview.items.filter((item) => item.valid).length} 条，错误 ${preview.errors.length} 项`}
            />
            <Table
              size="small"
              rowKey={(row) => `${row.worksheet}-${row.row}`}
              pagination={{ pageSize: 8 }}
              dataSource={preview.items}
              columns={[
                { title: '行', dataIndex: 'row', width: 60 },
                { title: '用例名称', dataIndex: 'name', ellipsis: true },
                { title: '优先级', dataIndex: 'priority', width: 90 },
                { title: '测试维度', dataIndex: 'case_type', width: 130 },
                { title: '校验', dataIndex: 'valid', width: 85, render: (valid: boolean) => <Tag color={valid ? 'green' : 'red'}>{valid ? '可导入' : '有错误'}</Tag> },
              ]}
            />
            {preview.errors.length > 0 && (
              <Table
                size="small"
                rowKey={(row, index) => `${row.worksheet}-${row.row}-${row.column}-${index}`}
                pagination={{ pageSize: 6 }}
                dataSource={preview.errors}
                columns={[
                  { title: '工作表', dataIndex: 'worksheet', width: 120 },
                  { title: '行', dataIndex: 'row', width: 65 },
                  { title: '列', dataIndex: 'column', width: 100 },
                  { title: '原因', dataIndex: 'message' },
                ]}
              />
            )}
            <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
              <Button onClick={onCancel}>取消</Button>
              <Button
                type="primary"
                loading={confirming}
                disabled={!file || preview.errors.length > 0 || preview.items.length === 0}
                onClick={confirmImport}
              >确认导入</Button>
            </Space>
          </>
        )}
      </Space>
    </Modal>
  );
}
