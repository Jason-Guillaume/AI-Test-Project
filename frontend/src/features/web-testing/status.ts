// Web 执行步骤的状态语义；未执行步骤不映射为跳过。

/**
 * Web 用例执行记录里的步骤状态色。
 *
 * 后端只写 PASSED / FAILED / ERROR 三种（playwright_executor 在首个失败步骤即 break），
 * 未出现在日志里的步骤表示「未执行」，不是 SKIPPED——不要映射成跳过色，
 * 否则会把超时中断伪装成主动跳过。
 */
export const WEB_STEP_STATUS_COLOR: Record<string, string> = {
  PASSED: 'green',
  FAILED: 'red',
  ERROR: 'warning',
};

/** Web 步骤状态中文标签。 */
export const WEB_STEP_STATUS_LABEL: Record<string, string> = {
  PASSED: '通过',
  FAILED: '失败',
  ERROR: '错误',
};
