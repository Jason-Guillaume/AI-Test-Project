/**
 * Holds one in-page playback snapshot while the workbench route changes between
 * runs. The snapshot is deliberately memory-only and is discarded as soon as
 * the media source changes.
 */
let activeSource = null;
let playbackSnapshot = null;

export function observeAudioSource(source) {
  // A pending workbench query may briefly render without an audio source. Keep
  // the last version's snapshot through that transient state; only a concrete
  // new media URL means the user changed recordings.
  if (!source) return null;
  if (activeSource !== source) {
    activeSource = source;
    playbackSnapshot = null;
    return null;
  }
  return playbackSnapshot?.source === source ? { ...playbackSnapshot } : null;
}

export function rememberAudioPlayback(snapshot) {
  if (!snapshot || typeof snapshot.source !== 'string' || !snapshot.source) return;
  playbackSnapshot = {
    source: snapshot.source,
    currentTime: Number.isFinite(snapshot.currentTime) ? Math.max(0, snapshot.currentTime) : 0,
    paused: Boolean(snapshot.paused),
    volume: Number.isFinite(snapshot.volume) ? Math.min(1, Math.max(0, snapshot.volume)) : 1,
    playbackRate: Number.isFinite(snapshot.playbackRate) ? snapshot.playbackRate : 1,
  };
}

export function clearAudioPlaybackMemory() {
  activeSource = null;
  playbackSnapshot = null;
}
