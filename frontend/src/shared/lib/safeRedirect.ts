// 登录后站内跳转校验：由登录页和路由守卫共用，阻止恶意 redirect 参数离开本站。

/** 验证登录后的回跳路径，只允许安全站内路径，非法输入统一回到工作台。
 *
 * 调用时机：登录页消费 query.redirect，或路由守卫记录当前页路径时。
 * @param candidate 用户提供或由当前路由生成的待跳转路径
 * @returns 以单个斜杠开头且不含反斜杠和控制字符的站内路径；无效时返回 /console
 */
export function safeInternalPath(candidate: string | null | undefined): string {
  if (
    !candidate ||
    !candidate.startsWith('/') ||
    candidate.startsWith('//') ||
    candidate.includes('\\') ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return '/console';
  }
  return candidate;
}
