// 缺陷批量创建弹窗的纯函数逻辑：多行文本解析、预设默认值应用、整批校验与错误映射。
// 本文件不依赖 React 或浏览器 DOM，供 UI 组件与 node --test 单测共用。

export const MAX_BATCH_BUG_ROWS = 100;

const VALID_CATEGORIES = new Set(['前端', '前后端', '接口']);

// 「后端」与「接口」为同一归属：录入后端时自动归并为接口提交。
const CATEGORY_ALIASES = {
  前端: '前端',
  frontend: '前端',
  fe: '前端',
  web: '前端',
  后端: '接口',
  backend: '接口',
  be: '接口',
  server: '接口',
  接口: '接口',
  api: '接口',
  interface: '接口',
  前后端: '前后端',
  both: '前后端',
  fullstack: '前后端',
  'full-stack': '前后端',
  'fe+be': '前后端',
  'be+fe': '前后端',
  '前端+后端': '前后端',
};

const SEVERITY_ALIASES = {
  '1': 1,
  低: 1,
  '1 低': 1,
  '2': 2,
  中: 2,
  '2 中': 2,
  '3': 3,
  高: 3,
  '3 高': 3,
  '4': 4,
  严重: 4,
  '4 严重': 4,
};

/** 规范化前后端划分输入，非法值返回 undefined。 */
export function normalizeCategoryToken(raw) {
  if (typeof raw !== 'string') return undefined;
  const key = raw.trim().toLowerCase();
  return CATEGORY_ALIASES[key] ?? CATEGORY_ALIASES[raw.trim()];
}

/** 规范化严重度输入（1-4 或中文标签），非法值返回 undefined。 */
export function normalizeSeverityToken(raw) {
  if (typeof raw === 'number' && [1, 2, 3, 4].includes(raw)) return raw;
  if (typeof raw !== 'string') return undefined;
  return SEVERITY_ALIASES[raw.trim()];
}

/** 构造一条带默认值的新草稿行。 */
export function createDraftRow(defaults, key) {
  return {
    key,
    title: '',
    category: defaults?.category,
    severity: defaults?.severity ?? 2,
    status: defaults?.status ?? '待确认',
    description: '',
    steps_to_reproduce: '',
    environment: defaults?.environment ?? '',
    assignee_id: defaults?.assignee_id ?? null,
  };
}

/** 判断某一行是否尚未填写任何实质内容（用于快捷拆分时替换初始空白行）。 */
export function isPristineEmptyRow(row) {
  if (!row) return false;
  return (
    !(row.title ?? '').trim() &&
    !(row.description ?? '').trim() &&
    !(row.steps_to_reproduce ?? '').trim()
  );
}

/**
 * 将粘贴的多行文本拆分为结构化缺陷行。
 *
 * 支持两种格式：
 * 1. 纯文本每行一个标题，其余字段继承顶部默认值；
 * 2. 使用「|」或制表符分隔的列：`标题 | 前端/前后端/接口 | 严重度 | 描述 | 复现步骤 | 环境`。
 */
