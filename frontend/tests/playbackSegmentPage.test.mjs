import assert from 'node:assert/strict';
import test from 'node:test';
import { shouldLookupPlaybackWindow } from '../src/features/asr-evaluation/components/playbackSegmentPage.mjs';

test('playback lookup waits for timed segments and stays disabled for plain transcripts', () => {
  assert.equal(shouldLookupPlaybackWindow(true, 1, undefined), false);
  assert.equal(shouldLookupPlaybackWindow(true, 1, 0), false);
  assert.equal(shouldLookupPlaybackWindow(true, 0, 12), false);
  assert.equal(shouldLookupPlaybackWindow(false, 1, 12), false);
  assert.equal(shouldLookupPlaybackWindow(true, 1, 12), true);
});
