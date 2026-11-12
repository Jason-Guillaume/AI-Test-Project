"""把平台接口契约（ApiInterface 等）导出为 OpenAPI 3.0.3 文档（Phase C）。

ZAP 的 OpenAPI Support 组件吃标准 3.0 文档，用它来「让 ZAP 知道有哪些接口」，
而不是靠爬虫去撞。导出过程严格遵守 §三十四：

- **只输出一个 servers 条目**，值就是本次任务的授权扫描根地址（SecurityScanTarget.base_url）。
  平台接口契约里没有 host，导出时也不会凭空生成任何外部 servers，因此 ZAP 不会
  依据文档去访问别的域名（「不允许扫描任意第三方网站」）。
- 契约描述里可能粘着真实 token（从 cURL 导入的 Authorization 头最典型）。
  导出前对 HEADER 位置的 Authorization / Cookie 参数丢弃 example 与 default，
  其余文本字段过一遍 JWT / 长随机串掩码，避免凭据进入上传给 ZAP 的文件。
- 只导出非弃用接口；条数上限可配，超限截断并在 info.description 里写明。

调用侧：Worker 在准备阶段调用 `build_openapi_document()`，把 JSON 文本交给
`connector.import_openapi()`。本模块不写库、不发网络请求。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.features.api_catalog.models import (
    ApiInterface,
    ApiParameter,
    ApiResponse,
    ApiRequestBody,
)

OPENAPI_VERSION = "3.0.3"
MAX_SCHEMA_DEPTH = 6
MAX_SCHEMA_NODES = 400
MAX_DOC_TEXT_LENGTH = 500
MAX_EXAMPLE_ITEMS = 64

# 从库里导入的契约偶尔带绝对地址或网关前缀；导出时统一收敛成相对路径。
_ABS_URL_RE = re.compile(r"^https?://[^/]+", re.IGNORECASE)
# JWT / 长期 token 形态：三段 base64 串，或单段足够长的随机串。
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}\b")
_LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9])")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9+/._=\-]{16,}")

_PARAM_IN_MAP = {
    "PATH": "path",
    "QUERY": "query",
    "HEADER": "header",
    "COOKIE": "cookie",
}

_OPENAPI_SCHEMA_KEYS = frozenset(
    {
        "type", "format", "description", "enum", "default", "example", "nullable",
        "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
        "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "pattern",
        "items", "properties", "required", "additionalProperties",
        "anyOf", "oneOf", "allOf", "not", "uniqueItems",
    }
)
_COMBINED_KEYS = ("anyOf", "oneOf", "allOf")

_TEXT_FIELDS = frozenset({"description", "summary", "example", "default", "name", "content"})

_TYPE_ALIASES = {
    "int": "integer", "int32": "integer", "int64": "integer", "long": "integer",
    "float": "number", "double": "number", "decimal": "number",
    "bool": "boolean", "byte": "string", "binary": "string",
    "list": "array", "dict": "object", "json": "object", "object": "object",
}


def _mask_tokens(text: str) -> str:
    """掩码 JWT 与长随机串；不改动普通业务文本。"""
    if not text:
        return text
    out = _JWT_RE.sub("[REDACTED]", text)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    out = _LONG_TOKEN_RE.sub("[REDACTED]", out)
    return out


def _text(value: Any, limit: int = MAX_DOC_TEXT_LENGTH) -> str:
    """把任意取值收敛成带掩码的字符串，超长截断。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    value = _mask_tokens(value.strip())
    return value[:limit]


def _norm_type(raw: Any) -> str:
    """参数类型归一：库里是自由文本（"Long"、"int64" 都会出现）。"""
    key = str(raw or "string").strip().lower()
    key = _TYPE_ALIASES.get(key, key)
    return key if key in {"string", "integer", "number", "boolean", "array", "object"} else "string"


def _coerce(value: Any, oas_type: str) -> Any:
    """把 example / default 的文本值按声明类型解释，避免给 ZAP 一份类型自相矛盾的定义。"""
    if value is None or isinstance(value, (int, float, bool, list, dict)):
        return value
    text = str(value).strip()
    if text == "" or text.startswith(("{", "[")):
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text
    if oas_type == "integer":
        try:
            return int(text)
        except (ValueError, TypeError):
            return text
    if oas_type == "number":
        try:
            return float(text)
        except (ValueError, TypeError):
            return text
    if oas_type == "boolean":
        low = text.lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        return text
    return text


