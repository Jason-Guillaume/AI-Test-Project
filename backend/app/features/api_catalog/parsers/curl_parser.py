"""Curl 命令解析器：单条 curl → InternalApiSchema。

使用 shlex 切词，识别 -X/--request、-H/--header、-d/--data/--data-raw/--data-binary、
--data-urlencode、-F/--form、-b/--cookie、-u/--user 与 URL 位置参数。
URL 拆 base_url/path/query；从路径模板 {id}/:id 识别 PATH 参数；query 识别 QUERY 参数。
JSON body 尝试 json.loads 生成 schema_json；form/multipart 按字段拆。

敏感值脱敏（spec §3）：Authorization/Token/Cookie/Set-Cookie/API-Key 等不直接保存真实值，
转成变量占位（如 ``Bearer ${token}``、``${cookie}``），schema_json 标注 ``sensitive:true``，
使导入预览/确认均不落库真实凭证。

本解析器只产 InternalApiSchema，不判定模块归属（ModuleResolver 负责），但会写入
suggested_module（由 URL 路径推断的纯函数），供预览展示与 ModuleResolver 第 5 优先级复用。
"""

from __future__ import annotations

import json
import re
import shlex
from urllib.parse import parse_qsl, unquote, urlsplit

from app.features.api_catalog.schemas import (
    HTTP_METHODS,
    InternalApiSchema,
    InternalBody,
    InternalParameter,
    InternalResponse,
)
from app.features.api_catalog.services.module_resolver import infer_module_name_from_path

# 敏感 header 名集合（小写）：值不直接落库，转变量占位。
_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization", "token", "cookie", "set-cookie",
        "x-api-key", "api-key", "x-auth-token", "x-token", "x-access-token",
        "proxy-authorization",
    }
)
# 这些 header 不作为 HEADER 参数落库（Cookie 路由到 COOKIE 参数，Content-Type 进 body）。
_CONSUMED_HEADERS: frozenset[str] = frozenset(
    {"cookie", "content-type", "content-length", "host"}
)
# 路径模板参数：{name} 与 :name（name 为字母/下划线起头）。
_PATH_TEMPLATE_BRACE = re.compile(r"\{([A-Za-z_]\w*)\}")
_PATH_TEMPLATE_COLON = re.compile(r"(^|/):([A-Za-z_]\w*)")


def parse_curl(curl_text: str) -> InternalApiSchema:
    """解析单条 curl 命令为 InternalApiSchema。"""
    text = _preprocess(curl_text)
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as exc:
        raise ValueError(f"curl 解析失败：{exc}") from exc

    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]
    if not tokens:
        raise ValueError("curl 命令为空或无法解析")

    parsed = _scan_tokens(tokens)

    if not parsed.url:
        raise ValueError("curl 命令缺少请求 URL")

    schema = _build_schema(parsed)
    return schema


# ----------------------------------------------------------------------------- 内部结构


class _Parsed:
    """curl 扫描中间结果。"""

    def __init__(self) -> None:
        self.method: str = "GET"
        self.url: str = ""
        self.headers: list[tuple[str, str]] = []
        self.raw_body: str | None = None
        self.form_fields: list[tuple[str, str]] = []
        self.multipart_fields: list[tuple[str, str]] = []
        self.multipart_files: set[str] = set()
        self.cookies: dict[str, str] = {}
        self.basic_user: str | None = None
        self.has_get_flag: bool = False


def _preprocess(curl_text: str) -> str:
    """合并反斜杠行续接，去首尾空白。"""
    text = (curl_text or "").strip()
    # shell 行续接：反斜杠 + 换行 → 空格
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    # 单独的尾部反斜杠（行末续接在最后一行）也清掉
    text = text.replace("\\\r", " ")
    return text


def _split_opt(tok: str) -> tuple[str, str | None]:
    """拆分 --opt=value 形式，返回 (opt, inline_value_or_None)。"""
    if tok.startswith("--") and "=" in tok:
        opt, _, val = tok.partition("=")
        return opt, val
    return tok, None


