// ASR 评测 HTTP 客户端：仅复用 shared api 实例；凭据只在创建连接时短暂提交。
import { api } from '@/shared/api/client';
import type { AxiosRequestConfig } from 'axios';
import type {
  AsrAudio, AsrComparison, AsrComparisonListItem, AsrConnection, AsrDiffBlock, AsrExperiment, AsrJob,
  AsrPage, AsrParameterSet, AsrSchedule, AsrSuggestion, AsrSuggestionJob,
  AsrAudioMetadata, AsrProcessingRun, AsrSpeaker, AsrSpeakerTurn, AsrTranscriptSegment, AsrWorkbench,
  JsonValue,
} from '../contracts';

export const asrQueryKeys = {
  /** 项目作用域和筛选条件均进入查询 key，项目切换不会复用旧资源。 */
  project: (projectId: number, resource: string, ...parts: unknown[]) =>
    ['project', projectId, 'asr', resource, ...parts] as const,
};

export const asrEvaluationApi = {
  /** 分页读取项目音频资源。 */
  listAudios: (projectId: number, page = 1, pageSize = 50, signal?: AbortSignal, keyword?: string) =>
    api.get<AsrPage<AsrAudio>>('/asr/audio', {
      signal, params: { project_id: projectId, page, page_size: pageSize, keyword: keyword?.trim() || undefined },
    }),
  /** 批量导入已有音频 URL。 */
  importAudios: (projectId: number, items: Array<{ name: string; url: string; duration_seconds?: number | null; tags?: string[] }>) =>
    api.post<{ items: AsrAudio[] }>('/asr/audio/import', { project_id: projectId, items }),
  /** 检查平台出站授权和上游 URL 可达性。 */
  checkAudio: (audioId: number) => api.post('/asr/audio/' + audioId + '/check'),
  /** 更新音频名称、时长或替换 URL；签名 URL 本身不从读取接口回显。 */
  updateAudio: (audioId: number, body: { name?: string; url?: string; duration_seconds?: number | null }) =>
    api.patch<AsrAudio>('/asr/audio/' + audioId, body),
  /** 创建一个新的通用 JSON HTTP 连接版本。 */
  createConnection: (body: Record<string, unknown>) => api.post<AsrConnection>('/asr/connections', body),
  /** 为连接创建一个短后台诊断运行。 */
  createConnectionCheck: (connectionId: number, body: { audio_id: number; parameter_set_id?: number }) =>
    api.post<AsrJob>('/asr/connections/' + connectionId + '/checks', body),
  /** 列出项目连接配置和历史版本。 */
  listConnections: (projectId: number, signal?: AbortSignal, taskType: 'TRANSCRIPTION' | 'DIARIZATION' = 'TRANSCRIPTION') =>
    api.get<{ items: AsrConnection[] }>('/asr/connections', { signal, params: { project_id: projectId, task_type: taskType } }),
  /** 创建待测参数方案的新版本。 */
  createParameterSet: (body: Record<string, unknown>) => api.post<AsrParameterSet>('/asr/parameter-sets', body),
  /** 列出参数配置版本。 */
  listParameterSets: (projectId: number, signal?: AbortSignal) =>
    api.get<{ items: AsrParameterSet[] }>('/asr/parameter-sets', { signal, params: { project_id: projectId } }),
  /** 创建三方后台识别批次。 */
  createJob: (body: { project_id: number; audio_ids: number[]; connection_ids?: number[]; parameter_set_id?: number; model_slots?: Array<{ slot: 'TEST' | 'REFERENCE_A' | 'REFERENCE_B' | 'DIARIZATION'; resource_id: number; revision_id: number; profile_id: number }> }) =>
    api.post<AsrJob>('/asr/jobs', body),
  /** 分页读取评测批次。 */
  listJobs: (projectId: number, page = 1, signal?: AbortSignal) =>
    api.get<AsrPage<AsrJob>>('/asr/jobs', { signal, params: { project_id: projectId, page, page_size: 20 } }),
  /** 读取任务状态、三方结果和比较入口。 */
  getJob: (jobId: number, config?: AxiosRequestConfig) => api.get<AsrJob>('/asr/jobs/' + jobId, config),
  /** 停止新提交或本地轮询跟踪。 */
  cancelJob: (jobId: number) => api.post<AsrJob>('/asr/jobs/' + jobId + '/cancel'),
  /** 按原配置创建新的完整三方批次；失败批次保持只读。 */
  retryJob: (jobId: number) => api.post<AsrJob>('/asr/jobs/' + jobId + '/retry'),
  /** 创建固定配置的一次性或每日夜间计划。 */
  createSchedule: (body: Record<string, unknown>) => api.post<AsrSchedule>('/asr/schedules', body),
  /** 列出项目夜间计划。 */
  listSchedules: (projectId: number, signal?: AbortSignal) =>
    api.get<{ items: AsrSchedule[] }>('/asr/schedules', { signal, params: { project_id: projectId } }),
  /** 暂停或恢复项目夜间计划。 */
  updateSchedule: (scheduleId: number, enabled: boolean) =>
    api.patch<AsrSchedule>('/asr/schedules/' + scheduleId, { enabled }),
  /** 分页读取识别对比版本。 */
  listComparisons: (projectId: number, page = 1, pageSize = 20, signal?: AbortSignal) =>
    api.get<AsrPage<AsrComparisonListItem>>('/asr/comparisons', { signal, params: { project_id: projectId, page, page_size: pageSize } }),
  /** 读取三方运行、统计口径与本版本人工确认状态。 */
  getComparison: (comparisonId: number, signal?: AbortSignal) =>
    api.get<AsrComparison>('/asr/comparisons/' + comparisonId, { signal }),
  /** 下载带项目权限校验的 JSON 或 CSV 结果。 */
  exportComparison: (comparisonId: number, format: 'json' | 'csv') =>
    api.get<Blob>('/asr/comparisons/' + comparisonId + '/exports', { params: { format }, responseType: 'blob' }),
  /** 按差异、确认或一致片段筛选并分页。 */
  listBlocks: (comparisonId: number, filter = 'DIFFERENCES', signal?: AbortSignal, page = 1) =>
    api.get<AsrPage<AsrDiffBlock>>('/asr/comparisons/' + comparisonId + '/blocks', {
      signal,
      params: { page, page_size: 100, filter },
    }),
  /** 乐观锁确认差异片段或明确加入人工校对集。 */
  reviewBlock: (comparisonId: number, blockId: number, body: Record<string, unknown>) =>
    api.put<AsrDiffBlock>('/asr/comparisons/' + comparisonId + '/reviews/' + blockId, body),
  /** 读取人工复核历史与操作者信息。 */
  reviewHistory: (comparisonId: number, blockId: number, signal?: AbortSignal) =>
    api.get<{ items: Array<{ version: number; review_status: string; confirmed_text: string | null; include_reference_sample: boolean; reviewer: string; created_at: string }> }>(
      '/asr/comparisons/' + comparisonId + '/reviews/' + blockId + '/history', { signal },
    ),
  /** 基于已确认证据生成参数建议。 */
  createSuggestions: (comparisonId: number, modelConfigId: number) =>
    api.post<AsrSuggestionJob>(
      '/asr/comparisons/' + comparisonId + '/suggestion-jobs', null,
      { params: { model_config_id: modelConfigId } },
    ),
  listSuggestionJobs: (comparisonId: number, signal?: AbortSignal) =>
    api.get<{ items: AsrSuggestionJob[] }>(`/asr/comparisons/${comparisonId}/suggestion-jobs`, { signal }),
  retrySuggestionJob: (jobId: number) =>
    api.post<AsrSuggestionJob>(`/asr/suggestion-jobs/${jobId}/retry`),
  /** 列出对比版本关联的建议。 */
  listSuggestions: (comparisonId: number, signal?: AbortSignal) =>
    api.get<{ items: AsrSuggestion[] }>('/asr/comparisons/' + comparisonId + '/suggestions', { signal }),
  /** 创建不覆盖基线的候选参数草稿。 */
  createExperiment: (body: {
    comparison_id: number; candidate_parameters: Record<string, unknown>; change_summary: string;
    reuse_reference_results: boolean;
  }) =>
    api.post<AsrExperiment>('/asr/experiments', body),
  /** 列出候选实验和复跑状态。 */
  listExperiments: (projectId: number, signal?: AbortSignal) =>
    api.get<{ items: AsrExperiment[] }>('/asr/experiments', { signal, params: { project_id: projectId } }),
  /** 按候选参数启动新的后台三方识别批次。 */
  runExperiment: (experimentId: number) =>
    api.post<{ experiment: AsrExperiment; job: AsrJob }>('/asr/experiments/' + experimentId + '/run'),
  /** 查看后台执行器最近心跳。 */
  runtimeStatus: (signal?: AbortSignal) =>
    api.get<{ online: boolean; process_alive: boolean; business_ready: boolean; status: string; last_seen_at: string | null }>('/asr/runtime-status', { signal }),
  /** 读取固定音频版本、模型参数快照与最新说话人关联，作为单模型工作台的页面合同。 */
  getRunWorkbench: (runId: number, signal?: AbortSignal) =>
    api.get<AsrWorkbench>('/asr/runs/' + runId, { signal }),
  /** 按时间与稳定段 ID 分页读取转写片段，支持说话人与未知/混合筛选。 */
  listRunSegments: (
    runId: number, page = 1, signal?: AbortSignal,
    filters: { speaker_id?: number; unknown_only?: boolean; mixed_only?: boolean; search?: string } = {},
  ) => api.get<AsrPage<AsrTranscriptSegment>>('/asr/runs/' + runId + '/segments', {
    signal, params: { page, page_size: 100, ...filters },
  }),
  /** 独立排队固定音频版本的说话人处理，重复请求由服务端去重。 */
  createDiarizationRun: (audioId: number, audioVersionId: number, body: {
    resource_id?: number; revision_id?: number; profile_id?: number;
    connection_id?: number; parameters?: Record<string, unknown>;
  }) =>
    api.post<AsrProcessingRun>(
      '/asr/audio/' + audioId + '/versions/' + audioVersionId + '/diarization-runs', body,
    ),
  /** 查询独立处理状态；该查询不依赖三方批次是否已完成。 */
  getProcessingRun: (processingRunId: number, signal?: AbortSignal) =>
    api.get<AsrProcessingRun>('/asr/processing-runs/' + processingRunId, { signal }),
  /** 仅重试处理阶段，不重新建立三家 ASR 运行。 */
  retryProcessingRun: (processingRunId: number) =>
    api.post<AsrProcessingRun>('/asr/processing-runs/' + processingRunId + '/retry'),
  /** 为当前转写显式选择同一音频版本的说话人结果并保存关联版本。 */
  createSpeakerFusion: (runId: number, diarizationResultId: number) =>
    api.post<Record<string, unknown>>('/asr/runs/' + runId + '/speaker-assignments', {
      diarization_result_id: diarizationResultId,
    }),
  /** 读取结果范围内全量人数、未知、重叠和发言时长汇总。 */
  listSpeakers: (resultId: number, signal?: AbortSignal) =>
    api.get<{ items: AsrSpeaker[]; summary: Record<string, JsonValue> }>(
      '/asr/diarization-results/' + resultId + '/speakers', { signal },
    ),
  /** 分页读取说话人区间，支持按区间而非全量转写过滤。 */
  listSpeakerTurns: (
    resultId: number, page = 1, signal?: AbortSignal,
    filters: { speaker_id?: number; unknown_only?: boolean; overlap_only?: boolean } = {},
  ) => api.get<AsrPage<AsrSpeakerTurn>>('/asr/diarization-results/' + resultId + '/turns', {
    signal, params: { page, page_size: 100, ...filters },
  }),
  /** 保存带 expected_version 的人工归属确认或未知结论。 */
  reviewSpeakerAssignment: (
    assignmentId: number, body: { expected_version: number; review_status: 'CONFIRMED' | 'UNRESOLVED'; speaker_id: number | null },
  ) => api.put('/asr/speaker-assignments/' + assignmentId + '/review', body),
  /** 修改当前说话人结果内显示名并创建审计历史。 */
  renameSpeaker: (speakerId: number, displayName: string) =>
    api.patch('/asr/diarization-results/speakers/' + speakerId, { display_name: displayName }),
  /** 读取固定音频版本的来源、后台元数据与真实分析摘要。 */
  getAudioMetadata: (audioId: number, audioVersionId: number, signal?: AbortSignal) =>
    api.get<AsrAudioMetadata>(
      '/asr/audio/' + audioId + '/versions/' + audioVersionId + '/metadata', { signal },
    ),
  /** 明确触发一次后台音频分析；页面加载不会下载整条音频。 */
  startAudioAnalysis: (audioId: number, audioVersionId: number) =>
    api.post<AsrProcessingRun>(
      '/asr/audio/' + audioId + '/versions/' + audioVersionId + '/analysis-runs', {},
    ),
  /** 按峰值级别按需读取服务端已生成的数据。 */
  getAudioPeaks: (audioId: number, audioVersionId: number, resolution: 2048 | 8192, signal?: AbortSignal) =>
    api.get<Record<string, JsonValue>>(
      '/asr/audio/' + audioId + '/versions/' + audioVersionId + '/peaks',
      { signal, params: { resolution } },
    ),
  /** 导出指定转写原文和说话人关联，下载权限由后端按项目复核。 */
  exportRun: (runId: number, format: 'json' | 'txt') =>
    api.get<Blob>('/asr/runs/' + runId + '/exports', { params: { format }, responseType: 'blob' }),
};
