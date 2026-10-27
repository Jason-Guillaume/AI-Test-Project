// 导入对话框：粘贴或上传 cURL、OpenAPI/Swagger、Postman 文档 → 解析预览 → 确认入库。
// 预览不入库（resolve_dry）；确认重新解析+去重+入库（幂等），写 import_record + change_log。
import { useRef, useState } from 'react';
import { App, Button, Input, Modal, Select, Space, Tabs, Typography, Upload } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { IMPORT_SOURCE_OPTIONS } from './constants';
import { ImportPreview } from './ImportPreview';
import type {
  ApiImportPreviewResponse,
  ApiModule,
  ApiSourceType,
} from '@/types';

const MAX_DOCUMENT_SIZE = 2 * 1024 * 1024;

/**
 * 导入对话框。
 *
 * 流程：source_type + content → importPreview（不入库）→ ImportPreview 勾选 → importConfirm（入库）。
 * 关闭时清空预览与内容，避免残留。
 */
export function ImportDialog({
  open,
  onClose,
  projectId,
  modules,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  modules: ApiModule[];
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [sourceType, setSourceType] = useState<ApiSourceType>('CURL');
  const [content, setContent] = useState('');
  const [fileName, setFileName] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [uploadedName, setUploadedName] = useState('');
  const [inputMode, setInputMode] = useState<'text' | 'file'>('text');
  const [readingFile, setReadingFile] = useState(false);
  const [previewInput, setPreviewInput] = useState<{ source_type: ApiSourceType; content: string; file_name: string | null } | null>(null);
  const [preview, setPreview] = useState<ApiImportPreviewResponse | null>(null);
  const fileReadId = useRef(0);

  const previewMutation = useMutation({
    mutationFn: (body: { source_type: ApiSourceType; content: string; file_name?: string | null }) =>
      apiCatalogApi.importPreview(projectId, body),
    onSuccess: (data, variables) => {
      const detectedSourceType = data.source_type || variables.source_type;
      const sourceLabels: Partial<Record<ApiSourceType, string>> = {
        CURL: 'cURL', OPENAPI: 'OpenAPI', SWAGGER: 'Swagger', POSTMAN: 'Postman Collection',
      };
      setSourceType(detectedSourceType);
      setPreviewInput({
        ...variables,
        source_type: detectedSourceType,
        file_name: variables.file_name || null,
      });
      setPreview(data);
      const detectedLabel = sourceLabels[detectedSourceType];
      const autoDetected = detectedSourceType !== variables.source_type && detectedLabel
        ? `已识别为 ${detectedLabel}，`
        : '';
      message.success(`${autoDetected}解析完成：${data.total} 条`);
    },
    onError: (e) => message.error(getErrorMessage(e, '解析失败')),
  });

  const confirmMutation = useMutation({
    mutationFn: (body: {
      source_type: ApiSourceType;
      content: string;
      file_name?: string | null;
      user_module_id?: number | null;
      selected_items?: number[] | null;
    }) => apiCatalogApi.importConfirm(projectId, body),
    onSuccess: (data) => {
      message.success(`导入完成：新建 ${data.created_count} / 更新 ${data.updated_count} / 跳过 ${data.skipped_count}`);
      queryClient.invalidateQueries({ queryKey: ['api-catalog'] });
      queryClient.invalidateQueries({ queryKey: ['api-catalog', projectId, 'import-records'] });
      handleClose();
    },
    onError: (e) => message.error(getErrorMessage(e, '导入失败')),
  });

  const handleClose = () => {
    fileReadId.current += 1;
    setPreview(null);
    setContent('');
    setFileName('');
    setFileContent('');
    setUploadedName('');
    setInputMode('text');
    setReadingFile(false);
    setPreviewInput(null);
    onClose();
  };

  const handleFile = async (file: File) => {
    const readId = ++fileReadId.current;
    setFileContent('');
    setUploadedName('');
    setReadingFile(false);
    if (!/\.(json|yaml|yml)$/i.test(file.name)) {
      message.error('请选择 JSON 或 YAML 文件');
      return;
    }
    if (file.size > MAX_DOCUMENT_SIZE) {
      message.error('文件不能超过 2 MB');
      return;
    }
    setReadingFile(true);
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      if (readId !== fileReadId.current) return;
      if (!text.trim()) {
        message.error('文件内容为空');
        return;
      }
      setFileContent(text);
      setUploadedName(file.name);
    } catch {
      if (readId === fileReadId.current) message.error('读取失败，请确认文件为 UTF-8 编码');
    } finally {
      if (readId === fileReadId.current) setReadingFile(false);
    }
  };

  const handleParse = async () => {
    const activeContent = inputMode === 'file' ? fileContent : content;
    if (!activeContent.trim()) {
      message.error(inputMode === 'file' ? '请选择文件' : '请粘贴内容');
      return;
    }
    setPreview(null);
    await previewMutation.mutateAsync({
      source_type: sourceType,
      content: activeContent,
      file_name: (inputMode === 'file' ? uploadedName : fileName) || null,
    });
  };

  const handleConfirm = async (
    selected: number[] | null,
    overrideModuleId: number | null,
  ) => {
    if (!previewInput) return;
    await confirmMutation.mutateAsync({
      ...previewInput,
      user_module_id: overrideModuleId,
      selected_items: selected,
    });
  };

  const placeholder =
    sourceType === 'CURL'
      ? 'curl -X POST "https://example.com/api/v1/tasks" -H "Authorization: Bearer xxx" -H "Content-Type: application/json" -d \'{"title":"x"}\''
      : sourceType === 'POSTMAN'
        ? '粘贴 Postman Collection v2.0/v2.1 JSON；也支持 OpenAPI / Swagger 文档自动识别'
        : '粘贴 OpenAPI 3.x / Swagger 2.0 的 JSON 或 YAML 文本';

  return (
    <Modal
      title={preview ? '导入预览' : '导入接口'}
      open={open}
      onCancel={handleClose}
      width={preview ? 'min(1240px, calc(100vw - 40px))' : 640}
      footer={
        preview ? (
          // 预览态的选择、返回和确认操作由预览面板底部统一承载。
          null
        ) : (
          <Space>
            <Button onClick={handleClose}>取消</Button>
            <Button
              type="primary"
              loading={previewMutation.isPending}
              disabled={readingFile}
              onClick={handleParse}
            >
              解析预览
            </Button>
          </Space>
        )
      }
      destroyOnClose
    >
      {preview ? (
        <ImportPreview
          preview={preview}
          modules={modules}
          onConfirm={handleConfirm}
          onClose={handleClose}
          confirming={confirmMutation.isPending}
        />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space wrap align="center">
            <Typography.Text>来源</Typography.Text>
            <Select
              value={sourceType}
              onChange={(v: ApiSourceType) => {
                if (v === 'CURL') setInputMode('text');
                setSourceType(v);
              }}
              options={IMPORT_SOURCE_OPTIONS}
              style={{ width: 180 }}
            />
          </Space>
          <Tabs
            activeKey={inputMode}
            onChange={(key) => setInputMode(key as 'text' | 'file')}
            items={[
              {
                key: 'text', label: '输入文本', children: (
                  <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                    <Input placeholder="文件名（可选）" value={fileName} onChange={(e) => setFileName(e.target.value)} />
                    <Input.TextArea rows={12} value={content} onChange={(e) => setContent(e.target.value)} placeholder={placeholder} style={{ fontFamily: 'monospace' }} />
                  </Space>
                ),
              },
              ...(sourceType === 'CURL' ? [] : [{
                key: 'file', label: '上传文件', children: (
                  <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                    <Upload.Dragger
                      accept=".json,.yaml,.yml"
                      multiple={false}
                      showUploadList={false}
                      beforeUpload={(file) => { void handleFile(file); return Upload.LIST_IGNORE; }}
                    >
                      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                      <p className="ant-upload-text">点击或将文件拖拽到此处上传</p>
                      <p className="ant-upload-hint">支持 UTF-8 编码的 OpenAPI/Swagger JSON、YAML 和 Postman Collection JSON，最大 2 MB</p>
                    </Upload.Dragger>
                    {readingFile ? <Typography.Text>正在读取文件…</Typography.Text> : uploadedName && <Typography.Text>已选择：{uploadedName}</Typography.Text>}
                  </Space>
                ),
              }]),
            ]}
          />
          <Typography.Text type="secondary">
            {sourceType === 'CURL'
              ? '单条 curl，Authorization/Token/Cookie 会自动脱敏为变量占位。'
              : sourceType === 'POSTMAN'
                ? '支持 Postman Collection v2.0/v2.1；OpenAPI 3.x、Swagger 2.0 和 Postman 文档会自动识别，凭据会脱敏。Apifox 请导出为上述标准格式。'
                : '支持 OpenAPI 3.x（含 3.1）/Swagger 2.0 JSON、YAML，以及 Postman Collection v2.0/v2.1；文档格式会自动识别，凭据会脱敏。Apifox 请导出为上述标准格式。'}
          </Typography.Text>
        </Space>
      )}
    </Modal>
  );
}
