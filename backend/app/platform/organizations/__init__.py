"""组织模块：组织信息与成员角色管理。

包含三个子模块，路由前缀统一挂在 /api/v1/organizations 下：
- schemas：组织、成员与模型授权的 Pydantic 契约（请求体与响应信封）
- router：面向前端的组织 CRUD、成员管理、模型分配与负责人转移接口
- service：组织边界检查、成员资格、组织管理员判定与注册时的个人组织创建，
  被多个 feature 模块（如 users 注册流程）复用，因此不依赖其它 feature 的路由层

与 users 模块的分工：users 负责平台级身份与令牌，organizations 负责平台内
的协作边界（谁能看到/管理哪个组织）。所有列表接口统一返回 {items, total,
page, page_size} 信封，便于前端复用同一套 TanStack Query 分页处理。
"""