def _schema_from_json(node: Any, depth: int = 0, budget: list[int] | None = None) -> dict:
    """把契约里的任意 JSON Schema 片段收敛成 OpenAPI 3 可接受的 schema。

    预算（MAX_SCHEMA_NODES / MAX_SCHEMA_DEPTH）防止一张畸形 schema 把导出文档撑爆。
    """
    if budget is None:
        budget = [MAX_SCHEMA_NODES]
    if budget[0] <= 0 or depth > MAX_SCHEMA_DEPTH:
        return {"type": "object"}
    budget[0] -= 1

    if isinstance(node, str):
        try:
            node = json.loads(node) if node.strip() else {}
        except (ValueError, TypeError):
            return {"type": "string"}
    if not isinstance(node, dict):
        return {"type": "string"} if isinstance(node, (str, int, float, bool)) else {"type": "object"}

    inner = node.get("schema")
    if isinstance(inner, dict):
        node = inner
    elif isinstance(inner, str) and inner.strip():
        try:
            loaded = json.loads(inner)
            if isinstance(loaded, dict):
                node = loaded
        except (ValueError, TypeError):
            pass

    clean: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _OPENAPI_SCHEMA_KEYS:
            continue
        if key in ("properties", "items", *_COMBINED_KEYS, "not"):
            continue
        clean[key] = _text(value, 300) if key in _TEXT_FIELDS else value
    if "type" in clean and clean["type"] not in {
        "string", "integer", "number", "boolean", "array", "object",
    }:
        clean["type"] = "object"

    for combined in _COMBINED_KEYS:
        branch = node.get(combined)
        if isinstance(branch, list) and branch:
            clean[combined] = [_schema_from_json(item, depth + 1, budget) for item in branch[:8]]

    properties = node.get("properties")
    if isinstance(properties, dict) and properties:
        clean["type"] = "object"
        clean["properties"] = {
            str(name): _schema_from_json(prop, depth + 1, budget)
            for name, prop in properties.items()
        }
        required = node.get("required")
        if isinstance(required, list) and required:
            clean["required"] = [str(item) for item in required][:64]

    items = node.get("items")
    if isinstance(items, (dict, list)) or isinstance(items, str):
        clean["type"] = "array"
        clean["items"] = _schema_from_json(items, depth + 1, budget)

    return clean or {"type": "object"}


def _masked_coerce(value: Any, oas_type: str) -> Any:
    """example / default 可能粘着真实令牌：先掩码，再按声明类型解释。"""
    return _coerce(_mask_tokens(value) if isinstance(value, str) else value, oas_type)


def _parameter_schema(param: ApiParameter) -> dict[str, Any]:
    """单个参数 → OpenAPI Parameter["schema"]。"""
    declared = _norm_type(param.type)
    schema = _schema_from_json(param.schema_json)
    if schema.get("type") in (None, "object") and declared not in ("object",) and "properties" not in schema:
        schema["type"] = declared
    if "enum" in schema:
        schema["enum"] = [
            _masked_coerce(item, schema.get("type", "string")) for item in schema["enum"][:32]
        ]
    if param.default_value:
        schema["default"] = _masked_coerce(param.default_value, schema.get("type", "string"))
    if param.example:
        schema["example"] = _masked_coerce(param.example, schema.get("type", "string"))
    return schema


#: 凭据类参数名：任何位置（HEADER / QUERY / COOKIE / PATH）都不导出示例值。
#: 只看参数名而不只看 HEADER 位置——token 走 query / cookie 传输同样会带真实凭据。
_SENSITIVE_PARAMETER_NAMES = frozenset({
    "authorization", "cookie", "x-api-key", "x-auth-token", "api-key", "apikey",
    "api_key", "token", "access_token", "refresh_token", "id_token",
    "password", "passwd", "secret", "signature", "sign",
    "session", "sessionid", "jsessionid", "sid", "csrf_token", "nonce",
})


def _is_sensitive_parameter(param: ApiParameter) -> bool:
    """判断参数是否是凭据载体：命中敏感名就丢弃示例值，参数本身仍保留。"""
    return str(param.name or "").strip().lower() in _SENSITIVE_PARAMETER_NAMES


def _parameter_to_openapi(param: ApiParameter) -> dict[str, Any] | None:
    """将参数转换为 OpenAPI 格式。"""
    param_in = _PARAM_IN_MAP.get(str(param.location or "").upper())
    if param_in is None:
        return None
    entry: dict[str, Any] = {
        "name": str(param.name or "").strip()[:100],
        "in": param_in,
        "schema": _parameter_schema(param),
    }
    if not entry["name"]:
        return None
    if param_in == "path":
        entry["required"] = True
    else:
        entry["required"] = bool(param.required)
    if _is_sensitive_parameter(param):
        # 保留参数本身（ZAP 才知道请求要带这个头或参数），但不给出任何示例值。
        entry["schema"] = {"type": "string"}
        entry["description"] = "敏感参数，示例值已省略"
    else:
        description = _text(param.description, 300)
        if description:
            entry["description"] = description
    return entry


