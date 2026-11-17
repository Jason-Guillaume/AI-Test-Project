// 公开缺陷分享凭证内存生命周期与防泄漏单元测试。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/features/defects/api/shareToken.ts', import.meta.url), 'utf8');
const transpiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const {
  captureShareToken,
  forgetShareToken,
  resetShareTokenMemoryForTests,
} = await import(`data:text/javascript;base64,${Buffer.from(transpiled).toString('base64')}`);

function createEnv(initialUrl) {
  const url = new URL(initialUrl, 'https://platform.example.com');
  const replaceCalls = [];
  const stateObj = { idx: 2, key: 'k1' };
  return {
    replaceCalls,
    location: {
      get hash() {
        return url.hash;
      },
      get pathname() {
        return url.pathname;
      },
      get search() {
        return url.search;
      },
    },
    history: {
      state: stateObj,
      replaceState(data, unused, nextUrl) {
        replaceCalls.push({ data, unused, nextUrl });
        if (nextUrl !== undefined) {
          const parsed = new URL(nextUrl, 'https://platform.example.com');
          url.pathname = parsed.pathname;
          url.search = parsed.search;
          url.hash = parsed.hash;
        }
      },
    },
  };
}

test('captures token once, scrubs fragment immediately, and survives StrictMode remounts', () => {
  resetShareTokenMemoryForTests();
  const env = createEnv('/public/defects/share/share-1?from=feishu#token=secret_tok_123');

  const first = captureShareToken('share-1', env);
  assert.deepEqual(first, { status: 'present', token: 'secret_tok_123' });
  assert.equal(env.location.hash, '');
  assert.equal(env.replaceCalls.length, 1);
  assert.equal(env.replaceCalls[0].nextUrl, '/public/defects/share/share-1?from=feishu');
  assert.deepEqual(env.replaceCalls[0].data, { idx: 2, key: 'k1' });

  // Simulate React 18 StrictMode double initializer call and component remount.
  const second = captureShareToken('share-1', env);
  const remount = captureShareToken('share-1', env);
  assert.deepEqual(second, { status: 'present', token: 'secret_tok_123' });
  assert.deepEqual(remount, { status: 'present', token: 'secret_tok_123' });
  assert.equal(env.replaceCalls.length, 1);
});

test('missing token after full page reload reports missing instead of leaking old token', () => {
  resetShareTokenMemoryForTests();
  const env = createEnv('/public/defects/share/share-2#token=tok_before_refresh');
  assert.deepEqual(captureShareToken('share-2', env), { status: 'present', token: 'tok_before_refresh' });
  assert.equal(env.location.hash, '');

  // Full page reload drops JS module memory while scrubbed URL has no fragment.
  resetShareTokenMemoryForTests();
  assert.deepEqual(captureShareToken('share-2', env), { status: 'missing' });
});

test('reissued link updates token in same tab and forgetShareToken invalidates rejected token', () => {
  resetShareTokenMemoryForTests();
  const initialEnv = createEnv('/public/defects/share/share-3#token=old_tok');
  assert.deepEqual(captureShareToken('share-3', initialEnv), { status: 'present', token: 'old_tok' });

  const reissuedEnv = createEnv('/public/defects/share/share-3#token=new_tok');
  assert.deepEqual(captureShareToken('share-3', reissuedEnv), { status: 'present', token: 'new_tok' });
  assert.equal(reissuedEnv.location.hash, '');

  forgetShareToken('share-3');
  assert.deepEqual(captureShareToken('share-3', reissuedEnv), { status: 'missing' });
});

test('rejects invalid or oversized fragment tokens while still scrubbing address bar', () => {
  resetShareTokenMemoryForTests();
  const spaced = createEnv('/public/defects/share/share-4#token=bad%20token');
  assert.deepEqual(captureShareToken('share-4', spaced), { status: 'missing' });
  assert.equal(spaced.location.hash, '');

  const oversized = createEnv(`/public/defects/share/share-4#token=${'a'.repeat(201)}`);
  assert.deepEqual(captureShareToken('share-4', oversized), { status: 'missing' });
  assert.equal(oversized.location.hash, '');
});

function stripComments(code) {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
}

test('public share implementation avoids persistent storage, cookies, URL query tokens, and console logging', async () => {
  const [pageSource, clientSource] = await Promise.all([
    readFile(new URL('../src/pages/public/DefectShare/index.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/features/defects/api/publicShare.ts', import.meta.url), 'utf8'),
  ]);

  for (const content of [source, pageSource, clientSource].map(stripComments)) {
    assert.doesNotMatch(content, /\blocalStorage\b/);
    assert.doesNotMatch(content, /\bsessionStorage\b/);
    assert.doesNotMatch(content, /\bdocument\.cookie\b/);
    assert.doesNotMatch(content, /\bconsole\.(log|info|warn|error|debug)\b/);
  }
  assert.doesNotMatch(stripComments(clientSource), /\breadShareToken\b/);
  assert.match(stripComments(clientSource), /withCredentials:\s*false/);
  assert.match(stripComments(pageSource), /\bcaptureShareToken\b/);
  assert.match(stripComments(pageSource), /\bforgetShareToken\b/);
});
