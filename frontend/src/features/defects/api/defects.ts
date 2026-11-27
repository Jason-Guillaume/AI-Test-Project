// 缺陷管理相关接口。字段命名与后端 BugCreate/BugUpdate/BugResponse 严格对齐（snake_case）。
// 权限：读 = 项目可见（viewer+）；写（建/改/删/导入）= 项目 member+。
import { AxiosError } from 'axios';
import { api, client, getErrorMessage } from '@/shared/api/client';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import type { Bug, BugListQuery } from '@/features/defects/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type {
  BugBatchCreate, BugBatchCreateResponse, BugCreate, BugUpdate,
  DefectExportFileResult, DefectExportRequest, DefectImportConfirmRequest,
  DefectImportConfirmResponse, DefectImportPreviewResponse,
  DefectShareDetail, DefectShareOptions, DefectSharePreview, DefectSharePushResult,
  DefectShareSummary, DefectShareBatchResult, DefectSourceType, DefectSourceLink,
  DefectSourceContext, BugActionRequest, BugActionResponse, BugActivity,
  BugQueueCounts, BugStats, BugBatchActionRequest, BugBatchActionReceipt,
  DefectProjectSetting, DefectTemplate, DefectTemplateConfig, DefectTemplatePreview,
} from '../contracts';

/** Blob 接口失败时解析后端统一错误信封（{ code, message, meta }）。 */
export async function parseBlobApiError(
  error: unknown,
  fallback: string,
): Promise<{ status?: number; code?: string; message: string; meta?: Record<string, unknown> }> {
  if (error instanceof AxiosError && error.response?.data instanceof Blob) {
    try {
      const text = await error.response.data.text();
      const parsed = JSON.parse(text) as { code?: string; message?: string; meta?: Record<string, unknown> };
      if (parsed && typeof parsed.message === 'string') {
        return { status: error.response.status, code: parsed.code, message: parsed.message, meta: parsed.meta };
      }
    } catch {
      // 非 JSON 响应体时回退到统一文案提取。
    }
  }
  return {
    status: error instanceof AxiosError ? error.response?.status : undefined,
    message: getErrorMessage(error, fallback),
  };
}

/** 从 Content-Disposition 响应头解析 UTF-8 文件名，解析失败时使用回退名。 */
function parseFilenameFromDisposition(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback;
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return fallback;
    }
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
  return plainMatch?.[1] || fallback;
}

/** 触发浏览器下载 Blob 文件，下载后立即释放对象 URL。 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}






/**
 * 缺陷管理接口集合，由缺陷列表页调用。
 * 覆盖端点：GET /bugs、POST /bugs、POST /bugs/batch、GET/PUT/DELETE /bugs/{id}。
 */
