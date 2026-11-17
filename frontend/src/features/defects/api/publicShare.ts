// 免登录缺陷分享客户端。
// 不走平台 axios 实例，避免公开接口的 401/403 触发登录跳转。
// 凭证只放在 Authorization 头，不写入 URL、日志或本地存储。
import axios from 'axios';

const publicClient = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: false,
});

export interface PublicDefectContent {
  bug_no?: string | null;
  title?: string | null;
  severity_label?: string | null;
  status?: string | null;
  project_name?: string | null;
  description?: string | null;
  steps_to_reproduce?: string | null;
  environment?: string | null;
  expected_result?: string | null;
  actual_result?: string | null;
  created_at?: string | null;
  reporter_name?: string | null;
  assignee_name?: string | null;
  sources?: Array<Record<string, unknown>>;
  agent_executions?: unknown[];
  allure?: string | null;
}

export interface PublicResolution {
  repair_description: string;
  fix_version: string | null;
  commit_sha: string | null;
  actor_display_name: string | null;
  actor_type: string;
  old_status: string;
  new_status: string;
  submitted_at: string;
  identity_note: string;
}

export interface PublicDefect {
  share_state: 'active';
  live_status: string;
  allow_resolve: boolean;
  can_submit: boolean;
  expires_at: string | null;
  content: PublicDefectContent;
  resolution: PublicResolution | null;
  identity_note: string;
}

export interface PublicResolveResult {
  live_status: string;
  idempotent: boolean;
  message: string;
  repair_description: string | null;
  submitted_at: string | null;
  actor_display_name: string | null;
}

function authHeader(token: string) {
  return { headers: { Authorization: `Bearer ${token}` } };
}

/**
 * 公开缺陷接口。调用方必须传入内存中的凭证，不能把凭证拼进请求路径。
 */
export const publicDefectApi = {
  /** 读取授权后的缺陷详情。 */
  get: async (shareId: string, token: string) => {
    const response = await publicClient.get<PublicDefect>(`/public/defect-shares/${encodeURIComponent(shareId)}`, authHeader(token));
    return response.data;
  },
  /** 记录一次访问。失败不影响阅读。 */
  recordView: async (shareId: string, token: string) => {
    await publicClient.post(`/public/defect-shares/${encodeURIComponent(shareId)}/views`, null, authHeader(token));
  },
  /** 提交已解决。 */
  resolve: async (shareId: string, token: string, body: { repair_description: string; fix_version?: string; commit_sha?: string; reporter_name?: string }) => {
    const response = await publicClient.post<PublicResolveResult>(
      `/public/defect-shares/${encodeURIComponent(shareId)}/resolve`,
      body,
      authHeader(token),
    );
    return response.data;
  },
};
