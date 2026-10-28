// 登录跳转路径安全回归测试：编译源码工具函数后用 Node 内置测试运行器覆盖外链与编码绕过。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/utils/safeRedirect.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { safeInternalPath } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('only accepts safe same-site paths', /** 校验登录跳转不会导航到站外或畸形 URL。 */ () => {
  assert.equal(safeInternalPath('/console/tasks?tab=active'), '/console/tasks?tab=active');
  assert.equal(safeInternalPath('//attacker.example/path'), '/console');
  assert.equal(safeInternalPath('/\\attacker.example/path'), '/console');
  assert.equal(safeInternalPath('https://attacker.example'), '/console');
  assert.equal(safeInternalPath('/console\u0000'), '/console');
});
