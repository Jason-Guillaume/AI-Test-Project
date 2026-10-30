"""变异算子注册表：一个 ``mutation_type`` 一个纯函数。

算子只做一件事：把规则应用到 ``BaselineRequest`` 的副本上，并返回 trace 条目。
禁止项（§6.3）：不发 HTTP、不查库、不 ``eval``。所有取值都是结构化配置里能算出来
的常量或 schema 推导值——不生成随机长串，不拼接 JWT。

认证类算子的固定哨兵不是伪造的 JWT：`Bearer invalid-token` / `Bearer a.b` 都是
无法通过任何解码校验的字符串；`Basic aW52YWxpZDpinv` 解出来是 `invalid:inv`，
不带任何真实口令。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.core.http.errors import (
    CODE_SECURITY_CONFIRMATION_REQUIRED,
    CODE_SECURITY_FIXTURE_REQUIRED,
    CODE_SECURITY_MUTATION_INVALID,
    AppError,
)

from app.features.security_testing.runtime import candidate_resolver
from app.features.security_testing.runtime.schema_reader import (
    over_max_capped,
    value_for,
)
from app.features.security_testing.runtime.types import (
    ConfirmationRequiredError,
    FieldSpec,
    MutationContext,
    MutationRuleView,
    MutationTraceEntry,
    RuleNotApplicableError,
)

__all__ = [
    "OPERATORS",
    "CATEGORY_BY_MUTATION_TYPE",
    "register_operator",
    "get_operator",
    "resolve_auth_header",
    "INVALID_TOKEN_VALUE",
    "MALFORMED_TOKEN_VALUE",
    "WRONG_AUTH_SCHEME_VALUE",
    "CONTENT_TYPE_TARGET",
]

OperatorFn = Callable[[Any, MutationContext], list[MutationTraceEntry]]

#: 算子注册表。未注册的类型在引擎里归 SECURITY_MUTATION_NOT_ALLOWED（未开放）。
OPERATORS: dict[str, OperatorFn] = {}

#: mutation_type → 策略类别。规则表上没有 category 列，缺省时按此反查。
CATEGORY_BY_MUTATION_TYPE: dict[str, str] = {}
for _category, _types in (
    ("AUTHENTICATION", ("REMOVE_TOKEN", "EMPTY_TOKEN", "INVALID_TOKEN", "MALFORMED_TOKEN",
                        "WRONG_AUTH_SCHEME", "EXPIRED_TOKEN")),
    ("AUTHORIZATION", ("CROSS_USER", "CROSS_PROJECT", "ROLE_DOWNGRADE", "RESOURCE_OWNER_CHANGE")),
    ("IDOR", ("IDOR",)),
    ("PARAMETER", ("REMOVE_FIELD", "NULL_VALUE", "EMPTY_STRING", "TYPE_MUTATION", "ZERO",
                   "NEGATIVE", "OVER_MAX", "UNDER_MIN", "INVALID_ENUM", "INVALID_FORMAT")),
    ("HEADER", ("REMOVE_HEADER", "EMPTY_HEADER", "INVALID_HEADER_VALUE",
                "CONTENT_TYPE_MUTATION", "AUTHORIZATION_MUTATION")),
    ("METHOD", ("METHOD_MUTATION",)),
    ("REPLAY", ("REPLAY_SAME_REQUEST",)),
    ("DUPLICATE_SUBMIT", ("DUPLICATE_SUBMIT",)),
    ("BUSINESS_STATE", ("BUSINESS_STATE", "SEQUENCE_BYPASS")),
):
    for _type in _types:
        CATEGORY_BY_MUTATION_TYPE[_type] = _category


def register_operator(type_: str):
    """把算子函数登记进注册表。"""

    def decorator(fn: OperatorFn) -> OperatorFn:
        """为业务计划步骤注册所需的函数装饰器。"""
        OPERATORS[type_] = fn
        return fn

    return decorator


def get_operator(type_: str) -> OperatorFn | None:
    """取算子；未开放返回 None。"""
    return OPERATORS.get(type_)


# --------------------------------------------------------------------------- 认证类哨兵

#: 固定非法 Token 哨兵（不是 JWT，无法通过任何签名校验）。
INVALID_TOKEN_VALUE = "Bearer invalid-token"
#: 固定畸形 Token：两段 base64 片段，缺少签名段。
MALFORMED_TOKEN_VALUE = "Bearer a.b"
#: 固定非法 Basic 凭据：base64("invalid:inv")，不含真实口令。
WRONG_AUTH_SCHEME_VALUE = "Basic aW52YWxpZDpinv"
#: CONTENT_TYPE_MUTATION 的目标内容类型。
CONTENT_TYPE_TARGET = "text/plain"
#: REMOVE_HEADER / EMPTY_HEADER 的默认目标头。
DEFAULT_HEADER_TARGET = "Content-Type"
#: 方法变异的默认对：只测一个，不铺方法集合。
DEFAULT_METHOD_PAIR = {"POST": "GET", "GET": "POST"}
#: 允许的 HTTP 方法白名单；白名单外一律拒绝。
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
#: auth_type → 鉴权头名（Catalog 的 auth_type 是自由字符串，这里只认常见取值）。
AUTH_HEADER_BY_TYPE = {
    "bearer": "Authorization",
    "basic": "Authorization",
    "digest": "Authorization",
    "http": "Authorization",
    "cookie": "Cookie",
    "session": "Cookie",
}

_DELETE = object()


# --------------------------------------------------------------------------- 定位工具


def _find_header_key(mapping: dict[str, Any] | None, name: str) -> str | None:
    """大小写不敏感地找键名（HTTP 头没有大小写语义）。"""
    wanted = str(name).lower()
    for key in mapping or {}:
        if str(key).lower() == wanted:
            return key
    return None


def _string_value(value: Any) -> str:
    """PATH/QUERY/HEADER/COOKIE 上的值必须能序列化成字符串。"""
    return "null" if value is None else str(value)


def _body_path(spec: FieldSpec) -> list[str]:
    """body 字段的定位路径；没写 json_path 时按 $.name 处理。"""
    path = spec.json_path or f"$.{spec.name}"
    return path.lstrip("$").strip(".").split(".")


def _read_body_value(body: Any, spec: FieldSpec) -> Any:
    """按路径读 body 字段；路径不存在返回 None。"""
    node = body
    for part in _body_path(spec):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _set_body_value(body: Any, spec: FieldSpec, value: Any) -> Any:
    """按路径写 body 字段；中间节点缺失时补空 dict（不改原有层级）。"""
    if not isinstance(body, dict):
        return value if body is None and not spec.json_path else body
    parts = _body_path(spec)
    node = body
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value
    return body


def _remove_body_value(body: Any, spec: FieldSpec) -> Any:
    """按路径删 body 字段；顶层字段删掉后 body 可能变成空 dict。"""
    if not isinstance(body, dict):
        return None
    parts = _body_path(spec)
    node = body
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            return body
        node = nxt
    node.pop(parts[-1], None)
    return body


def _read_field(req: Any, spec: FieldSpec) -> Any:
    """读字段当前值（按 location 分派）。"""
    location = spec.location.upper()
    if location == "BODY":
        return _read_body_value(req.json_body, spec)
    if location == "PATH":
        return req.path_params.get(spec.name)
    if location == "QUERY":
        return req.query.get(spec.name)
    if location in {"HEADER", "COOKIE"}:
        mapping = req.headers if location == "HEADER" else req.cookies
        key = _find_header_key(mapping, spec.name)
        return mapping.get(key) if key else None
    return None


def _apply_value(req: Any, ctx: MutationContext, spec: FieldSpec, value: Any,
                 note: str | None = None) -> MutationTraceEntry:
    """把取值写到字段所在位置，并返回这条 trace。"""
    before = _read_field(req, spec)
    location = spec.location.upper()
    if location == "BODY":
        req.json_body = _set_body_value(req.json_body, spec, value)
    elif location == "PATH":
        req.path_params[spec.name] = _string_value(value)
    elif location == "QUERY":
        req.query[spec.name] = _string_value(value)
    elif location == "HEADER":
        key = _find_header_key(req.headers, spec.name) or spec.name
        req.headers[key] = _string_value(value)
    elif location == "COOKIE":
        key = _find_header_key(req.cookies, spec.name) or spec.name
        req.cookies[key] = _string_value(value)
    else:
        raise RuleNotApplicableError(
            f"{ctx.rule.mutation_type} 不支持目标位置 {location}",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return MutationTraceEntry(ctx.rule.mutation_type, location, spec.name, before, value, note)


def _remove_field_value(req: Any, ctx: MutationContext, spec: FieldSpec) -> MutationTraceEntry:
    """删除字段，并返回这条 trace。"""
    before = _read_field(req, spec)
    location = spec.location.upper()
    if location == "BODY":
        req.json_body = _remove_body_value(req.json_body, spec)
    elif location == "PATH":
        req.path_params.pop(spec.name, None)
    elif location == "QUERY":
        req.query.pop(spec.name, None)
    elif location == "HEADER":
        key = _find_header_key(req.headers, spec.name)
        if key:
            req.headers.pop(key, None)
    elif location == "COOKIE":
        key = _find_header_key(req.cookies, spec.name)
        if key:
            req.cookies.pop(key, None)
    else:
        raise RuleNotApplicableError(
            f"REMOVE_FIELD 不支持目标位置 {location}",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return MutationTraceEntry(ctx.rule.mutation_type, location, spec.name, before, None)


def _require_spec(ctx: MutationContext) -> FieldSpec:
    """参数类算子必须有 schema 字段；无 schema 不自动 fuzz。"""
    if ctx.spec is None:
        raise RuleNotApplicableError(
            f"接口 schema 里没有字段 {ctx.rule.target_field!r}，跳过（无 schema 不自动 fuzz）",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return ctx.spec


def resolve_auth_header(auth_type: str | None, headers: dict[str, str] | None) -> str:
    """解析鉴权头名。

    默认 ``Authorization``；``cookie`` 类走 Cookie；``apikey`` / ``custom`` 只知道有
    API Key 认证而不知道头名，就按基线请求里实际存在的头找。
    """
    headers = headers or {}
    declared = AUTH_HEADER_BY_TYPE.get(str(auth_type or "").lower())
    if declared:
        return declared
    for key in headers:
        if str(key).lower() == "authorization":
            return "Authorization"
    for key in headers:
        normalized = str(key).lower().replace("-", "_").replace(" ", "_")
        if normalized in {"api_key", "x_api_key", "apikey", "x_apikey", "x_auth_key"}:
            return key
    return "Authorization"


# --------------------------------------------------------------------------- 认证算子


def _auth_target(req: Any, ctx: MutationContext, header: str) -> tuple[str, str | None]:
    """返回 (头名, 基线当前值)；基线没有该头时值就是 None。"""
    key = _find_header_key(req.headers, header)
    return (key or header), req.headers.get(key) if key else None


def _mutate_auth(req: Any, ctx: MutationContext, replacement: Any, *,
                 header: str | None = None, note: str | None = None) -> list[MutationTraceEntry]:
    """认证类算子的公共实现：replacement 为 ``_DELETE`` 时删头，否则替换值。"""
    target = header or ctx.auth_header
    key, before = _auth_target(req, ctx, target)
    if before is None:
        # 基线不带鉴权头就没有可比对的基线，记成无法下结论，不假装测过。
        ctx.notes.append(f"基线无 {target} 头，无法验证认证是否生效")
        return [MutationTraceEntry(ctx.rule.mutation_type, "HEADER", target, None, None,
                                   note="基线无此头")]
    if replacement is _DELETE:
        req.headers.pop(key, None)
        after: Any = None
    else:
        req.headers[key] = str(replacement)
        after = req.headers[key]
    return [MutationTraceEntry(ctx.rule.mutation_type, "HEADER", key, before, after, note)]


@register_operator("REMOVE_TOKEN")
def op_remove_token(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """删除鉴权头。"""
    return _mutate_auth(req, ctx, _DELETE)


@register_operator("EMPTY_TOKEN")
def op_empty_token(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """值改为空串；原值以 ``Bearer`` 开头时保留方案前缀，避免和「头不存在」混淆。"""
    _key, before = _auth_target(req, ctx, ctx.auth_header)
    replacement = "Bearer " if str(before or "").strip().lower().startswith("bearer") else ""
    return _mutate_auth(req, ctx, replacement)


@register_operator("INVALID_TOKEN")
def op_invalid_token(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """值改为固定非法哨兵 ``Bearer invalid-token``。"""
    return _mutate_auth(req, ctx, INVALID_TOKEN_VALUE)


@register_operator("MALFORMED_TOKEN")
def op_malformed_token(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """值改为缺签名段的畸形串 ``Bearer a.b``。"""
    return _mutate_auth(req, ctx, MALFORMED_TOKEN_VALUE)


@register_operator("WRONG_AUTH_SCHEME")
def op_wrong_auth_scheme(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """方案换成固定非法 Basic 凭据，不带真实口令。"""
    return _mutate_auth(req, ctx, WRONG_AUTH_SCHEME_VALUE)


@register_operator("EXPIRED_TOKEN")
def op_expired_token(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """过期 Token 只能来自测试人员预先准备的 Fixture 输出。

    平台没有「被测系统过期 JWT 生成器」，所以这里不做解码、不做拼接：拿不到
    ``mutation_config.token_source`` 或解析不到输出就直接跳过。
    """
    source = ctx.rule.mutation_config.get("token_source")
    if not isinstance(source, dict):
        raise RuleNotApplicableError(
            "EXPIRED_TOKEN 必须声明 token_source：平台不生成过期 JWT",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    value = ctx.scope.get(source)
    if value in (None, ""):
        raise AppError(
            "缺少过期 Token 的 Fixture 输出，跳过该规则",
            code=CODE_SECURITY_FIXTURE_REQUIRED,
        )
    return _mutate_auth(req, ctx, value, note="过期 Token 取自 Fixture 输出")


@register_operator("AUTHORIZATION_MUTATION")
def op_authorization_mutation(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """HEADER 类里指向 Authorization 的别名，转给认证算子，不另写一套。

    有 ``token_source`` 就换成 Fixture 里的 Token（等价于换身份），没有就删头。
    """
    source = ctx.rule.mutation_config.get("token_source")
    value = ctx.scope.get(source) if isinstance(source, dict) else None
    header = ctx.rule.target_field or None
    if value:
        return _mutate_auth(req, ctx, value, header=header, note="鉴权头取自 Fixture 输出")
    return _mutate_auth(req, ctx, _DELETE, header=header)


# --------------------------------------------------------------------------- 授权 / IDOR 算子
#
# 候选只来自 Fixture 输出契约（见 candidate_resolver）：没有候选就失败或跳过，
# 不用随机数、不用「当前值 ± 1」、不用平台自己的 project_id 去猜。


def _swap_identity(req: Any, ctx: MutationContext, *, label: str, note: str) -> list[MutationTraceEntry]:
    """换身份：把鉴权头换成 Fixture 里的一把 Token。

    Token 只能来自 ``mutation_config.token_source`` 点名的 Fixture 输出；没点名就
    跳过——不在平台用户表里改角色，也不签发平台 JWT。
    """
    token, _ = candidate_resolver.read_sources(ctx.rule)
    value = candidate_resolver.resolve_value(token, ctx.scope, label=label)
    return _mutate_auth(req, ctx, value, note=note)


def _replace_resource(req: Any, ctx: MutationContext, *, label: str) -> MutationTraceEntry:
    """把 path / query / body 里的一个资源字段换成另一个 Fixture 的输出值。

    目标是 PATH 时必须能在路径模板里找到对应占位符：占位符不存在的话替换不会改变
    实际 URL，trace 就会骗人。
    """
    location, field, value = candidate_resolver.resource_target(ctx.rule, ctx.scope, label=label)
    if location == "PATH" and f"{{{field}}}" not in req.path:
        raise RuleNotApplicableError(
            f"接口路径里没有 {{{field}}} 占位符，无法替换该资源 ID",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    spec = FieldSpec(
        location=location,
        name=field,
        json_path=None if location != "BODY" else f"$.{field}",
    )
    return _apply_value(req, ctx, spec, value)


@register_operator("CROSS_USER")
def op_cross_user(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """换用户：点名的替换项做几个做几个——换 Token、换资源 ID，或两者都做。"""
    token, resource = candidate_resolver.read_sources(ctx.rule)
    if token is None and resource is None:
        raise RuleNotApplicableError(
            "CROSS_USER 必须在 mutation_config 里点名 token_source、resource_source 或 candidates（不猜 ID）",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    traces: list[MutationTraceEntry] = []
    if token is not None:
        traces.extend(_swap_identity(req, ctx, label="CROSS_USER 的 Token 候选", note="Token 取自 Fixture 输出"))
    if resource is not None:
        traces.append(_replace_resource(req, ctx, label="CROSS_USER 的资源候选"))
    return traces


@register_operator("CROSS_PROJECT")
def op_cross_project(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """只替换被测请求里的业务项目字段，候选来自 PROJECT_B.project_id 这类输出。

    被测系统的 project_id 与平台自己的 project_id 是两个不同的整数，绝不互相兜底。
    """
    return [_replace_resource(req, ctx, label="CROSS_PROJECT 的项目候选")]


@register_operator("ROLE_DOWNGRADE")
def op_role_downgrade(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """换成低权限身份：低权限 Token 只能由测试人员放进 Fixture。"""
    return _swap_identity(
        req, ctx, label="ROLE_DOWNGRADE 的低权限 Token 候选", note="低权限 Token 取自 Fixture 输出"
    )


@register_operator("RESOURCE_OWNER_CHANGE")
def op_resource_owner_change(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """替换 body / path 里的 owner 字段，候选来自另一个 Fixture。"""
    return [_replace_resource(req, ctx, label="RESOURCE_OWNER_CHANGE 的 owner 候选")]


@register_operator("IDOR")
def op_idor(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """越权：USER_A 的请求里换成 USER_B 的资源 ID。"""
    return [_replace_resource(req, ctx, label="IDOR 的资源候选")]


# --------------------------------------------------------------------------- 参数算子


@register_operator("REMOVE_FIELD")
def op_remove_field(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """删除必填字段；非必填字段删掉不构成校验缺失，跳过。"""
    spec = _require_spec(ctx)
    if not spec.required:
        raise RuleNotApplicableError(
            f"字段 {spec.name!r} 非必填，删除它不构成校验缺失",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return [_remove_field_value(req, ctx, spec)]


@register_operator("NULL_VALUE")
def op_null_value(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """字段置 null（schema 可空且非必填时无验证意义）。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "NULL_VALUE"))]


