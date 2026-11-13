import assert from 'node:assert/strict';
import test from 'node:test';
import { parseJenkinsCustomParameters } from './jenkinsParameters.ts';

test('accepts safe custom parameters and an empty object', () => {
  assert.deepEqual(parseJenkinsCustomParameters('{"TEST_SUITE":"smoke"}'), { TEST_SUITE: 'smoke' });
  assert.deepEqual(parseJenkinsCustomParameters(''), {});
});

test('rejects reserved and case-conflicting parameter names', () => {
  assert.throws(() => parseJenkinsCustomParameters('{"automation_execution_id":"spoof"}'), /保留参数/);
  assert.throws(() => parseJenkinsCustomParameters('{"path":"/tmp/attacker-bin"}'), /保留参数/);
  assert.throws(() => parseJenkinsCustomParameters('{"SUITE":"a","suite":"b"}'), /大小写/);
});

test('rejects invalid names, command separators, non-string values, and oversized input', () => {
  assert.throws(() => parseJenkinsCustomParameters('{"bad-name":"value"}'), /格式不合法/);
  assert.throws(() => parseJenkinsCustomParameters('{"SUITE":"smoke;echo bad"}'), /命令分隔符/);
  assert.throws(() => parseJenkinsCustomParameters('{"SUITE":3}'), /必须是字符串/);
  assert.throws(() => parseJenkinsCustomParameters(JSON.stringify({ SUITE: 'x'.repeat(2001) })), /2000/);
  assert.throws(() => parseJenkinsCustomParameters(JSON.stringify(Object.fromEntries(
    Array.from({ length: 51 }, (_, index) => [`PARAM_${index}`, 'value']),
  ))), /50 项/);
});
