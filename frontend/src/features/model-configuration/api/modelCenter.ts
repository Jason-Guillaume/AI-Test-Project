// 统一模型中心客户端；所有业务请求继续复用 shared API 错误信封与会话处理。
import { api } from '@/shared/api/client';

export type ModelCategory = 'TEXT_GENERATION' | 'ASR' | 'DIARIZATION';
export type ModelVisibility = 'PLATFORM' | 'PROJECT';

export interface ModelParameterProfile {
  id: number;
  resource_id: number;
  revision_id: number;
  name: string;
  version: number;
  values: Record<string, unknown>;
  definitions: Array<Record<string, unknown>>;
  created_at: string;
}

export interface ModelRevision {
  id: number;
  resource_id: number;
  version: number;
  provider: string;
  adapter_key: string;
  model_name: string;
  endpoint_display: string | null;
  config: Record<string, unknown>;
  capabilities: string[];
  parameter_schema: Array<Record<string, unknown>>;
  enabled: boolean;
  has_credential: boolean;
  profiles: ModelParameterProfile[];
  created_at: string;
}

export interface ModelResource {
  id: number;
  resource_key: string;
  category: ModelCategory;
  visibility: ModelVisibility;
  project_id: number | null;
  display_name: string;
  status: string;
  current_revision_id: number | null;
  defaults: Array<{ purpose: string; project_id: number | null; automatic_fallback: boolean; fallback_resource_ids: number[] }>;
  grant_project_ids: number[];
  current_revision: ModelRevision | null;
  revisions: ModelRevision[];
  diagnostic: { id: number; status: string; message: string | null; checked_at: string } | null;
}

export interface ModelCenterCatalog {
  providers: Array<{ value: string; label: string }>;
  categories: Array<{ value: ModelCategory; label: string }>;
  adapters: Array<{ category: ModelCategory; value: string; label: string; capabilities: string[] }>;
  execution_modes: string[];
}

export interface ModelAvailableResource {
  id: number; resource_key: string; category: ModelCategory; visibility: ModelVisibility;
  project_id: number | null; display_name: string;
  revision: { id: number; version: number; provider: string; adapter_key: string; model_name: string; capabilities: string[] };
  profiles: Array<{
    id: number; revision_id: number; name: string; version: number;
    values: Record<string, unknown>; definitions: Array<Record<string, unknown>>;
  }>;
}

export interface ModelDiagnosticRun {
  id: number; status: string; result: { message?: string }; created_at: string; finished_at?: string | null;
}

export interface ModelResourceWrite {
  category: ModelCategory;
  visibility: ModelVisibility;
  project_id?: number | null;
  display_name: string;
  provider: string;
  adapter_key: string;
  model_name: string;
  endpoint: string;
  credential?: string;
  credential_header?: string | null;
  config: Record<string, unknown>;
  capabilities: string[];
  parameter_schema: Array<Record<string, unknown>>;
  enabled: boolean;
  initial_profile: { name: string; values: Record<string, unknown>; definitions: Array<Record<string, unknown>> };
  grant_project_ids?: number[];
}

export interface ModelSlotSelection {
  slot: 'TEST' | 'REFERENCE_A' | 'REFERENCE_B' | 'DIARIZATION';
  resource_id: number;
  revision_id: number;
  profile_id: number;
}

export const modelCenterQueryKeys = {
  catalog: ['model-center', 'catalog'] as const,
  resources: (projectId: number | null, category?: ModelCategory) => ['model-center', 'resources', projectId, category] as const,
  available: (projectId: number, category?: ModelCategory) => ['project', projectId, 'model-center', 'available', category] as const,
  diagnostic: (runId: number) => ['model-center', 'diagnostic', runId] as const,
};

export const modelCenterApi = {
  catalog: () => api.get<ModelCenterCatalog>('/model-center/catalog'),
  list: (projectId: number | null, category?: ModelCategory, signal?: AbortSignal) =>
    api.get<{ items: ModelResource[]; total: number }>('/model-center/resources', {
      signal, params: { project_id: projectId ?? undefined, category },
    }),
  available: (projectId: number, category?: ModelCategory, signal?: AbortSignal) =>
    api.get<{ items: ModelAvailableResource[]; total: number }>('/model-center/available', {
      signal, params: { project_id: projectId, category },
    }),
  create: (body: ModelResourceWrite) => api.post<ModelResource>('/model-center/resources', body),
  addRevision: (resourceId: number, body: Omit<ModelResourceWrite, 'category' | 'visibility' | 'project_id' | 'display_name' | 'grant_project_ids'>) =>
    api.post<ModelResource>(`/model-center/resources/${resourceId}/revisions`, body),
  addProfile: (resourceId: number, body: { revision_id: number; name: string; values: Record<string, unknown>; definitions: Array<Record<string, unknown>> }) =>
    api.post<ModelParameterProfile>(`/model-center/resources/${resourceId}/profiles`, body),
  copy: (resourceId: number, projectId: number) =>
    api.post<ModelResource>(`/model-center/resources/${resourceId}/copy`, null, { params: { project_id: projectId } }),
  setDefault: (body: { category: ModelCategory; purpose: string; project_id?: number; resource_id: number; revision_id: number; profile_id?: number; fallback_resource_ids: number[]; automatic_fallback: boolean }) =>
    api.put('/model-center/defaults', body),
  grants: (resourceId: number, projectIds: number[]) =>
    api.put(`/model-center/resources/${resourceId}/grants`, { project_ids: projectIds }),
  previewImport: (items: Array<Record<string, unknown>>) =>
    api.post('/model-center/imports/preview', { items }),
  importResources: (items: Array<Record<string, unknown>>) =>
    api.post<{ items: ModelResource[]; total: number; status: string }>('/model-center/imports', { items }),
  createDiagnostic: (resourceId: number, body: { project_id: number; profile_id?: number; audio_id?: number; confirm_model_call: true }) =>
    api.post<{ id: number; status: string }>(`/model-center/resources/${resourceId}/diagnostics`, body),
  getDiagnostic: (runId: number, signal?: AbortSignal) =>
    api.get<ModelDiagnosticRun>(`/model-center/diagnostics/${runId}`, { signal }),
};
