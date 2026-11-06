export interface AudioPlaybackSnapshot {
  source: string;
  currentTime: number;
  paused: boolean;
  volume: number;
  playbackRate: number;
}

export function observeAudioSource(source: string | null): AudioPlaybackSnapshot | null;
export function rememberAudioPlayback(snapshot: AudioPlaybackSnapshot): void;
export function clearAudioPlaybackMemory(): void;
