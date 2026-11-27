import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/shared/lib/sequence.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { sequenceColumn, sequenceNumber } = await import(
  `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
);

test('分页序号按页码与每页条数连续递增', () => {
  assert.equal(sequenceNumber(0, 1, 10), 1);
  assert.equal(sequenceNumber(9, 1, 10), 10);
  assert.equal(sequenceNumber(0, 2, 10), 11);
  assert.equal(sequenceNumber(4, 3, 20), 45);
});

test('非法页码与每页条数回退到第一页和默认值', () => {
  assert.equal(sequenceNumber(0, 0, 0), 1);
  assert.equal(sequenceNumber(2, Number.NaN, Number.NaN), 3);
  assert.equal(sequenceNumber(0, -3, 10), 1);
  assert.equal(sequenceNumber(1, 1.8, 10.7), 2);
});

test('提供 rows 时按筛选排序后的完整位置编号，并保留列配置', () => {
  const rows = [{ id: 7 }, { id: 3 }, { id: 9 }];
  const column = sequenceColumn({ rows, width: 60, title: '行号' });
  assert.equal(column.title, '行号');
  assert.equal(column.width, 60);
  assert.equal(column.render(undefined, rows[0], 0), 1);
  assert.equal(column.render(undefined, rows[1], 1), 2);
  assert.equal(column.render(undefined, rows[2], 2), 3);
});

test('rows 中找不到记录时退回当前页内索引，未提供 rows 时使用分页编号', () => {
  const rows = [{ id: 1 }];
  const column = sequenceColumn({ rows });
  assert.equal(column.render(undefined, { id: 99 }, 3), 4);

  const paged = sequenceColumn({ page: 2, pageSize: 5 });
  assert.equal(paged.render(undefined, { id: 1 }, 0), 6);
  assert.equal(paged.title, '序号');
  assert.equal(paged.align, 'center');
});