// ASR 音频资产 HTTP 客户端：识别与调优仅走 FunASR 调优接口。
import { api } from '@/shared/api/client';
import type { AsrAudio, AsrPage } from '../contracts';

export const asrQueryKeys = {
  /** 项目作用域和筛选条件均进入查询 key，项目切换不会复用旧资源。 */
  project: (projectId: number, resource: string, ...parts: unknown[]) =>
    ['project', projectId, 'asr', resource, ...parts] as const,
};

export const asrEvaluationApi = {
  /** 分页读取项目音频资源。 */
  listAudios: (
    projectId: number, page = 1, pageSize = 50, signal?: AbortSignal, keyword?: string,
    filters: { availability?: string; groundTruthStatus?: 'BOUND' | 'UNBOUND' } = {},
  ) =>
    api.get<AsrPage<AsrAudio>>('/asr/audio', {
      signal, params: {
        project_id: projectId, page, page_size: pageSize, keyword: keyword?.trim() || undefined,
        availability: filters.availability || undefined, ground_truth_status: filters.groundTruthStatus || undefined,
      },
    }),
  /** 供原生 audio 元素播放的同源、项目权限保护媒体地址；浏览器会自动携带会话 Cookie 和 Range。 */
  audioMediaUrl: (audioId: number, audioVersionId?: number | null) =>
    `/api/v1/asr/audio/${audioId}${audioVersionId ? `/versions/${audioVersionId}` : ''}/media`,
  /** 批量导入已有音频 URL。 */
  importAudios: (projectId: number, items: Array<{ name: string; url: string; duration_seconds?: number | null; tags?: string[] }>) =>
    api.post<{ items: AsrAudio[] }>('/asr/audio/import', { project_id: projectId, items }),
  /** 检查平台出站授权和上游 URL 可达性。 */
  checkAudio: (audioId: number) => api.post<{
    id: number; availability: string; platform_access: 'ALLOWED' | 'DENIED';
    audio_source: string; http_status: number | null;
  }>('/asr/audio/' + audioId + '/check'),
  /** 更新音频名称、时长或替换 URL；签名 URL 本身不从读取接口回显。 */
  updateAudio: (audioId: number, body: { name?: string; url?: string; duration_seconds?: number | null }) =>
    api.patch<AsrAudio>('/asr/audio/' + audioId, body),
};