def _scan_tokens(tokens: list[str]) -> _Parsed:
    """遍历 curl 选项，收集到 _Parsed。

    选项值两种形式：inline（-XPOST / -H'Name: v'）与独立参数（-X POST / -H 'Name: v'）。
    后者必须跳过紧跟的值 token，否则该值会被当成位置参数误判为 URL（如 -X POST 中
    POST 抢占 URL，真正的 https://… 被丢弃）。
    """
    state = _Parsed()
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]
        opt, inline = _split_opt(tok)
        # step：本轮前进多少 token。消费了独立值的选项 step=2，否则 1。
        step = 1

        def take(opt_name: str) -> str:
            """取选项值：inline 优先，否则取下一 token 并标记 step=2。"""
            nonlocal step
            if inline is not None:
                return inline
            if i + 1 >= n:
                raise ValueError(f"curl 选项 {opt_name} 缺少参数")
            step = 2
            return tokens[i + 1]

        if opt in ("-X", "--request"):
            state.method = take(opt).upper()
        elif opt in ("-H", "--header"):
            state.headers.append(_parse_header(take(opt)))
        elif opt in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii"):
            chunk = take(opt)
            # @file 形式无法读取本地文件，跳过并保留提示。
            if not chunk.startswith("@"):
                state.raw_body = (state.raw_body or "") + chunk
        elif opt == "--data-urlencode":
            state.form_fields.extend(_parse_urlencode(take(opt)))
        elif opt in ("-F", "--form"):
            k, v, is_file = _parse_form_field(take(opt))
            if is_file:
                state.multipart_files.add(k)
            state.multipart_fields.append((k, v))
        elif opt in ("-b", "--cookie"):
            state.cookies.update(_parse_cookie(take(opt)))
        elif opt in ("-u", "--user"):
            state.basic_user = take(opt)
        elif opt == "--url":
            state.url = take(opt)
        elif opt in ("-A", "--user-agent", "-e", "--referer", "-o", "--output",
                     "--connect-timeout", "--max-time", "--retry", "-w", "--write-out",
                     "--resolve", "--interface", "--proxy", "-x", "--cert", "--key",
                     "--cacert", "-E", "--cert-type", "--capath", "--crlfile"):
            # 值选项但与接口结构无关：消费其参数，忽略。
            if inline is None:
                step = 2
        elif opt == "-G":
            state.has_get_flag = True
        elif opt in ("-k", "--insecure", "-s", "--silent", "-S", "--show-error",
                     "-L", "--location", "-i", "--include", "--compressed", "-f",
                     "--fail", "-v", "--verbose", "-n", "--netrc", "--noproxy",
                     "--http1.1", "--http2", "--http3", "-I", "--head"):
            # 布尔开关：忽略。
            pass
        elif opt.startswith("-"):
            # 未知选项：保守忽略（避免误判为 URL）。
            pass
        else:
            # 位置参数：首个非选项视为 URL。
            if not state.url:
                state.url = tok
        i += step

    if state.has_get_flag:
        state.method = "GET"
    return state


def _parse_header(raw: str) -> tuple[str, str]:
    """拆 'Name: value' → (name, value)；无冒号返回 (raw, '')。"""
    if ":" in raw:
        name, _, value = raw.partition(":")
        return name.strip(), value.strip()
    return raw.strip(), ""


def _parse_urlencode(chunk: str) -> list[tuple[str, str]]:
    """--data-urlencode：支持 name=content / content / name@file / @file。"""
    if "=" in chunk:
        name, _, content = chunk.partition("=")
        return [(unquote(name), content)]
    if "@" in chunk and not chunk.startswith("@"):
        name, _, _ = chunk.partition("@")
        return [(unquote(name), "<file>")]
    return [("_", unquote(chunk))]


def _parse_form_field(chunk: str) -> tuple[str, str, bool]:
    """-F key=value / key=@file / key=<file → (key, value, is_file)。"""
    if "=" in chunk:
        key, _, value = chunk.partition("=")
        key = key.strip()
        # value 可能带 ;type=... 修饰，取分号前为主值。
        if ";" in value:
            value = value.split(";", 1)[0]
        is_file = value.startswith("@") or value.startswith("<")
        clean = value[1:] if is_file else value
        return key, clean, is_file
    if "@" in chunk:
        key, _, _ = chunk.partition("@")
        return key.strip(), "", True
    return chunk.strip(), "", False


def _parse_cookie(raw: str) -> dict[str, str]:
    """拆 'a=1; b=2' → {a:1,b:2}。"""
    out: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
        else:
            out[part] = ""
    return out


