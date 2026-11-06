/** Do not start periodic playback lookups until the full segment query confirms timed data exists. */
export function shouldLookupPlaybackWindow(hasTranscript, playbackTime, timedSegmentCount) {
  return Boolean(hasTranscript) && Number.isFinite(playbackTime) && playbackTime > 0
    && Number.isSafeInteger(timedSegmentCount) && timedSegmentCount > 0;
}
