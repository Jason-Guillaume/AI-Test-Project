// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。

/** 登录表单输入，对应 POST /session/login。 */
export interface LoginInput {
  username: string; // 登录名
  password: string; // 密码，明文提交，前端不做任何编码
}

/** 注册表单输入，对应 POST /session/register。 */
export interface RegisterInput {
  username: string; // 新账号的登录名
  password: string; // 新账号密码
}

/** 修改密码的输入，对应 PATCH /me。 */
export interface PasswordChangeInput {
  old_password: string; // 原密码，用于校验当前身份
  new_password: string; // 新密码
}


// 与后端 /api/v1 契约对齐的共享类型定义。
// 后端响应统一信封：列表 { items, total, page, page_size }，错误 { code, message, request_id }。
// 本文件是前端侧契约的事实来源：后端新增或改名字段时必须同步这里的字段与注释。

// 平台级角色（登录后可在顶栏切换/展示的身份）。三个成员含义：
//   admin —— 平台管理员，全站最高权限，可管理用户、模型配置等全局资源；
//   test  —— 测试工程师，常规业务身份，主要在组织与项目内执行测试；
//   dev   —— 开发工程师，以开发视角查看与配置资源。
export type PlatformRole = 'admin' | 'test' | 'dev';

// 平台用户（/users 列表与当前登录用户共用同一结构）。
export interface User {
  id: number; // 用户主键 ID
  username: string; // 登录用户名，全平台唯一
  role: PlatformRole; // 平台级角色，决定全站可见范围与菜单权限
  is_active: boolean; // 账号是否启用；被停用后无法登录
  created_at: string; // 创建时间，ISO 8601 字符串
  updated_at: string; // 最后更新时间，ISO 8601 字符串
}

// 登录接口的返回体：token 与用户信息一起下发。
export interface TokenResponse {
  access_token: string; // JWT 访问令牌，写入 Authorization: Bearer 头
  token_type: string; // 令牌类型，固定为 bearer
  expires_in: number; // 令牌剩余有效期，单位秒
  user: User; // 当前登录用户快照，前端据此判断权限
}
