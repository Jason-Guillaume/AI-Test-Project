// 用例 Excel 导入弹窗。
// 固定四列模板仍先预览再确认。模型建议是可选步骤：只展示分类和接口关联，勾选后才随确认写入。
// 未接入：不生成步骤和预期结果，不创建接口。
import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Checkbox, Descriptions, Modal, Select, Space, Table, Tag, Typography, Upload } from 'antd';
import type { UploadFile } from 'antd';
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import type { ScopeNode, TestCaseExcelImportPreview, TestCaseImportAdoption, TestCaseImportSuggestion } from '@/features/test-management/contracts';
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
  const [suggesting, setSuggesting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [suggestion, setSuggestion] = useState<TestCaseImportSuggestion | null>(null);
  const [useModel, setUseModel] = useState(true);
  const [nameColumn, setNameColumn] = useState<number | null>(null);
  const [priorityColumn, setPriorityColumn] = useState<number | null>(null);
  const [caseTypeColumn, setCaseTypeColumn] = useState<number | null>(null);
  const [descriptionColumn, setDescriptionColumn] = useState<number | null>(null);
  const [accepted, setAccepted] = useState<Record<string, { caseType: boolean; api: boolean }>>({});
  const [chosenApi, setChosenApi] = useState<Record<string, number>>({});
  const lastRejectedFile = useRef<{ reason: string; at: number } | null>(null);

  const clearSelectedFile = () => {
    setFile(null);
    setFileList([]);
    setPreview(null);
    setSuggestion(null);
    setRequestKey('');
    setAccepted({});
    setChosenApi({});
  };

  const rejectFile = (reason: string) => {
    clearSelectedFile();
    const previous = lastRejectedFile.current;
    if (previous?.reason !== reason || Date.now() - previous.at > 500) message.error(reason);
    lastRejectedFile.current = { reason, at: Date.now() };
    return Upload.LIST_IGNORE;
  };

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setFileList([]);
    setPreview(null);
    setSuggestion(null);
    setRequestKey('');
    setAccepted({});
    setChosenApi({});
    setUseModel(true);
    lastRejectedFile.current = null;
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
      setSuggestion(null);
      if (result.errors.length) message.warning(`发现 ${result.errors.length} 项需要修正`);
    } catch (error) {
      message.error(getErrorMessage(error, '预览失败'));
    } finally {
      setPreviewing(false);
    }
  };

  /**
   * 生成模型建议。模型失败时接口仍返回规则匹配，页面继续展示手动映射。
   */
  const suggestFile = async () => {
    if (!file) return;
    setSuggesting(true);
    try {
      const result = await testManagementApi.suggestCaseImport(projectId, file, direction, scopeNodeId, useModel);
      setSuggestion(result);
      setAccepted({});
      setChosenApi({});
      const mapping = result.suggested_mapping;
      setNameColumn(mapping?.name_column ?? null);
      setPriorityColumn(mapping?.priority_column ?? null);
      setCaseTypeColumn(mapping?.case_type_column ?? null);
      setDescriptionColumn(mapping?.description_column ?? null);
      if (result.model_status === 'unavailable') message.warning(result.model_error || '模型建议不可用');
    } catch (error) {
      message.error(getErrorMessage(error, '生成建议失败'));
    } finally {
      setSuggesting(false);
    }
  };

  const confirmImport = async () => {
    if (!file || confirming) return;
    const standardReady = preview != null && preview.errors.length === 0 && preview.items.length > 0;
    const mappingReady = suggestion != null && !suggestion.template_compatible && nameColumn != null;
    if (!standardReady && !mappingReady) return;
    const sourceHash = standardReady ? preview.source_hash : suggestion!.source_hash;
    const acceptedRows = Object.entries(accepted).flatMap(([key, value]) => {
      const [worksheet, rowText] = key.split('::');
      const source = suggestion?.rows.find((item) => item.worksheet === worksheet && item.row === Number(rowText));
      if (!source || (!value.caseType && !value.api)) return [];
      const apiId = source.rule_status === 'recommended'
        ? source.rule_api_id
        : source.rule_status === 'ambiguous'
          ? chosenApi[key] ?? null
          : source.model_api_id;
      return [{
        worksheet,
        row: Number(rowText),
        accept_case_type: value.caseType,
        case_type: source.model_case_type,
        accept_api: value.api && apiId != null,
        api_id: apiId,
      }];
    });
    let adoption: TestCaseImportAdoption | undefined;
    if (mappingReady && suggestion) {
      adoption = {
        mode: 'mapping',
        worksheet: suggestion.sheets[0]?.name,
        header_row: suggestion.sheets[0]?.header_row,
        name_column: nameColumn,
        priority_column: priorityColumn,
        case_type_column: caseTypeColumn,
        description_column: descriptionColumn,
        rows: acceptedRows,
      };
    } else if (acceptedRows.length) {
      adoption = { mode: 'template', rows: acceptedRows };
    }
    setConfirming(true);
    try {
      const result = await testManagementApi.confirmCaseImport(
        projectId, file, direction, scopeNodeId, requestKey || crypto.randomUUID(), sourceHash, adoption,
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
      width={960}
      destroyOnHidden
      footer={null}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Descriptions size="small" bordered column={1}>
          <Descriptions.Item label="当前项目">#{projectId}</Descriptions.Item>
          <Descriptions.Item label="测试方向">{DIRECTION_LABELS[direction] ?? direction}</Descriptions.Item>
          <Descriptions.Item label="目标目录">{scopeNode?.name ?? (scopeNodeId == null ? '对应方向的待整理' : `目录 #${scopeNodeId}`)}</Descriptions.Item>
        </Descriptions>
        <Button icon={<DownloadOutlined />} onClick={downloadTemplate}>下载 Excel 模板</Button>
        <Upload.Dragger
          accept=".xlsx"
          multiple
          disabled={previewing || suggesting || confirming}
          showUploadList={false}
          fileList={fileList}
          beforeUpload={(next, batch) => {
            if (batch.length > 1) return rejectFile('一次只能选择或拖入一个 Excel 文件，请重新选择。');
            if (!next.name.toLowerCase().endsWith('.xlsx')) return rejectFile('文件格式错误，请选择 .xlsx 文件。');
            if (next.size > 5 * 1024 * 1024) return rejectFile('文件超过 5 MiB 限制，请选择较小的 .xlsx 文件。');
            setFile(next);
            setFileList([{ uid: next.uid, name: next.name, status: 'done' }]);
            setPreview(null);
            setSuggestion(null);
            setAccepted({});
            setChosenApi({});
            setRequestKey(crypto.randomUUID());
            lastRejectedFile.current = null;
            return false;
          }}
          onDrop={(event) => {
            const dropped = Array.from(event.dataTransfer.files);
            if (dropped.length > 1) return rejectFile('一次只能选择或拖入一个 Excel 文件，请重新选择。');
            const candidate = dropped[0];
            if (!candidate) return;
            if (!candidate.name.toLowerCase().endsWith('.xlsx')) return rejectFile('文件格式错误，请选择 .xlsx 文件。');
            if (candidate.size > 5 * 1024 * 1024) return rejectFile('文件超过 5 MiB 限制，请选择较小的 .xlsx 文件。');
          }}
          onRemove={() => { clearSelectedFile(); return true; }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击选择或将 .xlsx 文件拖到此处</p>
          <p className="ant-upload-hint">仅支持单个 .xlsx 文件，最大 5 MiB、最多 1000 条用例。{file ? '再次选择可替换当前文件。' : ''}</p>
        </Upload.Dragger>
        {file && <Space>
          <Tag color="blue">{file.name}</Tag>
          <Button type="link" size="small" onClick={clearSelectedFile} disabled={previewing || suggesting || confirming}>移除文件</Button>
          <Button type="primary" loading={previewing} disabled={confirming || suggesting} onClick={previewFile}>上传并预览</Button>
          <Checkbox checked={useModel} onChange={(event) => setUseModel(event.target.checked)}>使用模型</Checkbox>
          <Button loading={suggesting} disabled={confirming || previewing} onClick={suggestFile}>生成分类与接口建议</Button>
        </Space>}
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
          </>
        )}
        {suggestion && (
          <>
            <Alert
              type={suggestion.model_status === 'ok' ? 'info' : 'warning'}
              showIcon
              message={suggestion.model_status === 'unavailable' ? suggestion.model_error : `建议已生成，模型调用 ${suggestion.model_calls} 次。勾选后才会写入维度或接口。`}
            />
            {suggestion.warnings.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} />)}
            {!suggestion.template_compatible && suggestion.sheets[0] && (
              <Space wrap>
                <Select
                  placeholder="用例名称列"
                  style={{ width: 160 }}
                  value={nameColumn ?? undefined}
                  options={suggestion.sheets[0].columns.map((column) => ({ value: column.index, label: column.header || `第${column.index}列` }))}
                  onChange={setNameColumn}
                />
                <Select
                  allowClear
                  placeholder="优先级列"
                  style={{ width: 140 }}
                  value={priorityColumn ?? undefined}
                  options={suggestion.sheets[0].columns.map((column) => ({ value: column.index, label: column.header || `第${column.index}列` }))}
                  onChange={(value) => setPriorityColumn(value ?? null)}
                />
                <Select
                  allowClear
                  placeholder="测试维度列"
                  style={{ width: 140 }}
                  value={caseTypeColumn ?? undefined}
                  options={suggestion.sheets[0].columns.map((column) => ({ value: column.index, label: column.header || `第${column.index}列` }))}
                  onChange={(value) => setCaseTypeColumn(value ?? null)}
                />
                <Select
                  allowClear
                  placeholder="描述列"
                  style={{ width: 140 }}
                  value={descriptionColumn ?? undefined}
                  options={suggestion.sheets[0].columns.map((column) => ({ value: column.index, label: column.header || `第${column.index}列` }))}
                  onChange={(value) => setDescriptionColumn(value ?? null)}
                />
              </Space>
            )}
            <Table
              size="small"
              rowKey={(row) => `${row.worksheet}-${row.row}`}
              pagination={{ pageSize: 8 }}
              dataSource={suggestion.rows}
              columns={[
                { title: '行', dataIndex: 'row', width: 60 },
                { title: '规则关联', dataIndex: 'rule_status', width: 110, render: (status: string) => status === 'recommended' ? '推荐' : status === 'ambiguous' ? '待选择' : '未匹配' },
                { title: '建议维度', dataIndex: 'model_case_type', width: 120, render: (value: string | null) => value ?? '—' },
                { title: '建议接口', width: 90, render: (_value, row) => row.rule_api_id ?? row.model_api_id ?? '—' },
                {
                  title: '采纳',
                  width: 180,
                  render: (_value, row) => {
                    const key = `${row.worksheet}::${row.row}`;
                    const current = accepted[key] ?? { caseType: false, api: false };
                    const apiId = row.rule_status === 'recommended'
                      ? row.rule_api_id
                      : row.rule_status === 'ambiguous'
                        ? chosenApi[key] ?? null
                        : row.model_api_id;
                    return (
                      <Space>
                        {row.rule_status === 'ambiguous' && (
                          <Select
                            placeholder="选择接口"
                            style={{ width: 140 }}
                            options={row.candidates.map((item) => ({ value: item.id, label: `${item.method} ${item.path}` }))}
                            onChange={(value) => setChosenApi((previous) => ({ ...previous, [key]: value }))}
                          />
                        )}
                        <Checkbox
                          checked={current.caseType}
                          disabled={!row.model_case_type}
                          onChange={(event) => setAccepted((previous) => ({ ...previous, [key]: { ...current, caseType: event.target.checked } }))}
                        >维度</Checkbox>
                        <Checkbox
                          checked={current.api}
                          disabled={apiId == null}
                          onChange={(event) => setAccepted((previous) => ({ ...previous, [key]: { ...current, api: event.target.checked } }))}
                        >接口</Checkbox>
                      </Space>
                    );
                  },
                },
              ]}
            />
          </>
        )}
        {(preview || suggestion) && (
          <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
            <Button onClick={onCancel}>取消</Button>
            <Button
              type="primary"
              loading={confirming}
              disabled={!file || !(
                (preview != null && preview.errors.length === 0 && preview.items.length > 0)
                || (suggestion != null && !suggestion.template_compatible && nameColumn != null)
              )}
              onClick={confirmImport}
            >确认导入</Button>
          </Space>
        )}
      </Space>
    </Modal>
  );
}