@register_operator("EMPTY_STRING")
def op_empty_string(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """string 字段置空串。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "EMPTY_STRING"))]


@register_operator("TYPE_MUTATION")
def op_type_mutation(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """类型错位：integer/number → "abc"，string → 1，boolean → "yes"。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "TYPE_MUTATION"))]


@register_operator("ZERO")
def op_zero(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """数值字段置 0。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "ZERO"))]


@register_operator("NEGATIVE")
def op_negative(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """数值字段置 -1；schema 已允许负数时跳过。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "NEGATIVE"))]


@register_operator("OVER_MAX")
def op_over_max(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """超过 maximum / maxLength；字符串样本封顶 256 字符。"""
    spec = _require_spec(ctx)
    note = "maxLength 已超过 256 封顶，样本可能并不真的超长" if over_max_capped(spec) else None
    return [_apply_value(req, ctx, spec, value_for(spec, "OVER_MAX"), note)]


@register_operator("UNDER_MIN")
def op_under_min(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """低于 minimum / minLength。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "UNDER_MIN"))]


@register_operator("INVALID_ENUM")
def op_invalid_enum(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """枚举外取值：UNKNOWN，若 UNKNOWN 已在枚举里则 __INVALID__。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "INVALID_ENUM"))]


