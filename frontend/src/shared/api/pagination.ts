// 批量选择器仍需合并多页数据，但限制读取规模，避免大项目触发无界串行请求。
const MAX_COLLECTED_ITEMS = 5000;
const MAX_COLLECTED_PAGES = 50;

/**
 * 有界收集分页接口，供必须构建本地树或选项列表的场景使用。
 * 超过行数或请求页数上限时显式失败，让页面显示错误态，避免静默截断。
 */
export async function collectPages<T>(
  fetchPage: (page: number) => Promise<{ items: T[]; total: number }>,
): Promise<{ items: T[]; total: number }> {
  const first = await fetchPage(1);
  if (first.total > MAX_COLLECTED_ITEMS || first.items.length > MAX_COLLECTED_ITEMS) {
    throw new Error(`数据超过批量加载上限（${MAX_COLLECTED_ITEMS} 条），请缩小筛选范围`);
  }
  const items = [...first.items];
  let total = first.total;
  for (let page = 2; items.length < total; page += 1) {
    if (page > MAX_COLLECTED_PAGES) {
      throw new Error(`数据超过批量加载上限（${MAX_COLLECTED_PAGES} 页），请缩小筛选范围`);
    }
    const next = await fetchPage(page);
    if (!next.items.length) throw new Error('分页数据不完整，请重试');
    items.push(...next.items);
    total = next.total;
    if (items.length > MAX_COLLECTED_ITEMS || total > MAX_COLLECTED_ITEMS) {
      throw new Error(`数据超过批量加载上限（${MAX_COLLECTED_ITEMS} 条），请缩小筛选范围`);
    }
  }
  return { ...first, items, total };
}

/**
 * 有界收集仅返回数组的旧版测试管理接口。
 * 到达上限仍有满页数据时按不完整处理，避免把截断数组伪装成完整结果。
 */
export async function collectArrayPages<T>(
  fetchPage: (page: number) => Promise<T[]>,
  pageSize: number,
): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; page <= MAX_COLLECTED_PAGES; page += 1) {
    const next = await fetchPage(page);
    items.push(...next);
    if (next.length < pageSize) return items;
    if (items.length >= MAX_COLLECTED_ITEMS) {
      throw new Error(`数据已达到批量加载上限（${MAX_COLLECTED_ITEMS} 条），无法确认结果完整性`);
    }
  }
  throw new Error(`数据超过批量加载上限（${MAX_COLLECTED_PAGES} 页），请缩小筛选范围`);
}