export interface BugAttachment { id: number; filename: string; size: number; created_at: string }
export const bugsApi = {
  attachments: (id: number) => api.get<BugAttachment[]>(`/bugs/${id}/attachments`),
  uploadAttachment: (id: number, file: File) => { const data = new FormData(); data.append('file', file); return api.post<BugAttachment>(`/bugs/${id}/attachments`, data); },
  downloadAttachment: async (id: number, attachment: BugAttachment) => { const response = await client.get(`/bugs/${id}/attachments/${attachment.id}`, { responseType: 'blob' }); const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = attachment.filename; link.click(); URL.revokeObjectURL(url); },
  deleteAttachment: (id: number, attachmentId: number) => api.delete<void>(`/bugs/${id}/attachments/${attachmentId}`),

  /** 读取授权后的来源定位信息与关联，不复制证据。 */
  sourceContext: (source_type: DefectSourceType, source_id: number) => api.get<DefectSourceContext>('/bugs/sources/context', { params: { source_type, source_id } }),
  sources: (source_type: DefectSourceType, source_id: number) => api.get<DefectSourceLink[]>('/bugs/sources', { params: { source_type, source_id } }),
  bugSources: (id: number) => api.get<DefectSourceLink[]>(`/bugs/${id}/sources`),
  linkSource: (body: { source_type: DefectSourceType; source_id: number; request_key: string; bug_id?: number; bug?: BugCreate }) => api.post<DefectSourceLink>('/bugs/sources', body),
  /** 分页查询可见项目下的缺陷，支持 project_id/category/status/severity/keyword 过滤。 */
  list: (params: BugListQuery) =>
    api.get<Paginated<Bug>>('/bugs', { params }),
  /** 新建缺陷，返回创建后的 Bug。 */
  create: (body: BugCreate) => api.post<Bug>('/bugs', body),
  /** 同一项目下原子批量创建缺陷，任一行不合法整批回滚。 */
  createBatch: (body: BugBatchCreate) =>
    api.post<BugBatchCreateResponse>('/bugs/batch', body),
  /** 按主键查询缺陷详情。 */
  get: (id: number) => api.get<Bug>(`/bugs/${id}`),
  /** 更新缺陷，返回更新后的 Bug。 */
  update: (id: number, body: BugUpdate) => api.put<Bug>(`/bugs/${id}`, body),
  /** 删除缺陷，无返回体。 */
  remove: (id: number) => api.delete<void>(`/bugs/${id}`),
  removeMany: (projectId: number, ids: number[]) =>
    dataLifecycleApi.deleteMany('bug', projectId, ids),

  /** 项目队列计数；与同条件列表 total 一致。 */
  queues: (projectId: number) => api.get<BugQueueCounts>('/bugs/queues', { params: { project_id: projectId } }),
  /** 质量统计：积压、首次确认耗时、待验证时长、回归失败率。 */
  stats: (projectId: number, periodDays = 30) => api.get<BugStats>('/bugs/stats', { params: { project_id: projectId, period_days: periodDays } }),
  /** 批量治理：调优先级/归档/撤销归档，部分失败返回逐项结果。 */
  batchAction: (body: BugBatchActionRequest) => api.post<BugBatchActionReceipt>('/bugs/batch-actions', body),
  /** 活动事件时间线（新→旧）。 */
  activities: (id: number) => api.get<BugActivity[]>(`/bugs/${id}/activities`),
  /** 队列动作：确认/登记可回归/回归通过/回归失败/拒绝/判重/重开。 */
  action: (id: number, body: BugActionRequest) => api.post<BugActionResponse>(`/bugs/${id}/actions`, body),
  /** 提交草稿进入待确认队列。 */
  submitDraft: (id: number) => api.post<Bug>(`/bugs/${id}/submit-draft`),
  /** 归档（editor+）：撤销全部有效分享。 */
  archive: (id: number, reason: string) => api.post<Bug>(`/bugs/${id}/archive`, { reason }),
  /** 撤销归档（editor+）。 */
  restore: (id: number) => api.post<Bug>(`/bugs/${id}/restore`),

  /** 项目级缺陷开关。 */
  projectSetting: (projectId: number) => api.get<DefectProjectSetting>('/bugs/project-setting', { params: { project_id: projectId } }),
  updateProjectSetting: (projectId: number, body: Partial<Pick<DefectProjectSetting, 'queue_enabled' | 'reminder_enabled' | 'stale_reminder_days'>>) =>
    api.put<DefectProjectSetting>('/bugs/project-setting', body, { params: { project_id: projectId } }),
  /** 项目模板：草稿、预览、发布与版本列表。 */
  templates: (projectId: number) => api.get<DefectTemplate[]>('/bugs/templates', { params: { project_id: projectId } }),
  createTemplate: (projectId: number, config: DefectTemplateConfig) => api.post<DefectTemplate>('/bugs/templates', { config }, { params: { project_id: projectId } }),
  previewTemplate: (config: DefectTemplateConfig) => api.post<DefectTemplatePreview>('/bugs/templates/preview', { config }),
  publishTemplate: (templateId: number) => api.post<DefectTemplate>(`/bugs/templates/${templateId}/publish`),
  /** 预览飞书推送，不创建分享。 */
  previewShare: (body: DefectShareOptions & { bug_ids: number[] }) =>
    api.post<DefectSharePreview>('/bugs/shares/preview', body),
  /** 推送一条缺陷。 */
  share: (bugId: number, body: DefectShareOptions) =>
    api.post<DefectSharePushResult>(`/bugs/${bugId}/shares`, body),
  /** 批量推送同一项目的缺陷。 */
  shareBatch: (body: DefectShareOptions & { bug_ids: number[] }) =>
    api.post<DefectShareBatchResult>('/bugs/shares/batch', body),
  /** 分享历史。 */
  listShares: (bugId: number) => api.get<{ items: DefectShareSummary[] }>(`/bugs/${bugId}/shares`),
  /** 分享详情，含外部修复记录。 */
  getShare: (bugId: number, shareId: string) =>
    api.get<DefectShareDetail>(`/bugs/${bugId}/shares/${shareId}`),
  /** 撤销一条分享。 */
  revokeShare: (bugId: number, shareId: string) =>
    api.post<DefectShareSummary>(`/bugs/${bugId}/shares/${shareId}/revoke`),
  /** 重新推送。传入 access_token 时不轮换凭证。 */
  retryShare: (bugId: number, shareId: string, accessToken?: string, confirmUncertain = false) =>
    api.post<DefectSharePushResult>(`/bugs/${bugId}/shares/${shareId}/retry`, { access_token: accessToken ?? null, confirm_uncertain: confirmUncertain }),
  retryShareBatch: (batchId: string, confirmUncertain = false) =>
    api.post<DefectShareBatchResult>(`/bugs/shares/batches/${encodeURIComponent(batchId)}/retry`, { confirm_uncertain: confirmUncertain }),
  revokeShareBatch: (batchId: string) =>
    api.post<DefectShareBatchResult>(`/bugs/shares/batches/${encodeURIComponent(batchId)}/revoke`),
  /** 批量撤销。 */
  revokeShares: (items: Array<{ bug_id: number; share_id: string }>) =>
    api.post<DefectShareSummary[]>('/bugs/shares/revoke-batch', { items }),

  /** 下载缺陷空白 Excel 导入模板（.xlsx）。 */
  downloadImportTemplate: async (projectId: number): Promise<{ blob: Blob; filename: string }> => {
    const response = await client.get<Blob>('/bugs/import-template', {
      params: { project_id: projectId },
      responseType: 'blob',
    });
    const filename = parseFilenameFromDisposition(
      response.headers['content-disposition'],
      `defect-import-template-project-${projectId}.xlsx`,
    );
    return { blob: response.data, filename };
  },
  /** 上传并预览缺陷 Excel，返回逐行错误、重复提示与有效预览标识。 */
  previewImport: (projectId: number, file: File) => {
    const form = new FormData();
    form.append('project_id', String(projectId));
    form.append('file', file);
    return api.post<DefectImportPreviewResponse>('/bugs/import-preview', form);
  },
  /** 按预览标识确认导入，整批单事务写入并返回批次编号与各行缺陷 ID。 */
  confirmImport: (body: DefectImportConfirmRequest) =>
    api.post<DefectImportConfirmResponse>('/bugs/import-confirm', body),
  /** 导出当前项目筛选结果或已勾选缺陷为无宏 .xlsx 工作簿。 */
  exportExcel: async (body: DefectExportRequest): Promise<DefectExportFileResult> => {
    const response = await client.post<Blob>('/bugs/export', body, {
      responseType: 'blob',
    });
    const filename = parseFilenameFromDisposition(
      response.headers['content-disposition'],
      `defects-project-${body.project_id}.xlsx`,
    );
    const countHeader = Number(response.headers['x-export-count']);
    return {
      blob: response.data,
      filename,
      count: Number.isFinite(countHeader) ? countHeader : 0,
    };
  },
};
