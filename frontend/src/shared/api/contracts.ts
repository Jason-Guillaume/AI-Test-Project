// api 领域类型合同；仅暴露当前模块稳定使用的请求、响应与查询类型。


// 后端统一的分页信封：所有列表接口都按这个形状返回。
export interface Paginated<T> {
  items: T[]; // 当前页数据
  total: number; // 过滤条件下的总条数（不是当前页条数）
  page: number; // 当前页码，从 1 开始
  page_size: number; // 每页条数
}

// 健康检查项（/ready 接口用）。
export interface ReadyCheckItem {
  name: string; // 检查项名称，如 database / redis
  status: string; // 检查状态，如 ok / fail
  detail: string | null; // 失败原因或补充信息；正常时为 null
}

// 健康检查整体返回。
export interface ReadyResponse {
  status: string; // 整体状态，如 ready / degraded
  checks: ReadyCheckItem[]; // 各项检查明细
}

// 统一错误体

// 后端统一错误信封：所有非 2xx 响应都长这样。
export interface ApiErrorBody {
  code: string; // 机器可读的错误码，前端按它做分支处理
  message: string; // 可直接展示给用户的错误描述
  request_id: string; // 请求追踪 ID，用于联系后端排查
}
