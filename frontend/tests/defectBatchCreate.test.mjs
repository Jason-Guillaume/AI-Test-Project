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
    category: '接口',
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
    '订单查询接口返回字段缺失 | api | 3 | 响应体缺少 orderNo 字段',
    '网关响应超时 | 后端 | 高 | Nginx 上游 504',
  ].join('\n');

  const rows = parseBatchDefectLines(input, defaults, (i) => `k-${i}`);
  assert.equal(rows.length, 6);

  assert.equal(rows[0].title, '登录接口 500 超时');
  assert.equal(rows[0].category, '接口');
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

  assert.equal(rows[4].title, '订单查询接口返回字段缺失');
  assert.equal(rows[4].category, '接口');
  assert.equal(rows[4].severity, 3);
  assert.equal(rows[4].description, '响应体缺少 orderNo 字段');
  assert.equal(rows[4].environment, 'test');

  // 旧「后端」录入自动归并为「接口」
  assert.equal(rows[5].title, '网关响应超时');
  assert.equal(rows[5].category, '接口');
  assert.equal(rows[5].severity, 3);
  assert.equal(rows[5].description, 'Nginx 上游 504');
  assert.equal(rows[5].environment, 'test');
});

test('粘贴兼容原六列并解析新增预期与实际结果两列', () => {
  const defaults = { category: '接口', severity: 2, status: '待确认', environment: '' };
  const rows = parseBatchDefectLines(
    '旧格式 | 前端 | 2 | 描述 | 步骤 | test\n新格式 | 接口 | 3 | 描述 | 步骤 | prod | 预期\\n第二行 | 实际返回',
    defaults,
    (index) => `row-${index}`,
  );
  assert.equal(rows[0].expected_result, '');
  assert.equal(rows[0].actual_result, '');
  assert.equal(rows[1].expected_result, '预期\n第二行');
  assert.equal(rows[1].actual_result, '实际返回');
  const result = validateBatchDefectRows(rows);
  assert.equal(result.valid, true);
  assert.equal(result.items[1].expected_result, '预期\n第二行');
  assert.equal(result.items[1].actual_result, '实际返回');
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
    category: '接口',
    severity: 3,
    status: '处理中',
    environment: 'prod',
    assignee_id: 9,
  };

  const filled = applyDefaultsToRows([rowA, rowB], defaults, 'fillEmpty');
  assert.equal(filled[0].category, '前端');
  assert.equal(filled[0].environment, 'dev');
  assert.equal(filled[0].assignee_id, 5);
  assert.equal(filled[1].category, '接口');
  assert.equal(filled[1].environment, 'prod');
  assert.equal(filled[1].assignee_id, 9);

  const overwritten = applyDefaultsToRows([rowA, rowB], defaults, 'overwrite');
  assert.equal(overwritten[0].category, '接口');
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
    { row: 2, field: 'category', message: '请选择前后端划分（前端、前后端或接口）' },
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
    {
      ...createDraftRow({ severity: 2, status: '待确认' }, 'r3'),
      title: '接口返回结构变更缺陷',
      category: '接口',
    },
  ]);
  assert.equal(validOnly.valid, true);
  assert.equal(validOnly.items[0].title, '合法缺陷');
  assert.equal(validOnly.items[0].category, '前端');
  assert.equal(validOnly.items[0].description, '说明');
  assert.equal(validOnly.items[0].environment, 'test');
  assert.equal(validOnly.items[1].category, '前后端');
  assert.equal(validOnly.items[2].category, '接口');
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
