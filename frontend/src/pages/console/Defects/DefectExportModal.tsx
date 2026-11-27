// 缺陷 Excel 导出弹窗。
// 支持「当前项目的筛选结果（全部页）」与「已勾选缺陷」两种导出范围，展示目标项目、条数与字段范围；
// 默认仅导出常规事实字段（排除请求头、请求体、实际响应结果），勾选接口详情时由服务端按脱敏规则导出。
// 勾选项失效时展示明确提示并提供一键刷新列表清空勾选。
import { useEffect, useState } from 'react';
import { Alert, App, Button, Checkbox, Descriptions, Modal, Radio, Space, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { bugsApi, parseBlobApiError, triggerBlobDownload } from '@/features/defects/api/defects';
import type { BugListQuery, DefectExportRequest } from '@/features/defects/contracts';

export interface DefectExportModalProps {
  open: boolean;
  projectId: number;
  projectName?: string;
  filteredTotal: number;
  selectedBugIds: number[];
  filterQuery: BugListQuery;
  filterSummary: string;
  onClose: () => void;
  onStaleSelectionRefresh: () => void;
}

/**
 * 缺陷 Excel 导出弹窗组件。
 *
 * 会发请求：点击「开始导出」调用 POST /bugs/export 获取无宏 .xlsx 二进制流。
 * 失败呈现：解析 Blob 中的统一错误信封；当勾选记录失效（409）时提示刷新列表。
 */
export function DefectExportModal({
  open,
  projectId,
  projectName,
  filteredTotal,
  selectedBugIds,
  filterQuery,
  filterSummary,
  onClose,
  onStaleSelectionRefresh,
}: DefectExportModalProps) {
  const { message } = App.useApp();
  const [mode, setMode] = useState<'filtered' | 'selected'>('filtered');
  const [includeApiDetails, setIncludeApiDetails] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  // 打开弹窗时根据当前是否已勾选默认定位导出范围，并清理上次残留告警。
  useEffect(() => {
    if (!open) return;
    setMode(selectedBugIds.length > 0 ? 'selected' : 'filtered');
    setIncludeApiDetails(false);
    setStaleMessage(null);
  }, [open, selectedBugIds.length]);

  const targetCount = mode === 'selected' ? selectedBugIds.length : filteredTotal;

  /** 调用后端导出接口并触发浏览器保存工作簿。 */
  const handleExport = async () => {
    if (targetCount === 0 || exporting) return;
    setExporting(true);
    setStaleMessage(null);
    const body: DefectExportRequest = {
      project_id: projectId,
      mode,
      include_api_details: includeApiDetails,
      ...(mode === 'selected'
        ? { bug_ids: selectedBugIds, sort: filterQuery.sort }
        : {
            category: filterQuery.category,
            status: filterQuery.status,
            severity: filterQuery.severity,
            priority: filterQuery.priority,
            affected_version: filterQuery.affected_version,
            status_group: filterQuery.status_group,
            mine: filterQuery.mine,
            include_archived: filterQuery.include_archived,
            include_drafts: filterQuery.include_drafts,
            view: filterQuery.view,
            keyword: filterQuery.keyword,
            sort: filterQuery.sort,
          }),
    };
    try {
      const { blob, filename, count } = await bugsApi.exportExcel(body);
      triggerBlobDownload(blob, filename);
      message.success(`导出完成，共 ${count || targetCount} 条缺陷`);
      onClose();
    } catch (error) {
      const parsed = await parseBlobApiError(error, '导出失败');
      if (parsed.status === 409 && mode === 'selected') {
        const missing = Array.isArray(parsed.meta?.missing_ids)
          ? `（失效 ID：${parsed.meta.missing_ids.map((id) => `#${String(id)}`).join('、')}）`
          : '';
        setStaleMessage(`${parsed.message}${missing}`);
      } else {
        message.error(parsed.message);
      }
    } finally {
      setExporting(false);
    }
  };

  return (
    <Modal
      title="导出缺陷（Excel）"
      open={open}
      onCancel={onClose}
      width={620}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            disabled={targetCount === 0}
            onClick={handleExport}
          >
            导出 .xlsx（{targetCount} 条）
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Descriptions size="small" bordered column={1}>
          <Descriptions.Item label="目标项目">
            {projectName ? `${projectName}（#${projectId}）` : `项目 #${projectId}`}
          </Descriptions.Item>
          <Descriptions.Item label="当前筛选条件">{filterSummary}</Descriptions.Item>
          <Descriptions.Item label="字段范围">
            {includeApiDetails
              ? '常规事实字段 + 脱敏后的接口详情（请求头、请求体、实际响应结果），附带说明页标注时区（UTC+8）与脱敏规则'
              : '常规事实字段（含状态展示名、UTC+8 时间等；默认排除请求头、请求体、实际响应结果、附件与分享凭证）'}
          </Descriptions.Item>
        </Descriptions>

        <div>
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            导出范围
          </Typography.Text>
          <Radio.Group
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as 'filtered' | 'selected');
              setStaleMessage(null);
            }}
          >
            <Space direction="vertical">
              <Radio value="filtered">
                当前项目的筛选结果（全部页，共 {filteredTotal} 条）
              </Radio>
              <Radio value="selected" disabled={selectedBugIds.length === 0}>
                已勾选缺陷（已选 {selectedBugIds.length} 条）
              </Radio>
            </Space>
          </Radio.Group>
        </div>

        <Checkbox
          checked={includeApiDetails}
          onChange={(event) => setIncludeApiDetails(event.target.checked)}
        >
          包含接口详情（请求头、请求体、实际响应结果；服务端自动脱敏并在工作簿说明页标记）
        </Checkbox>

        {targetCount === 0 && (
          <Alert
            type="warning"
            showIcon
            message="当前条件下没有可导出的缺陷"
            description="请调整队列、关键字或筛选条件后再试。"
          />
        )}

        {staleMessage && (
          <Alert
            type="error"
            showIcon
            message="已勾选缺陷已失效"
            description={staleMessage}
            action={
              <Button
                size="small"
                type="primary"
                onClick={() => {
                  onStaleSelectionRefresh();
                  onClose();
                }}
              >
                刷新列表并清空勾选
              </Button>
            }
          />
        )}

        <Typography.Text type="secondary">
          服务端将按当前登录人权限实时查询并生成无宏 .xlsx；附件、活动历史与公开分享凭证不进入工作簿。
        </Typography.Text>
      </Space>
    </Modal>
  );
}
