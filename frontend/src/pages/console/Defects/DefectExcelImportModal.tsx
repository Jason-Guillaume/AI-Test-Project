// 缺陷 Excel 导入弹窗。
// 复用测试用例 Excel 导入的上传预览交互模式：
// 1. 展示目标项目、1–100 条单次上限和空白模板下载；
// 2. 上传无宏 .xlsx 后预览待创建明细、未知列提示、文件内重复提示、历史同内容批次提示与逐行错误；
// 3. 存在错误时整批留在预览，禁止确认；全部通过后单事务确认并返回批次编号与各行缺陷 ID。
//
// 未接入：不支持按缺陷 ID 更新存量缺陷，不支持 .xls / .xlsm / CSV 导入。
import { useEffect, useRef, useState } from 'react';
import {
  Alert, App, Button, Checkbox, Descriptions, Modal, Space, Table, Tag, Typography, Upload,
} from 'antd';
import type { UploadFile } from 'antd';
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons';
import { bugsApi, parseBlobApiError, triggerBlobDownload } from '@/features/defects/api/defects';
import type {
  DefectImportConfirmResponse,
  DefectImportPreviewItem,
  DefectImportPreviewResponse,
} from '@/features/defects/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { CATEGORY_COLOR, PRIORITY_COLOR, PRIORITY_LABELS, SEVERITY_COLOR } from './constants';

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const SEVERITY_TEXT: Record<number, string> = { 1: '低', 2: '中', 3: '高', 4: '严重' };

export interface DefectExcelImportModalProps {
  open: boolean;
  projectId: number;
  projectName?: string;
  onClose: () => void;
  onImported: () => void;
}

/**
 * 缺陷 Excel 导入弹窗组件。
 *
 * 会发请求：
 * - 点击「下载空白模板」调用 GET /bugs/import-template；
 * - 点击「上传并预览」调用 POST /bugs/import-preview；
 * - 点击「确认导入」调用 POST /bugs/import-confirm。
 * 失败呈现：message.error 展示服务端中文错误；预览错误留在弹窗内逐行定位。
 */
