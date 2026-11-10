/**
 * Pure helpers used by the audio asset list and focused Node tests.
 * @param {string} value
 * @returns {Array<{name: string, url: string}>}
 */
export function parsePastedAudioRecords(value) {
  const lines = value.split(/\r?\n/).map((text, index) => ({ text: text.trim(), line: index + 1 })).filter((item) => item.text);
  const records = [];
  let pendingName = null;

  for (const item of lines) {
    if (/^https?:\/\//i.test(item.text)) {
      if (!pendingName) throw new Error('第 ' + item.line + ' 行发现 URL 前没有音频名称');
      try { new URL(item.text); } catch { throw new Error('第 ' + item.line + ' 行音频 URL 格式无效'); }
      records.push({ name: pendingName.name, url: item.text });
      pendingName = null;
      if (records.length > 200) throw new Error('批量导入最多支持 200 条音频');
      continue;
    }

    if (pendingName) throw new Error('第 ' + item.line + ' 行名称前一条“' + pendingName.name + '”缺少 URL');
    const name = item.text.replace(/[:：]\s*$/, '').trim();
    if (!name) throw new Error('第 ' + item.line + ' 行音频名称不能为空');
    pendingName = { name, line: item.line };
  }

  if (pendingName) throw new Error('第 ' + pendingName.line + ' 行“' + pendingName.name + '”后缺少音频 URL');
  if (records.length === 0) throw new Error('没有识别到音频记录，请粘贴名称和 URL');
  return records;
}

/**
 * @param {number | null} seconds
 * @returns {string}
 */
export function formatAudioDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '未解析';
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = whole % 60;
  return hours > 0
    ? [hours, minutes, remainder].map((item) => String(item).padStart(2, '0')).join(':')
    : [minutes, remainder].map((item) => String(item).padStart(2, '0')).join(':');
}

/**
 * Don't infer absence while the request is still loading or has failed.
 * @param {object | null | undefined} answer
 * @param {number} contentVersion
 * @param {'pending' | 'error' | 'success'} queryStatus
 * @returns {'loading' | 'error' | 'unbound' | 'current' | 'mismatch'}
 */
export function groundTruthUiState(answer, contentVersion, queryStatus) {
  if (queryStatus === 'pending') return 'loading';
  if (queryStatus === 'error') return 'error';
  if (!answer) return 'unbound';
  return answer.audio_content_version === contentVersion ? 'current' : 'mismatch';
}

/**
 * @param {object | null | undefined} recentRun
 * @param {'pending' | 'error' | 'success'} queryStatus
 * @param {boolean} hasData
 * @returns {'loading' | 'error' | 'unassessed' | 'assessed'}
 */
export function recentRunUiState(recentRun, queryStatus, hasData) {
  if (queryStatus === 'pending' && !hasData) return 'loading';
  if (queryStatus === 'error' && !hasData) return 'error';
  return recentRun ? 'assessed' : 'unassessed';
}