export function parseBatchDefectLines(rawText, defaults, createKey) {
  const lines = String(rawText ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  return lines.map((line, index) => {
    const key = createKey ? createKey(index) : `parsed-${index}-${Date.now()}`;
    const hasTab = line.includes('\t');
    const hasPipe = line.includes('|');
    if (!hasTab && !hasPipe) {
      return {
        ...createDraftRow(defaults, key),
        title: line.slice(0, 200),
      };
    }
    const delimiter = hasTab ? '\t' : '|';
    const cells = line.split(delimiter).map((part) => part.trim());
    const parsedCategory = normalizeCategoryToken(cells[1]);
    const parsedSeverity = normalizeSeverityToken(cells[2]);
    const rawSteps = (cells[4] ?? '').replace(/\\n/g, '\n');
    const rawEnv = cells[5] ?? '';

    return {
      ...createDraftRow(defaults, key),
      title: (cells[0] ?? '').slice(0, 200),
      category: parsedCategory ?? defaults?.category,
      severity: parsedSeverity ?? defaults?.severity ?? 2,
      description: (cells[3] ?? '').slice(0, 1000),
      steps_to_reproduce: rawSteps,
      environment: (rawEnv || defaults?.environment || '').slice(0, 200),
    };
  });
}

/**
 * 将顶部默认配置批量应用到当前表格行。
 * - overwrite: 覆盖全部行的归属/严重度/状态/环境/处理人；
 * - fillEmpty: 仅补齐尚未填写归属、环境或处理人的行。
 */
export function applyDefaultsToRows(rows, defaults, mode = 'overwrite') {
  return (rows ?? []).map((row) => {
    if (mode === 'fillEmpty') {
      return {
        ...row,
        category: row.category ?? defaults?.category,
        environment: (row.environment ?? '').trim() ? row.environment : (defaults?.environment ?? ''),
        assignee_id: row.assignee_id ?? defaults?.assignee_id ?? null,
      };
    }
    return {
      ...row,
      category: defaults?.category ?? row.category,
      severity: defaults?.severity ?? row.severity ?? 2,
      status: defaults?.status ?? row.status ?? '待确认',
      environment: defaults?.environment ?? '',
      assignee_id: defaults?.assignee_id ?? null,
    };
  });
}

/**
 * 校验全部草稿行并生成接口请求明细；返回行级错误（1-based）以便整批拦截。
 */
export function validateBatchDefectRows(rows) {
  const list = rows ?? [];
  const errors = [];

  if (list.length === 0) {
    errors.push({ row: 1, field: 'items', message: '请至少添加一条缺陷记录' });
    return { valid: false, errors, items: [] };
  }
  if (list.length > MAX_BATCH_BUG_ROWS) {
    errors.push({
      row: MAX_BATCH_BUG_ROWS + 1,
      field: 'items',
      message: `单次最多批量创建 ${MAX_BATCH_BUG_ROWS} 条缺陷`,
    });
  }

  const items = [];
  list.forEach((row, index) => {
    const rowNo = index + 1;
    const title = (row?.title ?? '').trim();
    const description = (row?.description ?? '').trim();
    const environment = (row?.environment ?? '').trim();
    const steps = (row?.steps_to_reproduce ?? '').trim();

    if (!title) {
      errors.push({ row: rowNo, field: 'title', message: '缺陷标题不能为空' });
    } else if (title.length > 200) {
      errors.push({ row: rowNo, field: 'title', message: '缺陷标题不能超过 200 字' });
    }

    if (!VALID_CATEGORIES.has(row?.category)) {
      errors.push({ row: rowNo, field: 'category', message: '请选择前后端划分（前端、前后端或接口）' });
    }

    if (description.length > 1000) {
      errors.push({ row: rowNo, field: 'description', message: '缺陷描述不能超过 1000 字' });
    }

    if (environment.length > 200) {
      errors.push({ row: rowNo, field: 'environment', message: '发现环境不能超过 200 字' });
    }

    items.push({
      title,
      category: row?.category,
      description: description || undefined,
      severity: row?.severity ?? 2,
      status: row?.status ?? '待确认',
      steps_to_reproduce: steps || undefined,
      environment: environment || undefined,
      assignee_id: row?.assignee_id ?? null,
    });
  });

  return {
    valid: errors.length === 0,
    errors,
    items,
  };
}

/** 安全提取服务端错误信封中的行级校验明细。 */
export function extractServerRowErrors(errorBody) {
  const rawList = errorBody?.meta?.errors;
  if (!Array.isArray(rawList)) return [];
  return rawList
    .filter(
      (item) =>
        item &&
        typeof item === 'object' &&
        Number.isInteger(item.row) &&
        typeof item.message === 'string',
    )
    .map((item) => ({
      row: item.row,
      field: typeof item.field === 'string' ? item.field : 'unknown',
      message: item.message,
    }));
}