export function DefectExcelImportModal({
  open,
  projectId,
  projectName,
  onClose,
  onImported,
}: DefectExcelImportModalProps) {
  const { message } = App.useApp();
  const [file, setFile] = useState<File | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [downloading, setDownloading] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [preview, setPreview] = useState<DefectImportPreviewResponse | null>(null);
  const [confirmDuplicate, setConfirmDuplicate] = useState(false);
  const [receipt, setReceipt] = useState<DefectImportConfirmResponse | null>(null);
  const lastRejected = useRef<{ reason: string; at: number } | null>(null);

  /** 清空已选文件、预览快照与确认回执。 */
  const clearSelection = () => {
    setFile(null);
    setFileList([]);
    setPreview(null);
    setConfirmDuplicate(false);
    setReceipt(null);
  };

  /** 拒绝非法文件并做 500ms 防抖提示，避免拖拽事件重复弹窗。 */
  const rejectFile = (reason: string) => {
    clearSelection();
    const prev = lastRejected.current;
    if (prev?.reason !== reason || Date.now() - prev.at > 500) {
      message.error(reason);
    }
    lastRejected.current = { reason, at: Date.now() };
    return Upload.LIST_IGNORE;
  };

  // 每次打开弹窗或切换项目时重置局部状态，避免把旧项目的预览带到新项目。
  useEffect(() => {
    if (!open) return;
    setFile(null);
    setFileList([]);
    setPreview(null);
    setConfirmDuplicate(false);
    setReceipt(null);
    lastRejected.current = null;
  }, [open, projectId]);

  /** 下载当前项目的空白缺陷导入模板。 */
  const handleDownloadTemplate = async () => {
    setDownloading(true);
    try {
      const { blob, filename } = await bugsApi.downloadImportTemplate(projectId);
      triggerBlobDownload(blob, filename);
      message.success('空白模板已开始下载');
    } catch (error) {
      const parsed = await parseBlobApiError(error, '模板下载失败');
      message.error(parsed.message);
    } finally {
      setDownloading(false);
    }
  };

  /** 上传文件并请求服务端预览校验。 */
  const handlePreview = async () => {
    if (!file) return;
    setPreviewing(true);
    setReceipt(null);
    setConfirmDuplicate(false);
    try {
      const result = await bugsApi.previewImport(projectId, file);
      setPreview(result);
      if (result.errors.length > 0) {
        message.warning(`发现 ${result.errors.length} 项错误，请修正后重新上传`);
      } else {
        message.success(`校验通过，共 ${result.valid_rows} 条待新建缺陷`);
      }
    } catch (error) {
      message.error(getErrorMessage(error, '预览失败'));
    } finally {
      setPreviewing(false);
    }
  };

  /** 确认整批导入：仅在预览无误且存在有效 preview_token 时允许调用。 */
  const handleConfirm = async () => {
    if (!preview?.preview_token || confirming) return;
    setConfirming(true);
    try {
      const result = await bugsApi.confirmImport({
        project_id: projectId,
        preview_token: preview.preview_token,
        confirm_duplicate: confirmDuplicate,
      });
      setReceipt(result);
      message.success(
        result.replayed
          ? `该预览已导入（批次 #${result.batch_id}），已返回原回执`
          : `导入成功：批次 #${result.batch_id}，共新建 ${result.created_count} 条缺陷`,
      );
      // 写入成功后通知父页面刷新缺陷列表、队列计数与质量统计。
      onImported();
    } catch (error) {
      message.error(getErrorMessage(error, '确认导入失败，整批已回滚未写入'));
    } finally {
      setConfirming(false);
    }
  };

  const needsDuplicateAck = preview?.recent_matching_batch != null;
  const canConfirm = Boolean(
    preview
    && preview.preview_token
    && preview.errors.length === 0
    && preview.valid_rows > 0
    && (!needsDuplicateAck || confirmDuplicate)
    && !receipt,
  );

  return (
    <Modal
      title="导入缺陷（Excel）"
      open={open}
      onCancel={onClose}
      width={980}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onClose}>{receipt ? '完成并关闭' : '取消'}</Button>
          {!receipt && (
            <Button
              type="primary"
              loading={confirming}
              disabled={!canConfirm || previewing}
              onClick={handleConfirm}
            >
              确认导入{preview?.valid_rows ? `（新建 ${preview.valid_rows} 条）` : ''}
            </Button>
          )}
        </Space>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Descriptions size="small" bordered column={2}>
          <Descriptions.Item label="目标项目">
            {projectName ? `${projectName}（#${projectId}）` : `项目 #${projectId}`}
          </Descriptions.Item>
          <Descriptions.Item label="单次上限">每次 1–100 条（仅新建，初始状态为「待确认」）</Descriptions.Item>
          <Descriptions.Item label="文件要求" span={2}>
            无宏 Excel 工作簿（.xlsx），最大 5 MiB；按「缺陷明细」表首行中文表头匹配，允许调换列顺序，禁止公式单元格。
          </Descriptions.Item>
        </Descriptions>

        <Space wrap>
          <Button
            icon={<DownloadOutlined />}
            loading={downloading}
            onClick={handleDownloadTemplate}
          >
            下载空白模板（.xlsx）
          </Button>
          <Typography.Text type="secondary">
            模板含「缺陷明细」「填写说明」两张表，示例放在说明页避免误导入。
          </Typography.Text>
        </Space>

        <Upload.Dragger
          accept=".xlsx"
          multiple={false}
          disabled={previewing || confirming}
          showUploadList={false}
          fileList={fileList}
          beforeUpload={(next, batch) => {
            if (batch.length > 1) return rejectFile('一次只能选择一个 .xlsx 文件，请重新选择');
            if (!next.name.toLowerCase().endsWith('.xlsx')) return rejectFile('仅支持无宏 .xlsx 文件，请转换后上传');
            if (next.size > MAX_UPLOAD_BYTES) return rejectFile('文件超过 5 MiB 上限，请拆分后重新上传');
            setFile(next);
            setFileList([{ uid: next.uid, name: next.name, status: 'done' }]);
            setPreview(null);
            setConfirmDuplicate(false);
            setReceipt(null);
            lastRejected.current = null;
            return false;
          }}
          onDrop={(event) => {
            const dropped = Array.from(event.dataTransfer.files);
            if (dropped.length > 1) return rejectFile('一次只能拖入一个 .xlsx 文件');
            const candidate = dropped[0];
            if (!candidate) return;
            if (!candidate.name.toLowerCase().endsWith('.xlsx')) return rejectFile('仅支持无宏 .xlsx 文件');
            if (candidate.size > MAX_UPLOAD_BYTES) return rejectFile('文件超过 5 MiB 上限');
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击选择或将 .xlsx 文件拖到此处</p>
          <p className="ant-upload-hint">
            支持 Excel / WPS / Google 表格导出的无宏 .xlsx；存在错误时整批留在预览，修正后重新上传即可。
          </p>
        </Upload.Dragger>

        {file && (
          <Space wrap>
            <Tag color="blue">{file.name}</Tag>
            <Button type="link" size="small" disabled={previewing || confirming} onClick={clearSelection}>
              移除文件
            </Button>
            <Button type="primary" loading={previewing} disabled={confirming} onClick={handlePreview}>
              上传并预览
            </Button>
          </Space>
        )}

        {receipt && (
          <Alert
            type="success"
            showIcon
            message={`导入完成 · 批次 #${receipt.batch_id}（新建 ${receipt.created_count} 条${receipt.replayed ? '，重试回放' : ''}）`}
            description={
              <Table
                size="small"
                pagination={{ pageSize: 5, hideOnSinglePage: true }}
                rowKey={(row) => `${row.excel_row}-${row.bug_id}`}
                dataSource={receipt.items}
                columns={[
                  { title: 'Excel 行号', dataIndex: 'excel_row', width: 100, render: (v: number) => `第 ${v} 行` },
                  { title: '新建缺陷 ID', dataIndex: 'bug_id', width: 120, render: (v: number) => <Tag color="green">#{v}</Tag> },
                  { title: '标题', dataIndex: 'title' },
                ]}
              />
            }
          />
        )}

        {preview && !receipt && (
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <Alert
              type={preview.errors.length > 0 ? 'error' : 'success'}
              showIcon
              message={
                preview.errors.length > 0
                  ? `预览发现 ${preview.errors.length} 项错误（共 ${preview.total_rows} 行，通过 ${preview.valid_rows} 行），请修正文件后重新上传`
                  : `校验通过：共 ${preview.valid_rows} 条待新建缺陷（所有记录均标记为「新建」，进入待确认队列）`
              }
            />

            {preview.warnings.map((warn, idx) => (
              <Alert key={`warn-${idx}`} type="info" showIcon message={warn} />
            ))}

            {preview.duplicate_warnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={`检测到 ${preview.duplicate_warnings.length} 组文件内重复项（同一项目允许重复，可按需修改后重传或直接新建）`}
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.duplicate_warnings.map((dup, idx) => (
                      <li key={`dup-${idx}`}>{dup.message}</li>
                    ))}
                  </ul>
                }
              />
            )}

            {preview.recent_matching_batch && (
              <Alert
                type="warning"
                showIcon
                message={`该文件内容与历史成功批次 #${preview.recent_matching_batch.batch_id} 一致`}
                description={
                  <Space direction="vertical" size="small">
                    <Typography.Text>
                      上次由 {preview.recent_matching_batch.created_by_username ?? '未知用户'} 于{' '}
                      {preview.recent_matching_batch.committed_at
                        ? new Date(preview.recent_matching_batch.committed_at).toLocaleString()
                        : '-'}{' '}
                      新建 {preview.recent_matching_batch.created_count} 条（文件：{preview.recent_matching_batch.file_name}）。
                    </Typography.Text>
                    <Checkbox
                      checked={confirmDuplicate}
                      onChange={(event) => setConfirmDuplicate(event.target.checked)}
                    >
                      我已核对历史批次，确认仍要再次新建这 {preview.valid_rows} 条缺陷
                    </Checkbox>
                  </Space>
                }
              />
            )}

            {preview.errors.length > 0 && (
              <Alert
                type="error"
                showIcon
                message="逐行错误明细（存在错误时整批不会写入）"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18, maxHeight: 200, overflowY: 'auto' }}>
                    {preview.errors.map((err, idx) => (
                      <li key={`err-${idx}`}>
                        {err.row > 0 ? `第 ${err.row} 行 · ${err.column}：${err.message}` : `${err.column}：${err.message}`}
                      </li>
                    ))}
                  </ul>
                }
              />
            )}

            {preview.items.length > 0 && (
              <Table<DefectImportPreviewItem>
                size="small"
                rowKey={(item) => item.excel_row}
                scroll={{ x: 860 }}
                pagination={{ pageSize: 10, hideOnSinglePage: true }}
                dataSource={preview.items}
                columns={[
                  { title: 'Excel 行', dataIndex: 'excel_row', width: 84, render: (v: number) => `第 ${v} 行` },
                  {
                    title: '操作',
                    dataIndex: 'valid',
                    width: 84,
                    render: (valid: boolean) => (valid ? <Tag color="green">新建</Tag> : <Tag color="red">有误</Tag>),
                  },
                  { title: '标题', dataIndex: 'title', width: 220, ellipsis: true },
                  {
                    title: '划分',
                    dataIndex: 'category',
                    width: 84,
                    render: (v: DefectImportPreviewItem['category']) => (
                      v ? <Tag color={CATEGORY_COLOR[v]}>{v}</Tag> : <Tag>未划分</Tag>
                    ),
                  },
                  {
                    title: '严重度',
                    dataIndex: 'severity',
                    width: 78,
                    render: (v: number) => <Tag color={SEVERITY_COLOR[v as 1 | 2 | 3 | 4]}>{SEVERITY_TEXT[v] ?? v}</Tag>,
                  },
                  {
                    title: '优先级',
                    dataIndex: 'priority',
                    width: 78,
                    render: (v: number) => (
                      <Tag color={PRIORITY_COLOR[v as 1 | 2 | 3 | 4]}>{PRIORITY_LABELS[v as 1 | 2 | 3 | 4] ?? v}</Tag>
                    ),
                  },
                  { title: '环境 / 版本', key: 'env', width: 140, render: (_, row) => [row.environment, row.affected_version].filter(Boolean).join(' / ') || '-' },
                  {
                    title: '接口信息',
                    key: 'api',
                    width: 160,
                    ellipsis: true,
                    render: (_, row) => (row.api_method || row.api_url ? `${row.api_method ?? ''} ${row.api_url ?? ''}`.trim() : '-'),
                  },
                ]}
              />
            )}
          </Space>
        )}
      </Space>
    </Modal>
  );
}
