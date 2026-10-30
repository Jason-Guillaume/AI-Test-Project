"""安全基线：环境闸门与 BaselineRequest 组装。

这个模块仍然是纯函数（§6.3）：不 import httpx、不查库、不 eval。它只接受
「已经解析完的数据」，所以变量解析、环境归类与 DB 读取都在 ``runner.py`` 里
做完再传进来。两个依赖用参数注入，保持本模块可离线单测：

- ``resolve``：模板变量解析函数，复用 ``test_case_executor`` 的现有实现，
  本模块不自己再写一套解析规则。
- ``build_url``：URL 拼接函数，调用 ``app.execution.http.request_builder``。
  runner 是唯一允许 import 执行器的模块，URL 拼接因此放在 runner 调用，
  这里只保留路径参数替换的纯实现，供需要单独校验 path 占位符的地方复用。

环境闸门（§18.3）分三层，任一命中即不发请求：

1. 生产：归类为 PRODUCTION，或本次请求命中的出站目标被登记为生产目标
   （``project_outbound_target.is_production``）——环境名叫 ``dev`` 但指向已标记
   生产的目标同样拒绝。生产不看 ``allow_production``，只记录意图不生效。
2. DEV / TEST：默认允许，项目设置里可以各自关掉。
3. STAGING（含未知环境名）：默认拒绝，只有 editor 打开 ``allow_staging`` 才放行。

拒绝发生在基线请求之前，因此基线也不发，不是「基线发完再挡变异」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.features.security_testing.runtime.types import BaselineRequest

__all__ = [
    "PRODUCTION_ENVIRONMENT_NAMES",
    "DEFAULT_TIMEOUT",
    "EnvironmentDecision",
    "decide_environment",
    "resolve_path_params",
    "build_request",
]

#: 环境名命中即视为生产（§20.2 的显式用例）。大小写与首尾空白不敏感。
PRODUCTION_ENVIRONMENT_NAMES = frozenset({"prod", "production"})

#: 与 ``ApiRequestExecutor.execute`` 的默认超时保持一致。
DEFAULT_TIMEOUT = 30

#: 默认放行、可被项目设置关闭的归类。
ALLOWED_BY_DEFAULT = frozenset({"DEV", "TEST"})

#: 未知环境名的归类：一律按预发处理，默认拒绝。
UNKNOWN_CLASSIFICATION = "STAGING"


@dataclass(frozen=True)
class EnvironmentDecision:
    """环境闸门结论。``reason`` 在允许时为 ``OK``。"""

    allowed: bool
    reason: str


def decide_environment(
    environment_name: str | None,
    *,
    classification: str = "",
    outbound_production: bool = False,
    allow_dev: bool = True,
    allow_test: bool = True,
    allow_staging: bool = False,
) -> EnvironmentDecision:
    """判断这个环境能不能发安全变异请求（§18.3）。

    Args:
        environment_name: 环境 ``name``。仅在 ``classification`` 为空时用来判断生产。
        classification: ``db_guard.classify(environment.name)`` 的结果。未知名字
            在那里已经被归为 STAGING。
        outbound_production: 请求命中的出站目标是否被登记为生产目标。
        allow_dev / allow_test / allow_staging: 项目设置里的三个开关。

    Returns:
        EnvironmentDecision: ``allowed`` 为 False 时 ``reason`` 说明被哪一条挡住。
    """
    resolved = str(classification or "").strip().upper()
    if not resolved:
        # 调用方没给归类时只保留最保守的一条：名字像生产就是生产。
        resolved = "PRODUCTION" if is_production_environment(environment_name) else UNKNOWN_CLASSIFICATION

    if resolved == "PRODUCTION" or outbound_production:
        return EnvironmentDecision(False, "PRODUCTION")
    if resolved == "DEV":
        return EnvironmentDecision(bool(allow_dev), "OK" if allow_dev else "DEV_NOT_ALLOWED")
    if resolved == "TEST":
        return EnvironmentDecision(bool(allow_test), "OK" if allow_test else "TEST_NOT_ALLOWED")
    return EnvironmentDecision(bool(allow_staging), "OK" if allow_staging else "STAGING_NOT_ALLOWED")


def is_production_environment(environment_name: str | None) -> bool:
    """环境名是否命中生产命名（大小写与首尾空白不敏感）。"""
    return str(environment_name or "").strip().lower() in PRODUCTION_ENVIRONMENT_NAMES


def _template_placeholders(path: str | None) -> list[str]:
    """取出路径模板里的占位符名（``/tasks/{id}/x`` → ``["id"]``）。"""
    out: list[str] = []
    text = path or ""
    i = 0
    while True:
        start = text.find("{", i)
        if start < 0:
            return out
        end = text.find("}", start + 1)
        if end < 0:
            return out
        name = text[start + 1 : end].strip()
        if name:
            out.append(name)
        i = end + 1


def resolve_path_params(path: str | None, params: dict[str, Any] | None) -> dict[str, str]:
    """把基线用例给出的路径参数按模板占位符收窄。

    只做两件事：转成字符串、丢掉模板里没有的多余键。模板里有但用例没给值的
    占位符原样保留 ``{name}``——执行器会把它留成字面量，服务端通常会回 404，
    这比悄悄用空串拼出 ``/tasks//detail`` 更容易被发现。
    """
    wanted = set(_template_placeholders(path))
    if not wanted:
        return {str(k): str(v) for k, v in (params or {}).items()}
    out = {str(k): str(v) for k, v in (params or {}).items() if str(k) in wanted}
    for name in wanted:
        out.setdefault(name, "{" + name + "}")
    return out


def _pick_timeout(value: Any) -> int:
    """超时取值夹到 1~120 秒。"""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return max(1, min(seconds, 120))


def build_request(
    *,
    method: str | None,
    path: str | None,
    step_config: dict[str, Any] | None,
    scope: Any,
    resolve: Any,
    data_values: dict[str, Any] | None,
    environment_headers: dict[str, str] | None,
    extra_headers: dict[str, str] | None,
    path_params: dict[str, Any] | None = None,
    auth_type: str = "none",
    api_id: int | None = None,
    project_id: int | None = None,
) -> BaselineRequest:
    """把基线用例的请求配置组装成 ``BaselineRequest``。

    取值优先级与既有 ``_execute_api`` 完全一致（否则安全基线与功能用例跑的是
    两个不同的请求，结论就不可信）：step_config 优先，其次接口默认值，
    body 缺省回退到测试数据。``resolve`` 在这里做一次模板解析。

    Args:
        method: 接口默认方法，被 step_config 覆盖。
        path: 接口路径模板（含 ``{param}``），原样保留，URL 由执行器拼。
        step_config: 用例的 step 配置（method/headers/query/path_params/body/timeout）。
        scope: 变量解析作用域，传给 ``resolve``。
        resolve: ``Callable[[obj, scope], obj]``，复用现有 ``_resolve_tokens``。
        data_values: 测试数据值；step_config 没有 body 时作为 json body 兜底。
        environment_headers: 环境默认请求头。
        extra_headers: 上游（Mock 等）附加头，最先并入，随后被环境头覆盖。
        path_params: 模板占位符取值。
    """
    config = step_config or {}
    resolved = lambda obj: resolve(obj, scope)  # noqa: E731 - 只做转发，不持有状态

    headers = dict(extra_headers or {})
    headers.update(environment_headers or {})
    headers.update({str(k): str(v) for k, v in (resolved(config.get("headers")) or {}).items()})

    body = config.get("body")
    if body is not None:
        json_body = resolved(body)
    else:
        json_body = resolved(data_values) if data_values else None

    return BaselineRequest(
        method=str(config.get("method") or method or "GET").upper(),
        path=str(path or ""),
        path_params=resolve_path_params(path, config.get("path_params") or path_params),
        query={str(k): str(v) for k, v in (resolved(config.get("query")) or {}).items()},
        headers=headers,
        json_body=json_body,
        timeout=_pick_timeout(config.get("timeout", DEFAULT_TIMEOUT)),
        api_id=api_id,
        project_id=project_id,
        auth_type=str(auth_type or "none"),
    )
