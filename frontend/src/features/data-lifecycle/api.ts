import { api } from '@/shared/api/client';
import type { Paginated } from '@/shared/api/contracts';

export interface RecycleBinItem {
  id: number;
  resource_type: string;
  resource_id: string;
  display_name: string;
  project_id: number | null;
  organization_id: number | null;
  deleted_by: number | null;
  deleted_by_name: string | null;
  deleted_at: string;
  deletion_reason: string | null;
  deletion_batch_id: string;
  deletion_status: 'ACTIVE' | 'RESTORED' | 'PURGED';
  can_restore: boolean;
  restore_conflict: string | null;
  last_restore_error: string | null;
  metadata: Record<string, unknown>;
  resource_data?: Record<string, unknown> | null;
}

export interface LifecycleReceipt {
  id: number;
  succeeded: boolean;
  already_done?: boolean;
  recycle_bin_item_id?: number | null;
  error_code?: string | null;
  error?: string | null;
  meta?: Record<string, unknown> | null;
}

export interface BatchLifecycleReceipt {
  succeeded: number;
  failed: number;
  items: LifecycleReceipt[];
}

export interface LifecycleAuditEvent {
  id: number;
  event_type: string;
  result: string;
  resource_type: string;
  resource_id: string;
  project_id: number | null;
  actor_id: number | null;
  deletion_batch_id: string | null;
  reason: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface PurgePreview {
  item_id: number;
  resource_type: string;
  resource_id: string;
  display_name: string;
  allowed: boolean;
  dependencies: string[];
  effects?: string[];
}

export const dataLifecycleApi = {
  list: (params: {
    project_id?: number;
    organization_id?: number;
    resource_type?: string;
    deleted_by?: number;
    date_from?: string;
    date_to?: string;
    keyword?: string;
    page?: number;
    page_size?: number;
    sort?: string;
    order?: string;
  }) => api.get<Paginated<RecycleBinItem>>('/recycle-bin', { params }),
  detail: (itemId: number) => api.get<RecycleBinItem>(`/recycle-bin/${itemId}`),
  audit: (itemId: number) => api.get<LifecycleAuditEvent[]>(`/recycle-bin/${itemId}/audit`),
  restore: (itemId: number) => api.post<LifecycleReceipt>(`/recycle-bin/${itemId}/restore`),
  restoreMany: (itemIds: number[]) =>
    api.post<BatchLifecycleReceipt>('/recycle-bin/batch-restore', { item_ids: itemIds }),
  deleteMany: (resourceType: string, projectId: number | null, ids: number[], reason?: string) =>
    api.post<BatchLifecycleReceipt>(`/resources/${resourceType}/batch-delete`, {
      project_id: projectId,
      ids,
      reason,
    }),
  purgePreview: (itemId: number) => api.get<PurgePreview>(`/recycle-bin/${itemId}/purge-preview`),
  purge: (itemId: number, confirmation: string, reason: string) =>
    api.delete<LifecycleReceipt>(`/recycle-bin/${itemId}/permanent`, {
      data: { confirmation, reason },
    }),
};
