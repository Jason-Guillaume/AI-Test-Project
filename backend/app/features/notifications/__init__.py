"""通知模块：用户收件箱与已读状态。

对外暴露两个子模块：
- router  : HTTP 路由（/api/v1/notifications），只读当前用户收件箱
- schemas : Pydantic 契约，统一分页信封 {items, total, page, page_size}

通知的产生方在别处（用户/组织/项目动作）；本模块不做通知模板或渠道配置，
那部分属于通知引擎，不在第一阶段范围内。
"""
