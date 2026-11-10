import { api } from '@/shared/api/client';
import type { AsrAudio, JsonValue } from '../contracts';

export interface FunAsrParameterDefinition {
  path: string; display_name: string; value_type: string; minimum: number | null; maximum: number | null;
  exclusive_minimum: number | null; default: JsonValue; unit: string | null; required: boolean;
  nullable: boolean; tunable: boolean; active_when: Record<string, JsonValue> | null;
  description: string; tuning_note: string | null;
}
export interface FunAsrInterface {
  id: number; name: string; method: string; path: string; version: number; source_hash: string | null;
  status: string; source_type: string;
}
export interface FunAsrEnvironment {
  id: number; name: string; display_name: string; is_default: boolean;
}
export interface FunAsrBinding {
  id: number; project_id: number; api_interface_id: number; interface_name: string; method: string; path: string;
  interface_version: number; source_hash: string | null; interface_updated: boolean; interface_removed: boolean;
  environment_name: string; response_mapping: Record<string, unknown>; response_mapping_verified: boolean; timeout_seconds: number;
  max_response_bytes: number; has_credential: boolean; parameter_seed: Record<string, JsonValue>;
  parameter_seed_warnings: string[];
}
export interface FunAsrGroundTruth {
  id: number; audio_id: number; audio_name: string; audio_version_id: number; audio_content_version: number; version: number;
  raw_sha256: string; transcript: string; created_at: string;
}
export interface FunAsrTuningItem {
  id: number; audio_id: number; audio_version_id: number; ground_truth_version_id: number; status: string;
  review_status: string; response_received: boolean; response_json: JsonValue | null; normalized_json: Record<string, unknown> | null;
  ground_truth_json: Record<string, unknown> | null; answer_markdown: string | null; response_markdown: string | null;
  metrics: Record<string, number | null> | null; review_json: Record<string, unknown> | null;
  duration_ms: number | null; error_message: string | null;
}
export interface FunAsrTuningRound {
  id: number; ordinal: number; status: string; parameters: Record<string, JsonValue>;
  parameter_hash: string; metrics: Record<string, unknown>; report_json: Record<string, unknown> | null;
  report_markdown: string | null; candidate_json: Record<string, unknown> | null; accepted: boolean | null;
  stop_reason: string | null; items?: FunAsrTuningItem[];
}
export interface FunAsrTuningSession {
  id: number; project_id: number; binding_id: number; model_config_id: number; status: string; mode: string;
  current_round: number; best_round_id: number | null; best_micro_cer: number | null; total_rounds: number;
  completed_items: number; total_items: number; asr_requests_used: number; max_asr_requests: number;
  ai_calls_used: number; max_ai_calls: number; stop_reason: string | null; next_run_at: string | null;
  window_enabled: boolean; night_start: string; night_end: string; created_at: string; finished_at: string | null;
  config_snapshot?: Record<string, unknown>; rounds?: FunAsrTuningRound[];
}

export const funasrTuningApi = {
  definitions: () => api.get<{ items: FunAsrParameterDefinition[]; source: string }>('/asr/funasr/definitions'),
  interfaces: (projectId: number) => api.get<{ items: FunAsrInterface[] }>(`/asr/funasr/interfaces`, { params: { project_id: projectId } }),
  environments: (projectId: number) => api.get<{ items: FunAsrEnvironment[] }>(`/asr/funasr/environments`, { params: { project_id: projectId } }),
  bindings: (projectId: number) => api.get<{ items: FunAsrBinding[] }>(`/asr/funasr/bindings`, { params: { project_id: projectId } }),
  createBinding: (body: Record<string, unknown>) => api.post<FunAsrBinding>('/asr/funasr/bindings', body),
  updateBinding: (id: number, response_mapping: Record<string, unknown>, response_sample: JsonValue) =>
    api.patch<FunAsrBinding>(`/asr/funasr/bindings/${id}`, { response_mapping, response_sample }),
  previewMapping: (document: JsonValue, mapping: Record<string, unknown>, source: 'ground_truth' | 'recognition') =>
    api.post<{ normalized_json: Record<string, unknown>; markdown: string; warnings: string[] }>(
      '/asr/funasr/mapping-preview', { document, mapping, source, audio_version_id: 1 }),
  groundTruth: (projectId: number) => api.get<{ items: FunAsrGroundTruth[] }>('/asr/funasr/ground-truth', { params: { project_id: projectId } }),
  createGroundTruth: (audioId: number, document: JsonValue, mapping: Record<string, unknown>) =>
    api.post<FunAsrGroundTruth & { warnings: string[] }>(`/asr/funasr/audio/${audioId}/ground-truth`, { document, mapping }),
  models: (projectId: number) => api.get<{ items: Array<{ id: number; label: string; model_name: string }> }>(
    '/asr/funasr/models', { params: { project_id: projectId } }),
  sessions: (projectId: number) => api.get<{ items: FunAsrTuningSession[] }>('/asr/funasr/sessions', { params: { project_id: projectId } }),
  session: (id: number) => api.get<FunAsrTuningSession>(`/asr/funasr/sessions/${id}`),
  createSession: (body: Record<string, unknown>) => api.post<FunAsrTuningSession>('/asr/funasr/sessions', body),
  pause: (id: number) => api.post<FunAsrTuningSession>(`/asr/funasr/sessions/${id}/pause`),
  resume: (id: number) => api.post<FunAsrTuningSession>(`/asr/funasr/sessions/${id}/resume`),
  stop: (id: number) => api.post<FunAsrTuningSession>(`/asr/funasr/sessions/${id}/stop`),
  retryFailed: (id: number) => api.post<FunAsrTuningSession>(`/asr/funasr/sessions/${id}/retry-failed`),
  retryAnalysis: (id: number) => api.post<FunAsrTuningSession>(`/asr/funasr/sessions/${id}/retry-analysis`),
  audioList: (projectId: number) => api.get<{ items: AsrAudio[]; total: number }>('/asr/audio', { params: { project_id: projectId, page: 1, page_size: 200 } }),
};
