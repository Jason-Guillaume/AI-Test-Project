// ASR 领域 DTO；wire 字段严格使用后端 snake_case，不包含密文或签名 URL。
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface AsrAudio {
  id: number; project_id: number; name: string; url_display: string;
  duration_seconds: number | null; content_version: number; current_audio_version_id?: number | null;
  availability: string; tags: string[];
}

export interface AsrPage<T> { items: T[]; total: number; page: number; page_size: number }