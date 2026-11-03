// ASR 评测领域 DTO；wire 字段严格使用后端 snake_case，不包含密文或签名 URL。
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type AsrRole = 'TEST' | 'REFERENCE';
export type AsrTaskType = 'TRANSCRIPTION' | 'DIARIZATION';

export interface AsrAudio {
  id: number; project_id: number; name: string; url_display: string;
  duration_seconds: number | null; content_version: number; availability: string; tags: string[];
}

export interface AsrConnection {
  id: number; project_id: number; name: string; role: AsrRole | null; task_type: AsrTaskType; provider_id: string;
  model_id: string; version: number; endpoint_display: string; method: 'POST';
  headers: Record<string, string>; request_template: Record<string, JsonValue>;
  response_mapping: Record<string, JsonValue>; async_config: Record<string, JsonValue> | null;
  parameter_definitions: Array<Record<string, JsonValue>>;
  timeout_seconds: number; max_response_bytes: number; has_secret: boolean;
  secret_header: string | null; enabled: boolean;
}

export interface AsrParameterDefinition {
  path: string; display_name: string;
  value_type: 'string' | 'integer' | 'number' | 'boolean' | 'object' | 'array';
  minimum?: number | null; maximum?: number | null; choices?: JsonValue[] | null;
  description: string; source: string;
}

export interface AsrParameterSet {
  id: number; project_id: number; connection_id: number; name: string; version: number;
  parameters: Record<string, JsonValue>; definitions: AsrParameterDefinition[];
}

export interface AsrSchedule {
  id: number; project_id: number; name: string; audio_ids: number[]; connection_ids: number[];
  parameter_set_id: number; schedule_type: 'ONCE' | 'DAILY'; timezone: string; local_time: string;
  scheduled_at: string | null; next_run_at: string | null; enabled: boolean;
  last_trigger_status: string | null;
}

export interface AsrModelRun {
  id: number; audio_id: number; connection_id: number; role: AsrRole; status: string;
  audio_version_id?: number | null; segments?: AsrTranscriptSegment[];
  remote_task_id: string | null; request_snapshot: Record<string, JsonValue>;
  transcript: string | null; error_message: string | null; duration_ms: number | null;
  parameter_set_id?: number | null; connection_name?: string; model_id?: string;
}

export interface AsrComparisonSummary {
  diff_blocks: number; unanimous_blocks: number; reviewed_blocks: number;
  unresolved_blocks: number; pending_review_blocks: number;
  text_difference_ratios: Record<string, number | null>; metric_definition: string;
  degradation_reason: string | null;
}

export interface AsrJob {
  id: number; project_id: number; status: string; cancel_requested: boolean;
  config_snapshot: Record<string, JsonValue>; created_at: string;
  runs?: AsrModelRun[];
  comparisons?: Array<{ id: number; audio_id: number; status: string }>;
}

export interface AsrDiffBlock {
  id: number; comparison_id: number; ordinal: number;
  test_text: string; reference_a_text: string; reference_b_text: string;
  labels: string[]; timing_source: 'PROVIDER' | 'REFERENCE_ANCHOR' | 'UNAVAILABLE';
  timing_role: string | null; start_seconds: number | null; end_seconds: number | null;
  review_status: 'UNREVIEWED' | 'CONFIRMED' | 'UNRESOLVED';
  confirmed_text: string | null; review_version: number;
}

export interface AsrComparison {
  id: number; project_id: number; job_id: number;
  audio: {
    id: number; name: string; url_display: string; duration_seconds: number | null;
    content_version: number | null; media_url: string | null;
    audio_version_id?: number | null; version_available?: boolean;
  } | null;
  job_status: string; version: number; status: 'COMPLETE' | 'INCOMPLETE';
  degraded: boolean; summary: AsrComparisonSummary;
  models: Array<{
    run_id: number; role: AsrRole; status: string; name: string;
    model_id: string | null; connection_version: number | null; transcript: string | null;
    error_message: string | null; duration_ms: number | null; parameter_set_id?: number | null;
  }>;
}