def _request_body_schema(body: ApiRequestBody) -> tuple[str, dict[str, Any]]:
    """请求体 → (content_type, schema)。"""
    body_type = str(body.body_type or "none").strip().lower()
    declared = str(body.content_type or "").strip()
    if body_type == "json":
        return declared or "application/json", _schema_from_json(body.schema_json)
    if body_type in ("form", "multipart"):
        content_type = declared or (
            "multipart/form-data" if body_type == "multipart" else "application/x-www-form-urlencoded"
        )
        return content_type, _schema_from_json(body.schema_json)
    return declared or "text/plain", {"type": "string"}


def _normalize_path(path: Any) -> str:
    """收敛成 OpenAPI path 模板：相对、以 / 开头，只保留合法的 {param} 占位。"""
    text = str(path or "").strip()
    text = _ABS_URL_RE.sub("", text)
    if not text.startswith("/"):
        text = "/" + text
    text = text.split("?", 1)[0].split("#", 1)[0]
    while "//" in text:
        text = text.replace("//", "/")
    # 数据库里的路径写法不统一：:id、$id、[id] 都可能出现，统一成 {id}
    text = re.sub(r"[:$\[]([A-Za-z_][A-Za-z0-9_]*)(?=[/?&]|$)", r"{\1}", text)
    return text or "/"


def _interface_rows(db: Session, project_id: int) -> dict[int, ApiInterface]:
    """查询项目下的 API 接口记录。"""
    rows = (
        db.query(ApiInterface)
        .filter(ApiInterface.project_id == project_id, ApiInterface.status != "DEPRECATED")
        .order_by(ApiInterface.id.asc())
        .all()
    )
    return {row.id: row for row in rows}


def _parameters_for(db: Session, interface_id: int) -> list[ApiParameter]:
    """生成 OpenAPI 参数定义。"""
    return (
        db.query(ApiParameter)
        .filter(ApiParameter.interface_id == interface_id)
        .order_by(ApiParameter.location.asc(), ApiParameter.sort.asc(), ApiParameter.id.asc())
        .all()
    )


def _body_for(db: Session, interface_id: int) -> ApiRequestBody | None:
    """生成 OpenAPI 请求体定义。"""
    return db.query(ApiRequestBody).filter(ApiRequestBody.interface_id == interface_id).first()


def _responses_for(db: Session, interface_id: int) -> list[ApiResponse]:
    """生成 OpenAPI 响应定义。"""
    return (
        db.query(ApiResponse)
        .filter(ApiResponse.interface_id == interface_id)
        .order_by(ApiResponse.sort.asc(), ApiResponse.status_code.asc())
        .all()
    )


