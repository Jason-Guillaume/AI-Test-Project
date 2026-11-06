/** Fetch every result page for one playback window with bounded concurrency. */
export async function fetchCompletePlaybackWindow(fetchPage, signal, concurrency = 3) {
  if (signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
  const first = await fetchPage(1, signal);
  if (!Number.isInteger(first.total) || !Number.isInteger(first.page_size) || first.page_size <= 0) {
    throw new Error('播放片段分页信息无效');
  }
  if (first.total > 100_000) throw new Error('播放窗口超过单次定位安全上限');
  const pageCount = Math.ceil(first.total / first.page_size);
  if (pageCount <= 1) return first;
  const pages = new Array(pageCount);
  pages[0] = first.items;
  let nextPage = 2;
  const worker = async () => {
    while (true) {
      if (signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
      const pageNumber = nextPage++;
      if (pageNumber > pageCount) return;
      const result = await fetchPage(pageNumber, signal);
      if (result.total !== first.total || result.page_size !== first.page_size) {
        throw new Error('播放期间片段数量发生变化，请重新定位');
      }
      pages[pageNumber - 1] = result.items;
    }
  };
  await Promise.all(Array.from({ length: Math.min(Math.max(1, concurrency), pageCount - 1) }, worker));
  if (signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
  const items = new Array(first.total);
  let offset = 0;
  for (const page of pages) {
    for (const item of page) items[offset++] = item;
  }
  items.length = offset;
  return { ...first, items };
}
