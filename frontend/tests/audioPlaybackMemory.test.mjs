import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clearAudioPlaybackMemory,
  observeAudioSource,
  rememberAudioPlayback,
} from '../src/features/asr-evaluation/components/audioPlaybackMemory.mjs';

test('same audio route switch restores position and active playback state', () => {
  clearAudioPlaybackMemory();
  const source = '/api/v1/asr/audio/1/versions/1/media';
  assert.equal(observeAudioSource(source), null);
  rememberAudioPlayback({ source, currentTime: 18.75, paused: false, volume: 0.6, playbackRate: 1.25 });
  assert.deepEqual(observeAudioSource(source), {
    source, currentTime: 18.75, paused: false, volume: 0.6, playbackRate: 1.25,
  });
});

test('changing audio source discards the prior playback position', () => {
  clearAudioPlaybackMemory();
  const first = '/api/v1/asr/audio/1/versions/1/media';
  const second = '/api/v1/asr/audio/2/versions/1/media';
  observeAudioSource(first);
  rememberAudioPlayback({ source: first, currentTime: 31, paused: false, volume: 1, playbackRate: 1 });
  assert.equal(observeAudioSource(null), null);
  assert.deepEqual(observeAudioSource(first), {
    source: first, currentTime: 31, paused: false, volume: 1, playbackRate: 1,
  });
  assert.equal(observeAudioSource(second), null);
  assert.equal(observeAudioSource(first), null);
});