@register_operator("INVALID_FORMAT")
def op_invalid_format(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """按 format 给固定非法样例（email/date/uuid/uri）。"""
    spec = _require_spec(ctx)
    return [_apply_value(req, ctx, spec, value_for(spec, "INVALID_FORMAT"))]


# --------------------------------------------------------------------------- 请求头算子


@register_operator("REMOVE_HEADER")
def op_remove_header(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """删除指定头，默认 Content-Type。

    JSON 请求体删掉 Content-Type 后，httpx 走 ``json=`` 仍会补回 application/json——
    trace 里标注这一点，避免把「实际没删掉」当成有效结论。
    """
    name = ctx.rule.target_field or DEFAULT_HEADER_TARGET
    key = _find_header_key(req.headers, name)
    before = req.headers.get(key) if key else None
    if key is None:
        ctx.notes.append(f"基线无 {name} 头，无对比意义")
        return [MutationTraceEntry("REMOVE_HEADER", "HEADER", name, None, None, note="基线无此头")]
    req.headers.pop(key, None)
    note = None
    if name.lower() == "content-type" and req.json_body is not None:
        note = "JSON 请求体下 httpx 仍会补 application/json，结果可能无法区分"
    return [MutationTraceEntry("REMOVE_HEADER", "HEADER", key, before, None, note)]


@register_operator("EMPTY_HEADER")
def op_empty_header(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """头值改空串，默认 Content-Type。"""
    name = ctx.rule.target_field or DEFAULT_HEADER_TARGET
    key = _find_header_key(req.headers, name)
    before = req.headers.get(key) if key else None
    if key is None:
        ctx.notes.append(f"基线无 {name} 头，无对比意义")
        return [MutationTraceEntry("EMPTY_HEADER", "HEADER", name, None, None, note="基线无此头")]
    req.headers[key] = ""
    return [MutationTraceEntry("EMPTY_HEADER", "HEADER", key, before, "")]


@register_operator("INVALID_HEADER_VALUE")
def op_invalid_header_value(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """非鉴权头值改为 ``invalid``；鉴权头走认证类算子。"""
    name = ctx.rule.target_field or DEFAULT_HEADER_TARGET
    if name.lower() == ctx.auth_header.lower():
        raise RuleNotApplicableError(
            f"{name} 是鉴权头，请用认证类算子（REMOVE_TOKEN 等）",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    key = _find_header_key(req.headers, name)
    before = req.headers.get(key) if key else None
    if key is None:
        ctx.notes.append(f"基线无 {name} 头，无对比意义")
        return [MutationTraceEntry("INVALID_HEADER_VALUE", "HEADER", name, None, None,
                                   note="基线无此头")]
    req.headers[key] = "invalid"
    return [MutationTraceEntry("INVALID_HEADER_VALUE", "HEADER", key, before, "invalid")]


@register_operator("CONTENT_TYPE_MUTATION")
def op_content_type_mutation(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """Content-Type 改为 text/plain，请求体以原始 JSON 文本发送。

    必须走 ``raw_body``：httpx 走 ``json=`` 时会把 Content-Type 改回
    application/json，变异就白做了（§6.4 风险项）。
    """
    if req.json_body is None:
        raise RuleNotApplicableError(
            "基线没有 JSON 请求体，无法做 Content-Type 变异",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    key = _find_header_key(req.headers, "Content-Type") or "Content-Type"
    before = req.headers.get(key)
    raw = json.dumps(req.json_body, ensure_ascii=False, separators=(",", ":"))
    req.headers[key] = CONTENT_TYPE_TARGET
    req.content_type = CONTENT_TYPE_TARGET
    req.json_body = None
    req.raw_body = raw
    return [MutationTraceEntry(
        "CONTENT_TYPE_MUTATION", "HEADER", "Content-Type", before, CONTENT_TYPE_TARGET,
        note="请求体以原始 JSON 文本发送（raw_body），避免 httpx 改回 application/json",
    )]


# --------------------------------------------------------------------------- 方法算子


@register_operator("METHOD_MUTATION")
def op_method_mutation(req: Any, ctx: MutationContext) -> list[MutationTraceEntry]:
    """改方法：默认只测一个（POST→GET / GET→POST）；DELETE 必须已确认。"""
    original = (req.method or "").upper()
    methods = [str(m).upper() for m in ctx.rule.mutation_config.get("methods") or []]
    if methods:
        unknown = [m for m in methods if m not in HTTP_METHODS]
        if unknown:
            raise AppError(
                f"mutation_config.methods 含未开放的方法：{'/'.join(sorted(set(unknown)))}",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        target = next((m for m in methods if m != original), None)
    else:
        target = DEFAULT_METHOD_PAIR.get(original)
    if not target:
        raise RuleNotApplicableError(
            f"方法 {original} 没有默认的变异目标，请在 mutation_config.methods 里指定白名单",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    if target == "DELETE" and not (ctx.rule.confirmation_required and ctx.confirmed):
        raise ConfirmationRequiredError(
            "DELETE 方法变异属于高风险，需要规则标记 confirmation_required 且用例已确认",
            code=CODE_SECURITY_CONFIRMATION_REQUIRED,
        )
    req.method = target
    return [MutationTraceEntry("METHOD_MUTATION", "METHOD", "method", original, target)]
