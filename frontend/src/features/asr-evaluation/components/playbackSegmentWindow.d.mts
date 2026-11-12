export function fetchCompletePlaybackWindow<T extends { total: number; page_size: number; items: unknown[] }>(
  fetchPage: (page: number, signal?: AbortSignal) => Promise<T>, signal?: AbortSignal, concurrency?: number,
): Promise<T>;