export interface AsrTranscriptSegment {
  id: string; segment_index: number; source_segment_id: string | null; text: string;
  start_ms: number | null; end_ms: number | null; start_offset: number | null; end_offset: number | null;
  native_speaker_id: string | null; confidence: number | null; channel: string | null;
  word_times: Array<Record<string, JsonValue>>;
  assignments: Array<{
    id: number; speaker_id: number | null; turn_id: number | null; status: string; source: string;
    review_status: string; review_version: number;
  }>;
}

export interface AsrProcessingRun {
  id: number; task_type: string; audio_version_id: number; connection_id: number | null;
  status: string; attempts: number; result_id: number | null; error_message: string | null;
  duration_ms: number | null; created_at: string;
}

export interface AsrSpeaker {
  id: number; result_id: number; source_label: string; channel: string | null;
  display_name: string; first_seen_ms: number | null; revision: number;
  turn_count: number; speech_duration_ms: number;
}

export interface AsrSpeakerTurn {
  id: number; stable_id: string; turn_index: number; speaker_id: number | null;
  source_speaker_id: string | null; display_name: string | null;
  start_ms: number; end_ms: number; text: string | null; channel: string | null;
  confidence: number | null; is_overlap: boolean;
}

export interface AsrWorkbench {
  run: AsrModelRun & {
    project_id: number; job_id: number; audio_version_id: number | null; request_snapshot: Record<string, JsonValue>;
    segment_count: number; created_at: string; finished_at: string | null;
  };
  job: { id: number; status: string } | null;
  audio: {
    id: number; project_id: number; name: string; audio_version_id: number | null; content_version: number | null;
    duration_seconds: number | null; url_display: string | null; media_url: string | null; version_available: boolean;
  } | null;
  model: { name: string; model_id: string; connection_version: number } | null;
  diarization: {
    processing_run: AsrProcessingRun | null; result_id: number | null; schema_version: string | null;
    timeline: string | null; fusion_version_id: number | null; fusion_version: number | null; fusion_status: string;
  };
}

export interface AsrAudioMetadata {
  audio_id: number; audio_version_id: number; content_version: number;
  source_info: Record<string, JsonValue>; original_format: Record<string, JsonValue>;
  analysis_pcm: Record<string, JsonValue>; signal_statistics: Record<string, JsonValue>;
  processed_range: Record<string, JsonValue>; warnings: string[];
  analysis_status: string; processing_run: AsrProcessingRun | null;
}

export interface AsrSuggestion {
  id: number; comparison_id: number; evidence_block_ids: number[];
  observation: string; evidence: string; parameter_path: string | null;
  current_value: JsonValue; candidate_value: JsonValue; rationale: string;
  validation_steps: string; status: string;
}

export interface AsrSuggestionJob {
  id: number; project_id: number; comparison_id: number; model_config_id: number;
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'RECONCILIATION_REQUIRED';
  attempts: number; result: { items?: AsrSuggestion[]; source?: string; message?: string };
  error_message: string | null; created_at: string; started_at: string | null; finished_at: string | null;
}

export interface AsrExperiment {
  id: number; project_id: number; comparison_id: number; baseline_parameter_set_id: number;
  candidate_parameters: Record<string, JsonValue>; change_summary: string;
  reuse_reference_results: boolean; reference_source_comparison_id: number | null;
  status: string; candidate_job_id: number | null; candidate_job_status?: string | null; failure_reason?: string | null;
}

export interface AsrPage<T> { items: T[]; total: number; page: number; page_size: number }

export interface AsrComparisonListItem {
  id: number; project_id: number; job_id: number; audio_id: number; audio_name: string;
  version: number; status: string; degraded: boolean; summary: AsrComparisonSummary;
  created_at: string;
}
