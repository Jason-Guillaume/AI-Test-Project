// 缺陷批量创建纯逻辑单元测试：多行与结构化文本解析、默认值填充、整批校验及行号错误提取。
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyDefaultsToRows,
  createDraftRow,
  extractServerRowErrors,
  isPristineEmptyRow,
  parseBatchDefectLines,
  validateBatchDefectRows,
} from '../src/features/defects/batchCreateUtils.mjs';

test('纯标题多行文本与分隔符多字段文本均能正确解析', () => {
  const defaults = {
    category: '后端',
    severity: 2,
    status: '待确认',
    environment: 'test',
    assignee_id: 12,
  };
  const input = [
    '登录接口 500 超时',
    '  ',
    '按钮样式错位 | 前端 | 严重 | 提交按钮超出卡片 | 1. 打开弹窗\\n2. 查看底部 | staging',
    '表格翻页未重置\tFE\t3\t切换筛选后停在第二页',
    '联调鉴权超时 | 前后端 | 3 | 令牌过期跳转异常',
  ].join('\n');

  const rows = parseBatchDefectLines(input, defaults, (i) => `k-${i}`);
  assert.equal(rows.length, 4);

  assert.equal(rows[0].title, '登录接口 500 超时');
  assert.equal(rows[0].category, '后端');
  assert.equal(rows[0].severity, 2);
  assert.equal(rows[0].environment, 'test');
  assert.equal(rows[0].assignee_id, 12);

  assert.equal(rows[1].title, '按钮样式错位');
  assert.equal(rows[1].category, '前端');
  assert.equal(rows[1].severity, 4);
  assert.equal(rows[1].description, '提交按钮超出卡片');
  assert.equal(rows[1].steps_to_reproduce, '1. 打开弹窗\n2. 查看底部');
  assert.equal(rows[1].environment, 'staging');

  assert.equal(rows[2].title, '表格翻页未重置');
  assert.equal(rows[2].category, '前端');
  assert.equal(rows[2].severity, 3);
  assert.equal(rows[2].description, '切换筛选后停在第二页');
  assert.equal(rows[2].environment, 'test');

  assert.equal(rows[3].title, '联调鉴权超时');
  assert.equal(rows[3].category, '前后端');
  assert.equal(rows[3].severity, 3);
  assert.equal(rows[3].description, '令牌过期跳转异常');
  assert.equal(rows[3].environment, 'test');
});

test('默认配置支持仅填充空字段与覆盖全部行两种模式', () => {
  const rowA = {
    ...createDraftRow({ severity: 2, status: '待确认' }, 'a'),
    title: 'A',
    category: '前端',
    environment: 'dev',
    assignee_id: 5,
  };
  const rowB = {
    ...createDraftRow({ severity: 2, status: '待确认' }, 'b'),
    title: 'B',
  };
  const defaults = {
    category: '后端',
    severity: 3,
    status: '处理中',
    environment: 'prod',
    assignee_id: 9,
  };

  const filled = applyDefaultsToRows([rowA, rowB], defaults, 'fillEmpty');
  assert.equal(filled[0].category, '前端');
  assert.equal(filled[0].environment, 'dev');
  assert.equal(filled[0].assignee_id, 5);
  assert.equal(filled[1].category, '后端');
  assert.equal(filled[1].environment, 'prod');
  assert.equal(filled[1].assignee_id, 9);

  const overwritten = applyDefaultsToRows([rowA, rowB], defaults, 'overwrite');
  assert.equal(overwritten[0].category, '后端');
  assert.equal(overwritten[0].severity, 3);
  assert.equal(overwritten[0].status, '处理中');
  assert.equal(overwritten[0].environment, 'prod');
  assert.equal(overwritten[0].assignee_id, 9);
  assert.equal(overwritten[0].title, 'A');
});

test('整批校验准确标出缺失标题与前后端划分的行号', () => {
  const result = validateBatchDefectRows([
    {
      ...createDraftRow({ category: '前端', severity: 3, status: '待确认' }, 'r1'),
      title: '  合法缺陷  ',
      description: '  说明  ',
      environment: ' test ',
    },
    {
      ...createDraftRow({ severity: 2, status: '待确认' }, 'r2'),
      title: '   ',
    },
  ]);

  assert.equal(result.valid, false);
  assert.deepEqual(result.errors, [
    { row: 2, field: 'title', message: '缺陷标题不能为空' },
    { row: 2, field: 'category', message: '请选择前后端划分（前端、后端或前后端）' },
  ]);

  const validOnly = validateBatchDefectRows([
    {
      ...createDraftRow({ category: '前端', severity: 3, status: '待确认' }, 'r1'),
      title: '  合法缺陷  ',
      description: '  说明  ',
      environment: ' test ',
    },
    {
      ...createDraftRow({ category: '前后端', severity: 2, status: '待确认' }, 'r2'),
      title: '前后端联调缺陷',
    },
  ]);
  assert.equal(validOnly.valid, true);
  assert.equal(validOnly.items[0].title, '合法缺陷');
  assert.equal(validOnly.items[0].category, '前端');
  assert.equal(validOnly.items[0].description, '说明');
  assert.equal(validOnly.items[0].environment, 'test');
  assert.equal(validOnly.items[1].category, '前后端');
});

test('空白行检测与服务端行级错误提取安全过滤畸形结构', () => {
  const empty = createDraftRow({ category: '前端', severity: 2, status: '待确认' }, 'e');
  assert.equal(isPristineEmptyRow(empty), true);
  assert.equal(isPristineEmptyRow({ ...empty, title: '非空' }), false);

  const extracted = extractServerRowErrors({
    meta: {
      errors: [
        { row: 2, field: 'assignee_id', message: '处理人必须是该项目成员' },
        { row: 'bad', message: 'ignore' },
        null,
      ],
    },
  });
  assert.deepEqual(extracted, [
    { row: 2, field: 'assignee_id', message: '处理人必须是该项目成员' },
  ]);
  assert.deepEqual(extractServerRowErrors(null), []);
});
