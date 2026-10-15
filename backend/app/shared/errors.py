"""统一应用错误与异常处理。

统一错误响应体：
    {"code": "ERR_X", "message": "...", "request_id": "..."}

状态码语义与旧项目保持一致：
- 401：令牌无效/过期/已被撤销、用户不存在
- 403：令牌有效但权限不足（含「该账户已被禁用」）
- 404：资源不存在或当前用户无权访问（隐藏存在性）
- 422：请求校验失败
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

# 错误码字典：前端可据此区分业务分支。
CODE_TOKEN_EXPIRED = "ERR_TOKEN_EXPIRED"
CODE_USER_NOT_FOUND = "ERR_USER_NOT_FOUND"
CODE_ACCOUNT_DISABLED = "ERR_ACCOUNT_DISABLED"
CODE_FORBIDDEN = "ERR_FORBIDDEN"
CODE_NOT_FOUND = "ERR_NOT_FOUND"
CODE_VALIDATION = "ERR_VALIDATION"
CODE_CONFLICT = "ERR_CONFLICT"
CODE_BAD_REQUEST = "ERR_BAD_REQUEST"
CODE_RATE_LIMITED = "ERR_RATE_LIMITED"
CODE_INTERNAL = "ERR_INTERNAL"

# Phase 2：测试报告 + 飞书通知相关错误码（§三十五）。
CODE_REPORT_NOT_FOUND = "ERR_REPORT_NOT_FOUND"
CODE_REPORT_GENERATION_FAILED = "ERR_REPORT_GENERATION_FAILED"
CODE_REPORT_ALREADY_EXISTS = "ERR_REPORT_ALREADY_EXISTS"
CODE_REPORT_AI_SUMMARY_FAILED = "ERR_REPORT_AI_SUMMARY_FAILED"
CODE_NOTIFICATION_CHANNEL_NOT_FOUND = "ERR_NOTIFICATION_CHANNEL_NOT_FOUND"
CODE_NOTIFICATION_CHANNEL_DISABLED = "ERR_NOTIFICATION_CHANNEL_DISABLED"
CODE_FEISHU_WEBHOOK_INVALID = "ERR_FEISHU_WEBHOOK_INVALID"
CODE_FEISHU_SEND_FAILED = "ERR_FEISHU_SEND_FAILED"
CODE_FEISHU_SIGNATURE_FAILED = "ERR_FEISHU_SIGNATURE_FAILED"

# 测试数据中心 + Data Factory 相关错误码（Phase A/B/C）。
# 与 core 的 ERR_* 不同，数据域错误码**不加前缀**：前端可直接按业务语义分支。
CODE_FIXTURE_NOT_FOUND = "FIXTURE_NOT_FOUND"
CODE_FIXTURE_DEPENDENCY_CYCLE = "FIXTURE_DEPENDENCY_CYCLE"
CODE_FIXTURE_INVALID = "FIXTURE_INVALID"
CODE_FIXTURE_DISABLED = "FIXTURE_DISABLED"
CODE_FIXTURE_GENERATION_FAILED = "FIXTURE_GENERATION_FAILED"
CODE_FIXTURE_STEP_UNSUPPORTED = "FIXTURE_STEP_UNSUPPORTED"
CODE_DATA_RESOLVE_FAILED = "DATA_RESOLVE_FAILED"
CODE_VARIABLE_RESOLVE_FAILED = "VARIABLE_RESOLVE_FAILED"
CODE_SETUP_FAILED = "SETUP_FAILED"
CODE_CLEANUP_FAILED = "CLEANUP_FAILED"
CODE_PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
CODE_PROVIDER_DISABLED = "PROVIDER_DISABLED"
CODE_DATA_POOL_EXHAUSTED = "DATA_POOL_EXHAUSTED"
CODE_DATA_EXECUTION_NOT_FOUND = "DATA_EXECUTION_NOT_FOUND"
CODE_DATABASE_ENVIRONMENT_FORBIDDEN = "DATABASE_ENVIRONMENT_FORBIDDEN"
CODE_DATABASE_OPERATION_FORBIDDEN = "DATABASE_OPERATION_FORBIDDEN"
CODE_DATABASE_TABLE_NOT_ALLOWED = "DATABASE_TABLE_NOT_ALLOWED"
CODE_DATABASE_CONNECTION_FAILED = "DATABASE_CONNECTION_FAILED"


# 所有 401 共用同一文案：不区分「令牌过期」「版本被撤销」「用户已删除」，
# 避免攻击者通过差异判断某个 sub 是否存在。
AUTH_REQUIRED_MESSAGE = "登录失效，请重新登录"

# 错误信封缺省码映射：调用方未显式给 code 时按 HTTP 状态码回查；
# 5xx 不在此表中，统一落到 CODE_INTERNAL，避免把内部错误归到业务错误码上。
DEFAULT_CODE_BY_STATUS: dict[int, str] = {
    400: CODE_BAD_REQUEST,
    401: CODE_TOKEN_EXPIRED,
    403: CODE_FORBIDDEN,
    404: CODE_NOT_FOUND,
    409: CODE_CONFLICT,
    422: CODE_VALIDATION,
    429: CODE_RATE_LIMITED,
}


class AppError(Exception):
    """业务层可携带状态码与错误码的统一异常。"""

    def __init__(self, message: str, *, status_code: int = 400, code: str | None = None) -> None:
        """初始化业务异常。

        Args:
            message: 面向用户的错误文案（会原样进入错误信封的 message 字段）。
            status_code: HTTP 状态码，缺省 400；决定前端走哪条失败分支。
            code: 业务错误码，缺省时按 status_code 查 DEFAULT_CODE_BY_STATUS，
                查不到（如 5xx）则落 CODE_INTERNAL。
        """
        self.message = message
        self.status_code = status_code
        # 错误码回查：显式 code 优先，其次按状态码映射，最后兜底 ERR_INTERNAL。
        self.code = code or DEFAULT_CODE_BY_STATUS.get(status_code, CODE_INTERNAL)
        super().__init__(message)

    def to_http_exception(self) -> HTTPException:
        """转成 FastAPI 的 HTTPException，便于复用全局异常处理器。

        Returns:
            HTTPException: 只带 status_code/detail/headers，错误信封仍由统一处理器拼装。
        """
        return HTTPException(status_code=self.status_code, detail=self.message, headers=self.headers())

    def headers(self) -> dict[str, str]:
        """返回响应头；仅 401 需要 WWW-Authenticate，提示前端走重新登录流程。

        Returns:
            dict[str, str]: 401 时含 {"WWW-Authenticate": "Bearer"}，其它状态码返回空字典。
        """
        return {"WWW-Authenticate": "Bearer"} if self.status_code == 401 else {}


def unauthorized(message: str = AUTH_REQUIRED_MESSAGE) -> HTTPException:
    """401：令牌无效或已被撤销。"""
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message,
                         headers={"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "权限不足") -> HTTPException:
    """403：令牌有效但权限不足（含「该账户已被禁用」分支）。"""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def not_found(message: str = "资源不存在") -> HTTPException:
    """404：资源不存在，或当前用户无权访问（用 404 隐藏资源存在性）。"""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def conflict(message: str = "资源冲突") -> HTTPException:
    """409：资源冲突，例如重复名称、已被他人占用。"""
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def bad_request(message: str = "请求参数有误") -> HTTPException:
    """400：请求本身不合法（区别于 422 的字段级校验失败）。"""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _request_id(request: Request) -> str:
    """读取中间件挂在 request.state 上的请求链路 ID。

    Returns:
        str: request_id；尚未注入（例如中间件未装配）时返回空串而非报错。
    """
    return getattr(request.state, "request_id", "") or ""


def _detail_to_message(detail: Any) -> str:
    """FastAPI/Pydantic 的 detail 可能是 list[dict]，统一转成可读文案。

    Returns:
        str: 可直接展示给用户的单行文案。dict 取 "message" 或 "detail" 字段；
        list 逐条转成 "字段路径: 消息" 并用「；」拼接，非 dict 元素直接 str()。
    """
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        if "message" in detail:
            return str(detail["message"])
        if "detail" in detail and isinstance(detail["detail"], str):
            return detail["detail"]
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                loc = item.get("loc") or ()
                # 去掉 loc 里的 "body" 段：那只是 FastAPI 的请求体包装名，对用户没有意义。
                loc_text = ".".join(str(p) for p in loc if p != "body")
                msg = item.get("msg", "")
                parts.append(f"{loc_text}: {msg}".strip(": "))
            else:
                parts.append(str(item))
        return "；".join(parts)
    return str(detail)


def _error_body(request: Request, status_code: int, message: str, code: str | None = None) -> dict[str, str]:
    """拼装统一错误信封 {code, message, request_id}，前端可据此区分业务分支。

    Args:
        status_code: HTTP 状态码，用于缺省错误码的回查。
        code: 显式错误码；为空时按 DEFAULT_CODE_BY_STATUS 回查，查不到则 ERR_INTERNAL。
    """
    return {
        "code": code or DEFAULT_CODE_BY_STATUS.get(status_code, CODE_INTERNAL),
        "message": message,
        "request_id": _request_id(request),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一错误处理：HTTPException / 校验错误 / 兜底 500。"""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """HTTPException → 错误信封。

        优先级：先取 exc.code，其次 exc.detail 字典里的 "code"，最后按状态码回查默认码。
        """
        code = getattr(exc, "code", None)
        if not code:
            body_detail = exc.detail
            code = None
            if isinstance(body_detail, dict) and body_detail.get("code"):
                code = str(body_detail["code"])
                message = _detail_to_message(body_detail.get("message", body_detail))
            else:
                message = _detail_to_message(body_detail)
        else:
            message = _detail_to_message(exc.detail)
        if message == "Not authenticated" or (
            exc.status_code == 401 and message != AUTH_REQUIRED_MESSAGE
        ):
            # OAuth2PasswordBearer 的默认英文文案（缺少 Authorization 头，或头不是
            # Bearer 前缀），以及任何自定义 401，都归一为同一文案，不泄露失败原因。
            message = AUTH_REQUIRED_MESSAGE
        headers = dict(exc.headers or {})
        headers.pop("content-type", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, exc.status_code, message, code),
            headers=headers,
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """业务层抛出的 AppError → 错误信封，保留其自带的 status_code 与 code。"""
        response = JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, exc.status_code, exc.message, exc.code),
            headers=exc.headers(),
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Pydantic 校验失败 → 422 信封，错误码固定为 ERR_VALIDATION。

        把 detail 的多条字段错误压成一行可读文案，避免直接回吐 Pydantic 的原始结构。
        """
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            # 显式覆盖 code：保证校验错误永远报 ERR_VALIDATION，不被状态码映射改写成别的码。
            content={**_error_body(request, 422, _detail_to_message(exc.errors())), "code": CODE_VALIDATION},
        )

    # 兜底处理器必须最后注册：任何未被上面几条捕获的异常都收敛到统一 500 信封。
    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底 500：吞掉异常详情（不泄露堆栈与内部信息），仅回固定文案。"""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(request, 500, "服务器内部错误", CODE_INTERNAL),
        )
