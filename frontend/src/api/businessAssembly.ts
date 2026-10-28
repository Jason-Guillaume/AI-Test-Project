// 业务组装异步任务、版本化草稿、确定性校验与原子保存 API。
import { api } from './client';
import type { Task } from './tasks';
import type { BusinessAssemblyDraft, BusinessAssemblyDraftContent, BusinessAssemblyValidation } from '@/types';

export const businessAssemblyApi = {
  createTask: (projectId: number, body: { title?: string; goal: string; document_version_ids: number[]; request_key: string }) =>
    api.post<Task>(`/projects/${projectId}/business-assembly-tasks`, body),
  draftForRun: (runId: number) => api.get<BusinessAssemblyDraft>(`/task-runs/${runId}/business-assembly-draft`),
  getDraft: (draftId: number) => api.get<BusinessAssemblyDraft>(`/business-assembly-drafts/${draftId}`),
  updateDraft: (draftId: number, body: { expected_revision: number; content: BusinessAssemblyDraftContent }) =>
    api.patch<BusinessAssemblyDraft>(`/business-assembly-drafts/${draftId}`, body),
  validateDraft: (draftId: number, revision: number) =>
    api.post<BusinessAssemblyValidation>(`/business-assembly-drafts/${draftId}/validate`, { revision }),
  applyDraft: (draftId: number, body: { revision: number; flow_indexes: number[]; idempotency_key: string }) =>
    api.post<{ draft_id: number; revision: number; domain_id: number; flow_ids: number[]; replayed: boolean }>(
      `/business-assembly-drafts/${draftId}/apply`, body,
    ),
};
