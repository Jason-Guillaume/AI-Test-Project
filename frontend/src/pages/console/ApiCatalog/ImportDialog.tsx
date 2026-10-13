// 导入对话框：选来源（Curl/OpenAPI/Swagger）+ 粘贴文本 → 解析预览 → 确认入库。
// 预览不入库（resolve_dry）；确认重新解析+去重+入库（幂等），写 import_record + change_log。
import { useState } from 'react';
import { App, Button, Input, Modal, Select, Space, Typography } from 'antd';
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
  const [preview, setPreview] = useState<ApiImportPreviewResponse | null>(null);

  const previewMutation = useMutation({
    mutationFn: (body: { source_type: ApiSourceType; content: string; file_name?: string | null }) =>
      apiCatalogApi.importPreview(projectId, body),
    onSuccess: (data) => {
      setPreview(data);
      message.success(`解析完成：${data.total} 条`);
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
    setPreview(null);
    setContent('');
    setFileName('');
    onClose();
  };

  const handleParse = async () => {
    if (!content.trim()) {
      message.error('请粘贴内容');
      return;
    }
    setPreview(null);
    await previewMutation.mutateAsync({
      source_type: sourceType,
      content,
      file_name: fileName || null,
    });
  };

  const handleConfirm = async (
    selected: number[] | null,
    overrideModuleId: number | null,
  ) => {
    await confirmMutation.mutateAsync({
      source_type: sourceType,
      content,
      file_name: fileName || null,
      user_module_id: overrideModuleId,
      selected_items: selected,
    });
  };

  const placeholder =
    sourceType === 'CURL'
      ? 'curl -X POST "https://example.com/api/v1/tasks" -H "Authorization: Bearer xxx" -H "Content-Type: application/json" -d \'{"title":"x"}\''
      : '粘贴 OpenAPI 3.x / Swagger 2.0 的 JSON 或 YAML 文本';

  return (
    <Modal
      title="导入接口"
      open={open}
      onCancel={handleClose}
      width={preview ? 900 : 640}
      footer={
        preview ? (
          // 预览阶段由 ImportPreview 内的确认按钮驱动，隐藏底部默认按钮。
          <Button onClick={handleClose}>关闭</Button>
        ) : (
          <Space>
            <Button onClick={handleClose}>取消</Button>
            <Button
              type="primary"
              loading={previewMutation.isPending}
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
          confirming={confirmMutation.isPending}
        />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Space wrap align="center">
            <Typography.Text>来源</Typography.Text>
            <Select
              value={sourceType}
              onChange={(v: ApiSourceType) => setSourceType(v)}
              options={IMPORT_SOURCE_OPTIONS}
              style={{ width: 180 }}
            />
            <Input
              placeholder="文件名（可选）"
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
              style={{ width: 220 }}
            />
          </Space>
          <Input.TextArea
            rows={12}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={placeholder}
            style={{ fontFamily: 'monospace' }}
          />
          <Typography.Text type="secondary">
            {sourceType === 'CURL'
              ? '单条 curl，Authorization/Token/Cookie 会自动脱敏为变量占位。'
              : '批量导入，按 tag/路径推断模块；支持 JSON 与 YAML。'}
          </Typography.Text>
        </Space>
      )}
    </Modal>
  );
}
