// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { Environment } from '@/features/environments/contracts';

// Web UI 自动化：既有测试执行的扩展视图，字段与后端结构化契约一致。
export type WebOperation = 'NAVIGATE' | 'CLICK' | 'FILL' | 'SELECT' | 'UPLOAD' | 'WAIT' | 'ASSERT';

export interface WebLocator {
  strategy: 'TEST_ID' | 'ROLE' | 'LABEL' | 'TEXT' | 'CSS' | 'XPATH'; // 定位策略
  value: string; // 定位值
  name?: string | null; // Role 可访问名称
  exact?: boolean; // 精确匹配
}

export interface WebStep {
  name: string; // 步骤名称
  operation: WebOperation; // 白名单操作
  locator?: WebLocator | null; // 直接定位器
  page_object_id?: number | null; // 页面对象引用
  element_key?: string | null; // 命名元素
  value?: string | null; // 输入或导航值，可引用变量
  timeout_ms?: number | null; // 步骤超时
  wait_state?: 'visible' | 'hidden' | 'attached' | 'detached'; // 等待状态
  assertion?: 'TEXT' | 'VALUE' | 'VISIBLE' | 'COUNT' | 'URL' | 'TITLE'; // 断言来源
  operator?: 'EQ' | 'NE' | 'CONTAINS' | 'GT' | 'GE' | 'LT' | 'LE'; // 平台断言操作符
  expected?: string | null; // 断言期望值
  sensitive?: boolean; // 输入或元素敏感
  upload?: { name: string; mime_type?: string; content_base64: string } | null; // 内存上传，禁止服务器路径
  output_variable?: string | null; // 断言值输出到业务上下文
}

export interface WebCaseInput {
  name: string; // 用例名称
  description?: string; // 描述
  auth_profile_id?: number | null; // 加密凭据配置
  timeout_ms?: number; // 默认操作超时
  total_timeout_ms?: number; // 用例总超时
  revision?: number | null; // 乐观锁
  steps: WebStep[]; // 顺序即执行顺序
}

export interface WebCase extends WebCaseInput {
  id: number; // 既有 TestCase ID
  project_id: number; // 项目 ID
  revision: number; // 当前版本
  source_type: string; // 人工或 Agent
  confirmed: boolean; // 当前依赖指纹已人工确认
}

export interface WebPageInput {
  name: string; // 页面名
  path: string; // 环境相对路径
  elements: { key: string; locator: WebLocator }[]; // 命名元素
  revision?: number | null; // 乐观锁
}

export interface WebPage extends WebPageInput {
  id: number; // 页面 ID
  project_id: number; // 项目 ID
  revision: number; // 当前版本
}

export interface WebAuthProfile {
  id: number; // 配置 ID
  project_id: number; // 项目 ID
  environment_id: number; // 环境 ID
  name: string; // 配置名称
  configured: boolean; // 仅表示已配置，敏感值永不回传
  expires_at: string; // UTC 过期时间
}

export interface WebArtifact {
  id: string; // 不透明附件 ID
  kind: string; // 截图或 Trace
  url: string; // 受 JWT 保护的下载地址
}

export interface WebExecution {
  id: number; // CaseExecution ID
  test_run_id: number; // TestRun ID
  test_case_id: number | null; // 用例 ID
  status: string; // 既有执行状态
  duration_ms: number | null; // 耗时
  error_code: string | null; // 失败错误码
  error_message: string | null; // 中文错误定位
  started_at: string | null; // 执行时间
  response_snapshot: { web?: { steps?: Record<string, unknown>[]; artifacts?: WebArtifact[] } } | null; // 脱敏步骤及附件
  report_id: number | null; // 已生成报告
}

// 单轮决策结论

// Web 调试环境候选只展示元信息，不暴露管理端请求头与凭据。
export type WebEnvironment = Pick<Environment, 'id' | 'name' | 'display_name' | 'is_active'>;
