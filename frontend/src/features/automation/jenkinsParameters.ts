const RESERVED_PARAMETERS = new Set([
  'AUTOMATION_EXECUTION_ID', 'AUTOMATION_PROJECT_ID', 'AUTOMATION_CALLBACK_KEY',
  'AUTOMATION_CALLBACK_URL', 'AUTOMATION_HISTORY_URL', 'AUTOMATION_PROVIDER',
  'REPOSITORY_URL', 'REPOSITORY_ID', 'BRANCH_NAME', 'TEST_ENV', 'PYTEST_ARGS',
  'TEST_TAGS', 'TEST_SCOPE', 'BUILD_TIMEOUT_MINUTES',
  'AUTOMATION_STATUS', 'JENKINS_RESULT', 'AUTOMATION_START_MS', 'AUTOMATION_CALLBACK_SECRET',
  'AUTOMATION_CALLBACK_ORIGIN', 'REPOSITORY_CREDENTIALS_ID', 'CALLBACK_CREDENTIALS_ID',
  'BUILD_NUMBER', 'BUILD_URL', 'JOB_NAME', 'JENKINS_URL', 'WORKSPACE', 'NODE_NAME',
  'EXECUTOR_NUMBER', 'PATH', 'HOME', 'SHELL', 'JAVA_HOME',
]);
const PARAMETER_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const DANGEROUS_VALUE = /[\x00-\x1f\x7f;&|$`<>\\]/;
const MAX_CUSTOM_PARAMETERS = 50;

export function parseJenkinsCustomParameters(raw: string): Record<string, string> {
  let value: unknown;
  try {
    value = JSON.parse(raw || '{}');
  } catch {
    throw new Error('自定义参数必须是有效的 JSON 对象');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('自定义参数必须是 JSON 对象');
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > MAX_CUSTOM_PARAMETERS) throw new Error(`自定义参数不能超过 ${MAX_CUSTOM_PARAMETERS} 项`);
  const names = new Set<string>();
  const result: Record<string, string> = {};
  for (const [name, rawValue] of entries) {
    if (!PARAMETER_NAME.test(name)) throw new Error(`参数名 ${name} 格式不合法`);
    const normalized = name.toUpperCase();
    if (names.has(normalized)) throw new Error('参数名称不能仅大小写不同');
    names.add(normalized);
    if (RESERVED_PARAMETERS.has(normalized)) throw new Error(`参数名 ${name} 是平台保留参数`);
    if (typeof rawValue !== 'string') throw new Error(`参数 ${name} 的值必须是字符串`);
    if (rawValue.length > 2000) throw new Error(`参数 ${name} 超过 2000 个字符`);
    if (DANGEROUS_VALUE.test(rawValue)) throw new Error(`参数 ${name} 含控制字符或命令分隔符`);
    result[name] = rawValue;
  }
  return result;
}