def _mask_example(value: Any, depth: int = 0) -> Any:
    """递归掩码响应示例里的令牌。

    契约的响应示例往往是真实抓包粘过来的，里面可能带着响应头回显出的 JWT。
    只掩码 JWT / 长随机串 / Bearer 形态，普通业务文本原样保留。
    """
    if depth > MAX_SCHEMA_DEPTH:
        return value
    if isinstance(value, dict):
        return {str(k): _mask_example(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_example(item, depth + 1) for item in value[:MAX_EXAMPLE_ITEMS]]
    if isinstance(value, str):
        return _mask_tokens(value)[:MAX_DOC_TEXT_LENGTH]
    return value


def _content_entry(schema: dict[str, Any], example_json: Any = None) -> dict[str, Any]:
    """单个 media type 的 content 条目。"""
    entry: dict[str, Any] = {"schema": schema}
    if example_json:
        if isinstance(example_json, str):
            try:
                example_json = json.loads(example_json)
            except (ValueError, TypeError):
                example_json = None
        if isinstance(example_json, (dict, list)):
            entry["example"] = _mask_example(example_json)
    return entry


def _response_object(
    schema: dict[str, Any],
    example_json: Any = None,
    media_type: str = "application/json",
) -> dict[str, Any]:
    """OpenAPI 3 的 Response Object。

    schema 必须包在 ``content`` 里才是合规的 Response Object——直接写
    ``{"200": {"schema": ...}}`` 在 OpenAPI 3.0 里是非法结构，ZAP OpenAPI Support
    会拒绝导入或按未知字段忽略掉整个响应定义。
    """
    return {
        "description": "标准响应",
        "content": {media_type: _content_entry(schema, example_json)},
    }


def build_openapi_document(
    db: Session,
    project_id: int,
    *,
    base_url: str,
    target_name: str = "",
    environment_name: str = "",
    max_interfaces: int = 500,
    only_active: bool = False,
) -> dict[str, Any]:
    """导出指定项目的接口契约为 OpenAPI 3.0.3 文档（dict 形式）。

    Args:
        base_url: 本次扫描的授权根地址，会成为唯一的 servers 条目。
        target_name: 扫描目标名称，写进 info，便于人工辨认这份文档属于哪次扫描。
        environment_name: 被测环境名，仅用于描述。
        max_interfaces: 导出条数上限；超限截断并在 info.description 中标明。
        only_active: True 时只导出 status=ACTIVE 的接口。
    """
    interfaces = _interface_rows(db, project_id)
    if only_active:
        interfaces = {i: r for i, r in interfaces.items() if str(r.status) == "ACTIVE"}
    ids = sorted(interfaces)
    truncated = len(ids) > max(1, int(max_interfaces))
    ids = ids[: max(1, int(max_interfaces))]

    paths: dict[str, dict[str, Any]] = {}
    for interface_id in ids:
        row = interfaces[interface_id]
        params = _parameters_for(db, interface_id)
        openapi_params = [p for p in (_parameter_to_openapi(p) for p in params) if p]
        path = _normalize_path(row.path)
        # path 占位符必须出现在 path 参数里，否则文档不自洽，ZAP 会拒绝导入。
        placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path))
        have_path = {str(p.get("name", "")) for p in openapi_params if p.get("in") == "path"}
        for name in sorted(placeholders - have_path):
            openapi_params.insert(0, {
                "name": name, "in": "path", "required": True, "schema": {"type": "string"},
            })

        responses: dict[str, dict[str, Any]] = {}
        for resp in _responses_for(db, interface_id):
            status = str(resp.status_code or 200)
            if not status.isdigit():
                status = "default"
            responses[status] = _response_object(_schema_from_json(resp.schema_json), resp.example_json)
        if not responses:
            responses["200"] = _response_object({"type": "object"})

        operation: dict[str, Any] = {
            "summary": _text(row.name, 200),
            "operationId": f"{str(row.method).upper().replace(' ', '')}_{row.id}",
        }
        if row.description:
            operation["description"] = _text(row.description, 400)
        if openapi_params:
            operation["parameters"] = openapi_params

        body = _body_for(db, interface_id)
        if body is not None:
            media_type, schema = _request_body_schema(body)
            content: dict[str, Any] = {"schema": schema}
            if body.raw_text:
                try:
                    content["example"] = _mask_example(json.loads(body.raw_text))
                except (ValueError, TypeError):
                    content["example"] = _text(body.raw_text, 300)
            operation["requestBody"] = {
                "description": "请求体（示例值已脱敏）",
                "required": True,
                "content": {media_type: content},
            }

        operation["responses"] = responses
        method = str(row.method or "GET").strip().lower()
        if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
            method = "post" if method else "get"
        item = paths.setdefault(path, {})
        item[method] = operation

    description_parts = [
        f"由平台接口契约导出，供 ZAP OpenAPI Support 使用。扫描范围仅限授权的测试环境目标。",
    ]
    if target_name:
        description_parts.append(f"扫描目标：{target_name}")
    if environment_name:
        description_parts.append(f"被测环境：{environment_name}")
    if truncated:
        description_parts.append(
            f"接口数量超出上限 {max_interfaces}，仅导出前 {len(ids)} 个（ID 升序）。"
        )

    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": f"{target_name or 'API'} 安全扫描接口契约",
            "version": "1.0.0",
            "description": " ".join(description_parts),
        },
        # 只保留授权目标的 server；契约里没有 host 信息，也不会新增任何外部 servers。
        "servers": [{"url": str(base_url or "").rstrip("/") or "/"}],
        "paths": paths,
    }


def render_openapi_json(document: dict[str, Any]) -> str:
    """序列化给 ZAP 上传的 JSON 文本（稳定排序，便于比对与缓存）。"""
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def count_interfaces(document: dict[str, Any]) -> int:
    """统计文档中的接口条数（用于日志与计划预览）。"""
    return sum(len(item) for item in (document.get("paths") or {}).values())
