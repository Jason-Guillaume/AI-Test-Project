import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import {
  formatAudioDuration,
  groundTruthUiState,
  parsePastedAudioRecords,
} from '../src/features/asr-evaluation/audioAssetUi.mjs';

test('batch audio paste parses pairs and reports the original line on incomplete records', () => {
  assert.deepEqual(parsePastedAudioRecords(
    '录音一：\nhttps://media.example/a.mp3?sig=secret\n\n录音二\nhttps://media.example/b.wav',
  ), [
    { name: '录音一', url: 'https://media.example/a.mp3?sig=secret' },
    { name: '录音二', url: 'https://media.example/b.wav' },
  ]);
  assert.throws(() => parsePastedAudioRecords('录音一\n\n录音二'), /第 3 行/);
  assert.throws(() => parsePastedAudioRecords('https://media.example/a.mp3'), /第 1 行/);
});

test('audio duration uses compact mm:ss and hh:mm:ss formats', () => {
  assert.equal(formatAudioDuration(null), '未解析');
  assert.equal(formatAudioDuration(87), '01:27');
  assert.equal(formatAudioDuration(3661), '01:01:01');
});

test('answer read failures never collapse to an unbound state', () => {
  assert.equal(groundTruthUiState(undefined, 1, 'pending'), 'loading');
  assert.equal(groundTruthUiState(undefined, 1, 'error'), 'error');
  assert.equal(groundTruthUiState(undefined, 1, 'success'), 'unbound');
  assert.equal(groundTruthUiState({ audio_content_version: 1 }, 1, 'success'), 'current');
  assert.equal(groundTruthUiState({ audio_content_version: 1 }, 2, 'success'), 'mismatch');
});

test('audio page keeps audition, batch checks and JSON preview without task creation', async () => {
  const source = await readFile(new URL('../src/pages/console/ASREvaluation/AudioPage.tsx', import.meta.url), 'utf8');
  assert.match(source, /audioMediaUrl\(selectedAudio\.id, selectedAudio\.current_audio_version_id\)/);
  assert.match(source, /Math\.min\(3, ids\.length\)/);
  assert.match(source, /Upload\.Dragger/);
  assert.match(source, /groundTruthDocument/);
  assert.match(source, /确认绑定/);
  assert.doesNotMatch(source, /\/console\/asr\/(jobs|runs|comparisons|experiments)/);
  assert.doesNotMatch(source, /创建评测/);
});

