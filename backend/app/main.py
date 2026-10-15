"""FastAPI 应用工厂。

运行时能力与旧项目对齐：请求 ID 中间件、CORS、统一异常处理、`/api/v1` 版本前缀。
新增约束：应用启动不自动变更表结构，全部结构变更走 Alembic；
仅在 ``AUTO_CREATE_SCHEMA=true`` 时允许启动期 create_all（限本地首次调试）。

启动方式（开发）：
    uvicorn app.main:app --reload --port 8000

本模块被 gunicorn / uvicorn 通过 `app.main:app` 加载；`lifespan` 负责启动期
副作用（日志、连接探测），`create_app` 负责中间件、异常映射与路由装配。
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  集中导入全部 ORM 模型，确保 metadata 完整
from app.features.agent.router import router as agent_router
from app.features.api_catalog.router import router as api_catalog_router
from app.features.business.router import router as business_router
from app.features.captcha.router import router as captcha_router
from app.features.dashboard.router import router as dashboard_router
from app.features.defects.router import router as defects_router
from app.features.environment_configuration.router import router as environments_router
from app.features.mock_management.router import router as mock_management_router
from app.features.mock_management.runtime_router import router as mock_runtime_router
from app.features.model_configuration.router import router as model_configs_router
from app.features.notifications.router import router as notifications_router
from app.features.notifications.channel_router import router as notification_channel_router
from app.features.organizations.router import router as organizations_router
from app.features.projects.router import router as projects_router
from app.features.reports.router import router as reports_router
from app.features.test_data.router import router as test_data_router
from app.features.test_management.router import router as test_management_router
from app.features.users.admin import router as users_admin_router
from app.features.users.auth import router as auth_router
from app.shared.config import settings
from app.shared.database import Base, engine
from app.shared.errors import register_exception_handlers
from app.shared.request_context import (
    configure_logging,
    request_id_context,
    resolve_request_id,
)

# 本模块的日志统一走这里，输出格式与 request_id 注入由 app.shared.request_context 配置。
logger = logging.getLogger(__name__)

# 业务路由统一挂在 /api/v1 下；新增路由时必须走 include_router(prefix=API_PREFIX)，不要另起前缀。
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动期记录基本信息，并按开关处理本地自动建表。

    Args:
        _: FastAPI 应用实例，仅在签名上出现，函数体内不使用。

    Yields:
        AsyncIterator[None]: 应用运行期；上下文退出后释放连接池。
    """
    configure_logging()
    # 只打印数据库 URL 的 host 部分（@ 之后），避免把用户名/密码泄漏到日志
    logger.info(
        "启动 %s v%s（数据库：%s）",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.DATABASE_URL.split("@")[-1] if settings.DATABASE_URL else "未配置",
    )
    # 降级路径：默认 AUTO_CREATE_SCHEMA=False，启动期不做任何表结构变更；
    # 仅本地首次调试允许打开，避免和 Alembic 迁移脚本产生双写。
    if settings.AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        session = factory()
        try:
            # SELECT 1 只做连接探测，不访问业务表；用来提前暴露配置错误
            probe = session.execute(text("SELECT 1")).scalar()
            logger.info("AUTO_CREATE_SCHEMA 已开启，create_all 完成（连接探测：%s）", probe)
        finally:
            session.close()
    yield
    # 停止期回收连接池，避免 gunicorn worker 反复退出时留下半开连接
    engine.dispose()
    logger.info("应用已停止")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 跨域：来源由环境变量给出并逐条去空白（空串直接丢弃）；
    # 显式 expose X-Request-ID，前端报障时可以带上同一请求 ID 便于后端按日志定位。
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def attach_request_context(request: Request, call_next):
        """为每个请求分配请求 ID，写入 state、响应头与日志上下文。"""
        request_id = resolve_request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.error("method=%s path=%s unhandled_error", request.method, request.url.path)
            raise
        finally:
            request_id_context.reset(token)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started_at) * 1000,
        )
        return response

    # 统一错误信封（401/403/404/422/兜底 500）在装配路由前注册，确保所有路由共用同一响应格式。
    register_exception_handlers(application)

    @application.get("/healthz", tags=["系统"], summary="存活探针")
    def healthz():
        """存活检查，不访问数据库，用于容器 liveness。"""
        return {"status": "ok"}

    @application.get("/health", tags=["系统"], summary="进程健康检查")
    def health_check():
        """进程健康检查，与 /healthz 语义相同，保留给外部监控工具约定路径。

        Returns:
            dict[str, str]: 固定返回 {"status": "ok"}；不访问数据库，因此不能用于依赖就绪判断。
        """
        return {"status": "ok"}

    @application.get(f"{API_PREFIX}/meta", tags=["系统"], summary="应用元信息")
    def meta():
        """返回应用名、版本与文档地址，供前端展示当前连接的后端版本。

        Returns:
            dict[str, str]: 含 name / version / docs 三个字段，version 取自配置项 VERSION。
        """
        return {"name": settings.PROJECT_NAME, "version": settings.VERSION, "docs": "/docs"}

    # 路由装配：每个 feature 自带 prefix 时只补 API_PREFIX，不在此处改路由前缀。
    # 验证码接口不要求登录（注册前置），与 auth_router 同层装配，便于错误日志归因。
    application.include_router(captcha_router, prefix=API_PREFIX)
    application.include_router(auth_router, prefix=API_PREFIX)
    application.include_router(users_admin_router, prefix=API_PREFIX)
    application.include_router(organizations_router, prefix=API_PREFIX)
    application.include_router(projects_router, prefix=API_PREFIX)
    application.include_router(defects_router, prefix=API_PREFIX)
    application.include_router(api_catalog_router, prefix=API_PREFIX)
    application.include_router(business_router, prefix=API_PREFIX)
    application.include_router(test_management_router, prefix=API_PREFIX)
    # 报告依赖 test_management（TestRun / CaseExecution），紧随其后装配。
    application.include_router(reports_router, prefix=API_PREFIX)
    application.include_router(agent_router, prefix=API_PREFIX)
    application.include_router(notifications_router, prefix=API_PREFIX)
    # 通知渠道（飞书 Webhook 配置/测试/触发/审计），挂在通知之后便于故障隔离。
    application.include_router(notification_channel_router, prefix=API_PREFIX)
    application.include_router(model_configs_router, prefix=API_PREFIX)
    application.include_router(environments_router, prefix=API_PREFIX)
    application.include_router(dashboard_router, prefix=API_PREFIX)
    application.include_router(test_data_router, prefix=API_PREFIX)
    # Mock Management：管理面（需平台 JWT）与执行面（X-Mock-Token）分离（§十四）。
    # 执行面 router 自带 prefix=/mock，catch-all 挂在 /api/v1/mock 下，必须最后装配，
    # 避免其 {path:path} 吞掉其它路由（/mock/ 与 /mock-services/ 不冲突）。
    application.include_router(mock_management_router, prefix=API_PREFIX)
    application.include_router(mock_runtime_router, prefix=API_PREFIX)
    return application


# 模块加载即创建应用实例：uvicorn / gunicorn 通过 `app.main:app` 直接引用它，
# 因此 lifespan 的启动副作用只执行一次，不在导入时重复建表或打日志之外的逻辑。
app = create_app()
