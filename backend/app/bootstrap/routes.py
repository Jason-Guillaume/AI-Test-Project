"""顶层 HTTP 路由装配。

所有业务路由挂在同一个 APIRouter 下，再由 app.main 统一加上 /api/v1 版本前缀。
顺序无关，因为各 feature 的前缀互不重叠；通知模块内部已保证
`/summary`、`/events`、`/read-all` 等固定路径写在 `/{notification_id}` 之前。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.features.captcha.router import router as captcha_router
from app.features.business.router import router as business_router
from app.features.dashboard.router import router as dashboard_router
from app.features.defects.router import router as defects_router
from app.features.environment_configuration.router import router as environment_router
from app.features.model_configuration.router import router as model_configuration_router
from app.features.notifications.router import router as notifications_router
from app.features.organizations.router import router as organizations_router
from app.features.projects.router import router as projects_router
from app.features.users.admin import router as users_admin_router
from app.features.users.auth import router as users_auth_router

router = APIRouter()

# 用户与认证相关路由必须最先装配，保证 /auth/* 与 /users/* 的鉴权中间件在链上生效
router.include_router(captcha_router)
router.include_router(users_auth_router)
router.include_router(users_admin_router)
# 组织与项目：所有后续资源都依赖「组织→项目」这层关系，权限检查从这里开始
router.include_router(organizations_router)
router.include_router(projects_router)
# 缺陷管理：挂在项目之后，因为缺陷的可见性边界完全依赖项目权限
router.include_router(defects_router)
# 业务管理：依赖项目权限，且其业务绑定引用接口管理（api_catalog），故装配在两者之后
router.include_router(business_router)
# 平台级配置：模型与环境是项目成员调用的下游依赖，装配在项目之后便于故障隔离
router.include_router(model_configuration_router)
router.include_router(environment_router)
# 通知与看板：只读当前用户收件箱 / 当前用户可见范围，放在最后不影响其它业务路由
router.include_router(notifications_router)
router.include_router(dashboard_router)
