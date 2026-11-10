export type GroundTruthUiState = 'loading' | 'error' | 'unbound' | 'current' | 'mismatch';
export type RecentRunUiState = 'loading' | 'error' | 'unassessed' | 'assessed';

export function parsePastedAudioRecords(value: string): Array<{ name: string; url: string }>;
export function formatAudioDuration(seconds: number | null): string;
export function groundTruthUiState(
  answer: { audio_content_version?: number } | null | undefined,
  contentVersion: number,
  queryStatus: 'pending' | 'error' | 'success',
): GroundTruthUiState;
export function recentRunUiState(
  recentRun: object | null | undefined,
  queryStatus: 'pending' | 'error' | 'success',
  hasData: boolean,
): RecentRunUiState;