def _build_schema(state: _Parsed) -> InternalApiSchema:
    """由扫描结果构造 InternalApiSchema。"""
    url = state.url
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    raw_path = parts.path or "/"
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)

    # 路径模板归一：:id → {id}，并提取 PATH 参数。
    path, path_params = _normalize_path_and_params(raw_path)

    content_type = _header_value(state.headers, "content-type")
    cookie_header = _header_value(state.headers, "cookie")

    # Cookie 来源合并：-b 与 -H 'Cookie: ...'。
    cookies: dict[str, str] = {}
    if cookie_header:
        cookies.update(_parse_cookie(cookie_header))
    cookies.update(state.cookies)

    parameters = _build_parameters(state, path_params, query_pairs, cookies)
    body = _build_body(state, content_type)
    responses = _default_responses()

    # basic 鉴权若无 Authorization header，补一条脱敏的 Authorization 参数。
    auth_type = "none"
    auth_header_present = any(h[0].lower() == "authorization" for h in state.headers)
    if auth_header_present:
        auth_type = _infer_auth_type(state.headers)
    elif state.basic_user:
        parameters.append(_masked_header_param("Authorization", f"Basic {state.basic_user}"))
        auth_type = "basic"

    method = state.method.upper()
    if method not in HTTP_METHODS:
        # 非标准方法保留原值，由服务层决定是否拒绝。
        method = state.method.upper() or "GET"

    name = f"{method} {path}"
    return InternalApiSchema(
        name=name,
        description=None,
        method=method,
        path=path,
        auth_type=auth_type,
        content_type=content_type or (body.content_type or "application/json"),
        parameters=parameters,
        body=body,
        responses=responses,
        tags=[],
        suggested_module=infer_module_name_from_path(path),
        source_type="CURL",
    )


def _normalize_path_and_params(raw_path: str) -> tuple[str, list[str]]:
    """:id → {id} 归一；返回 (normalized_path, param_names 顺序去重)。"""
    # 先提取 :name 参数（在替换前）。
    colon_params = [m.group(2) for m in _PATH_TEMPLATE_COLON.finditer(raw_path)]
    normalized = _PATH_TEMPLATE_COLON.sub(lambda m: f"{m.group(1)}{{{m.group(2)}}}", raw_path)
    brace_params = [m.group(1) for m in _PATH_TEMPLATE_BRACE.finditer(normalized)]
    # 合并去重保序。
    seen: set[str] = set()
    params: list[str] = []
    for p in colon_params + brace_params:
        if p not in seen:
            seen.add(p)
            params.append(p)
    return normalized, params


def _header_value(headers: list[tuple[str, str]], name: str) -> str | None:
    """取首个指定 header 的值（大小写不敏感）。"""
    lower = name.lower()
    for h_name, h_value in headers:
        if h_name.lower() == lower:
            return h_value
    return None


def _build_parameters(
    state: _Parsed,
    path_params: list[str],
    query_pairs: list[tuple[str, str]],
    cookies: dict[str, str],
) -> list[InternalParameter]:
    """组装 PATH/QUERY/HEADER/COOKIE 参数。"""
    params: list[InternalParameter] = []
    sort = 0
    for name in path_params:
        params.append(InternalParameter(
            name=name, location="PATH", type="string", required=True,
            description=None, sort=sort,
        ))
        sort += 1
    for name, value in query_pairs:
        params.append(InternalParameter(
            name=name, location="QUERY", type="string", required=False,
            example=value, sort=sort,
        ))
        sort += 1
    for h_name, h_value in state.headers:
        lower = h_name.lower()
        if lower in _CONSUMED_HEADERS:
            continue
        if lower in _SENSITIVE_HEADERS:
            params.append(_masked_header_param(h_name, h_value, sort=sort))
        else:
            params.append(InternalParameter(
                name=h_name, location="HEADER", type="string", required=False,
                example=h_value, sort=sort,
            ))
        sort += 1
    for name, value in cookies.items():
        # Cookie 一律不落库真实值：example 写占位串（调试/用例侧再填真值）。
        # 否则 sessionid / JSESSIONID 这类真实会话值会经 api_parameter.example 明文入库，
        # 并被 get_interface 详情原样回给项目内任意成员；而 schema_json 的 sensitive 标记
        # 全仓库无人消费，纯属装饰。
        params.append(InternalParameter(
            name=name, location="COOKIE", type="string", required=False,
            example="${cookie}", schema_json={"sensitive": True} if _looks_sensitive_cookie(name) else None,
            sort=sort,
        ))
        sort += 1
    return params


def _looks_sensitive_cookie(name: str) -> bool:
    """会话类 cookie 名视作敏感。"""
    low = (name or "").lower()
    return any(k in low for k in ("session", "token", "sid", "auth", "jwt", "csrf"))


def _masked_header_param(name: str, value: str, *, sort: int = 0) -> InternalParameter:
    """构造脱敏后的 HEADER 参数：保留方案前缀，值转变量占位。"""
    lower = name.lower()
    if lower == "authorization":
        masked = _mask_authorization(value)
    elif lower in ("cookie", "set-cookie"):
        masked = "${cookie}"
    else:
        var = lower.replace("-", "_")
        masked = f"${{{var}}}"
    return InternalParameter(
        name=name, location="HEADER", type="string", required=False,
        example=masked, schema_json={"sensitive": True}, sort=sort,
    )


def _mask_authorization(value: str) -> str:
    """Authorization 脱敏：Bearer xxx → Bearer ${token}；其它 → ${authorization}。"""
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].lower() in {"bearer", "basic", "digest", "negotiate", "ntlm"}:
        return f"{parts[0]} ${{token}}"
    return "${authorization}"


def _infer_auth_type(headers: list[tuple[str, str]]) -> str:
    """由 Authorization 头推断 auth_type。"""
    raw = _header_value(headers, "authorization") or ""
    low = raw.lower()
    if low.startswith("bearer"):
        return "bearer"
    if low.startswith("basic"):
        return "basic"
    if low.startswith("digest"):
        return "digest"
    return "apikey"


def _build_body(state: _Parsed, content_type: str | None) -> InternalBody:
    """根据原始 body / 表单 / multipart / content-type 决定请求体。"""
    ct = (content_type or "").lower()
    raw = state.raw_body

    if raw is not None and not raw.startswith("@"):
        if "application/json" in ct or _looks_json(raw):
            schema_json = _json_schema_from_raw(raw)
            return InternalBody(
                body_type="json",
                content_type=ct or "application/json",
                schema_json=schema_json,
                raw_text=raw,
            )
        if "multipart/form-data" in ct:
            return InternalBody(
                body_type="multipart",
                content_type="multipart/form-data",
                schema_json=_multipart_schema(state),
                raw_text=None,
            )
        if "x-www-form-urlencoded" in ct or _looks_form(raw):
            fields = state.form_fields or parse_qsl(raw, keep_blank_values=True)
            return InternalBody(
                body_type="form",
                content_type=ct or "application/x-www-form-urlencoded",
                schema_json=_form_schema(fields),
                raw_text=raw,
            )
        return InternalBody(
            body_type="raw",
            content_type=ct or "text/plain",
            schema_json=None,
            raw_text=raw,
        )

    if state.multipart_fields:
        return InternalBody(
            body_type="multipart",
            content_type="multipart/form-data",
            schema_json=_multipart_schema(state),
            raw_text=None,
        )
    if state.form_fields:
        return InternalBody(
            body_type="form",
            content_type="application/x-www-form-urlencoded",
            schema_json=_form_schema(state.form_fields),
            raw_text=None,
        )
    return InternalBody(body_type="none")


def _looks_json(raw: str) -> bool:
    s = raw.lstrip()
    return s.startswith("{") or s.startswith("[")


def _looks_form(raw: str) -> bool:
    s = raw.strip()
    if not s or s[0] in "{[":
        return False
    return "=" in s


def _json_schema_from_raw(raw: str) -> dict | None:
    """尝试 json.loads，成功则返回 {example: <parsed>}；失败返回 None。"""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return {"example": parsed}


def _form_schema(fields: list[tuple[str, str]]) -> dict:
    """表单字段 → {properties: {name: {type:string, example: val}}}。"""
    props: dict[str, dict] = {}
    for name, value in fields:
        if name == "_":
            continue
        props[name] = {"type": "string", "example": value}
    return {"type": "object", "properties": props}


def _multipart_schema(state: _Parsed) -> dict:
    """multipart → {properties, files}。"""
    props: dict[str, dict] = {}
    for name, value in state.multipart_fields:
        entry: dict = {"type": "string", "example": value}
        if name in state.multipart_files:
            entry = {"type": "file"}
        props[name] = entry
    return {"type": "object", "properties": props, "files": sorted(state.multipart_files)}


def _default_responses() -> list[InternalResponse]:
    """curl 无响应信息，给一个占位 200 响应。"""
    return [InternalResponse(status_code=200, description="成功（curl 导入未携带响应结构）", sort=0)]


__all__ = ["parse_curl"]
