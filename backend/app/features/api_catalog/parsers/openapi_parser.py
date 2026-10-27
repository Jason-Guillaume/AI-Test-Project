"""OpenAPI 3.x / Swagger 2.0 解析器：JSON/YAML → list[InternalApiSchema]。

yaml.safe_load 兼容 JSON 与 YAML（JSON 是 YAML 子集），不执行任意对象，安全。
区分版本：spec 含 ``openapi`` 字段为 3.x；含 ``swagger`` 字段为 2.0。
$ref（#/definitions/X、#/components/schemas/X、#/parameters/X、#/responses/X）递归内联，
带环检测（visited 集合），避免自引用无限递归。

3.x：遍历 paths.{path}.{method}，summary/operationId→name，tags→tags，parameters(in:path/query/
header/cookie)，requestBody.content.{ct}.schema→body，responses.{code}→response。
2.0：paths.{path}.{method}，parameters(in:path/query/header/formData/body)，responses，
definitions/responses/parameters 解引用。consumes/produces 决定 content-type。

本解析器只产 InternalApiSchema 列表，不判定模块归属（ModuleResolver 负责），但写入
suggested_module（URL 路径推断纯函数）供预览与 ModuleResolver 第 5 优先级复用。
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from app.features.api_catalog.schemas import (
    HTTP_METHODS,
    InternalApiSchema,
    InternalBody,
    InternalParameter,
    InternalResponse,
)
from app.features.api_catalog.services.module_resolver import infer_module_name_from_path

_HTTP_METHOD_KEYS = ("get", "post", "put", "patch", "delete", "head", "options")
# 路径参数 {var} 与 swagger 的 {var} 风格统一；不支持 :var。
_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_]\w*)\}")


def parse_openapi(content: str) -> list[InternalApiSchema]:
    """解析 OpenAPI3/Swagger2 文本为 InternalApiSchema 列表。"""
    if not content or not content.strip():
        raise ValueError("OpenAPI/Swagger 内容为空")
    try:
        spec = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML/JSON 解析失败：{exc}") from exc
    if not isinstance(spec, dict):
        raise ValueError("OpenAPI/Swagger 顶层必须是映射对象")

    is_swagger2 = "swagger" in spec
    is_openapi3 = "openapi" in spec
    if not (is_swagger2 or is_openapi3):
        if isinstance(spec.get("info"), dict) and "item" in spec:
            raise ValueError("该文件是 Postman Collection，暂不支持导入；请使用 OpenAPI 或 Swagger 文档")
        raise ValueError("缺少 openapi/swagger 版本字段，无法识别文档类型")

    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        raise ValueError("paths 字段必须是映射对象")

    results: list[InternalApiSchema] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_level_params = path_item.get("parameters") or []
        for method in _HTTP_METHOD_KEYS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            schema = _build_operation(spec, path, method, operation, path_level_params, swagger2=is_swagger2)
            results.append(schema)
    return results


# ----------------------------------------------------------------------------- 单个操作


def _build_operation(
    spec: dict,
    path: str,
    method: str,
    operation: dict,
    path_level_params: list,
    *,
    swagger2: bool,
) -> InternalApiSchema:
    """由一个 operation 节构造 InternalApiSchema。"""
    name = (
        operation.get("operationId")
        or operation.get("summary")
        or f"{method.upper()} {path}"
    )
    description = operation.get("description") or operation.get("summary")
    tags = [str(t) for t in operation.get("tags") or [] if t]

    raw_params = list(path_level_params) + list(operation.get("parameters") or [])
    parameters = _build_parameters(spec, raw_params, path)

    body = _build_body(spec, operation, swagger2=swagger2)
    responses = _build_responses(spec, operation.get("responses") or {}, swagger2=swagger2)

    content_type = _infer_content_type(operation, body, swagger2=swagger2)

    return InternalApiSchema(
        name=str(name)[:200],
        description=str(description)[:1000] if description else None,
        method=method.upper(),
        path=path,
        auth_type=_infer_auth_type(spec, operation, swagger2=swagger2),
        content_type=content_type,
        parameters=parameters,
        body=body,
        responses=responses,
        tags=tags,
        suggested_module=infer_module_name_from_path(path),
        source_type="SWAGGER" if swagger2 else "OPENAPI",
    )


def _build_parameters(
    spec: dict, raw_params: list, path: str,
) -> list[InternalParameter]:
    """组装参数列表（PATH/QUERY/HEADER/COOKIE）。"""
    # 路径里出现的参数名必须标记为 PATH 且 required。
    path_param_names = set(_PATH_PARAM_RE.findall(path))
    out: list[InternalParameter] = []
    seen: set[tuple[str, str]] = set()
    sort = 0
    for raw in raw_params:
        param = _inline(spec, raw, _visited())
        if not isinstance(param, dict):
            continue
        location = _map_location(param.get("in"))
        if location is None:
            continue
        name = str(param.get("name") or "").strip()
        if not name:
            continue
        if location == "PATH":
            name = name
        key = (location, name)
        if key in seen:
            continue
        seen.add(key)
        schema_node = param.get("schema") if param.get("schema") is not None else param
        schema_node = _inline(spec, schema_node, _visited()) if isinstance(schema_node, dict) else schema_node
        ptype, pinfo = _schema_type_info(schema_node)
        required = bool(param.get("required")) or (name in path_param_names)
        example = param.get("example")
        if example is None and isinstance(schema_node, dict):
            example = schema_node.get("example") or schema_node.get("default")
        out.append(InternalParameter(
            name=name,
            location=location,
            type=ptype,
            required=required,
            description=str(param.get("description")) if param.get("description") else None,
            example=None if example is None else (str(example) if not isinstance(example, str) else example),
            default_value=str(schema_node.get("default")) if isinstance(schema_node, dict) and schema_node.get("default") is not None else None,
            schema_json=pinfo,
            sort=sort,
        ))
        sort += 1
    # 兜底：路径声明了 {id} 但 parameters 里缺该 PATH 参数，补一条占位。
    declared = {(p.location, p.name) for p in out}
    for pname in path_param_names:
        if ("PATH", pname) not in declared:
            out.append(InternalParameter(
                name=pname, location="PATH", type="string", required=True, sort=sort,
            ))
            sort += 1
    return out


def _map_location(loc: Any) -> str | None:
    """openapi in → 内部 location；body/formData 由 body 通道处理，此处忽略。"""
    if loc == "path":
        return "PATH"
    if loc == "query":
        return "QUERY"
    if loc == "header":
        return "HEADER"
    if loc == "cookie":
        return "COOKIE"
    # swagger2 的 formData / body 不作为参数，交给 _build_body。
    return None


def _build_body(spec: dict, operation: dict, *, swagger2: bool) -> InternalBody:
    """构造请求体：3.x 走 requestBody.content；2.0 走 parameters(formData/body)+consumes。"""
    if swagger2:
        return _build_body_swagger2(spec, operation)
    return _build_body_openapi3(spec, operation)


def _build_body_openapi3(spec: dict, operation: dict) -> InternalBody:
    """构建请求体`openapi`。"""
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return InternalBody(body_type="none")
    request_body = _inline(spec, request_body, _visited())
    content = request_body.get("content") if isinstance(request_body, dict) else None
    if not isinstance(content, dict) or not content:
        return InternalBody(body_type="none")
    # 优先 application/json，其次 multipart，再任意。
    ct_key = _pick_content_type(list(content.keys()))
    media = content.get(ct_key) or {}
    schema = _inline(spec, media.get("schema"), _visited())
    body_type = _content_type_to_body_type(ct_key)
    schema_json = _schema_to_info(schema) if schema is not None else None
    example = media.get("example") or (media.get("examples") or {}).get("example")
    raw_text = None
    if example is not None and body_type == "json":
        import json as _json
        try:
            raw_text = _json.dumps(example, ensure_ascii=False)
        except (TypeError, ValueError):
            raw_text = None
    return InternalBody(
        body_type=body_type,
        content_type=ct_key,
        schema_json=schema_json,
        raw_text=raw_text,
    )


def _build_body_swagger2(spec: dict, operation: dict) -> InternalBody:
    """构建请求体`swagger`。"""
    consumes = operation.get("consumes") or spec.get("consumes") or []
    ct = _pick_content_type(list(consumes)) if consumes else "application/json"
    params = operation.get("parameters") or []
    form_fields: list[dict] = []
    body_param: dict | None = None
    for raw in params:
        p = _inline(spec, raw, _visited())
        if not isinstance(p, dict):
            continue
        loc = p.get("in")
        if loc == "formData":
            form_fields.append(p)
        elif loc == "body":
            body_param = p
    if body_param is not None:
        schema = _inline(spec, body_param.get("schema"), _visited())
        return InternalBody(
            body_type="json",
            content_type=ct,
            schema_json=_schema_to_info(schema) if schema is not None else None,
            raw_text=None,
        )
    if form_fields:
        body_type = _content_type_to_body_type(ct)
        props: dict[str, dict] = {}
        for f in form_fields:
            fname = str(f.get("name") or "").strip()
            if not fname:
                continue
            ptype, pinfo = _schema_type_info(f)
            props[fname] = {**({"type": ptype} if ptype else {}), **(pinfo or {})}
        return InternalBody(
            body_type=body_type,
            content_type=ct,
            schema_json={"type": "object", "properties": props},
            raw_text=None,
        )
    return InternalBody(body_type="none")


def _build_responses(spec: dict, responses: dict, *, swagger2: bool) -> list[InternalResponse]:
    """组装响应列表（按 status_code）。"""
    out: list[InternalResponse] = []
    sort = 0
    for code, resp in responses.items():
        if not isinstance(resp, dict):
            continue
        resp = _inline(spec, resp, _visited())
        status_code = _parse_status_code(code)
        description = resp.get("description")
        schema_json = None
        example_json = None
        if swagger2:
            schema = _inline(spec, resp.get("schema"), _visited())
            if schema is not None:
                schema_json = _schema_to_info(schema)
            ex = resp.get("examples") or {}
            if isinstance(ex, dict) and ex:
                first = next(iter(ex.values()))
                if isinstance(first, dict) and first.get("value") is not None:
                    import json as _json
                    try:
                        example_json = _json.dumps(first.get("value"), ensure_ascii=False)
                    except (TypeError, ValueError):
                        example_json = None
        else:
            content = resp.get("content") or {}
            if isinstance(content, dict) and content:
                media = next(iter(content.values())) or {}
                schema = _inline(spec, media.get("schema"), _visited())
                if schema is not None:
                    schema_json = _schema_to_info(schema)
                ex = media.get("example")
                if ex is None:
                    exs = media.get("examples") or {}
                    if isinstance(exs, dict) and exs:
                        first = next(iter(exs.values()))
                        if isinstance(first, dict) and first.get("value") is not None:
                            ex = first.get("value")
                if ex is not None:
                    import json as _json
                    try:
                        example_json = _json.dumps(ex, ensure_ascii=False)
                    except (TypeError, ValueError):
                        example_json = None
        out.append(InternalResponse(
            status_code=status_code,
            description=str(description) if description else None,
            schema_json=schema_json,
            example_json=example_json,
            sort=sort,
        ))
        sort += 1
    if not out:
        out.append(InternalResponse(status_code=200, description="默认成功响应", sort=0))
    return out


# ----------------------------------------------------------------------------- $ref 内联


def _visited() -> set[str]:
    """检查并记录已经处理的 OpenAPI schema 节点，避免循环引用。"""
    return set()


def _inline(spec: dict, node: Any, visited: set[str]) -> Any:
    """递归内联 $ref，带环检测。返回内联后的纯数据（dict/list/标量）。"""
    if node is None:
        return None
    if isinstance(node, list):
        return [_inline(spec, item, visited) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if ref is not None:
        if not isinstance(ref, str):
            return node
        if ref in visited:
            # 环：返回占位，停止递归，避免无限展开。
            return {"$ref": ref, "cycle": True}
        target = _resolve_ref(spec, ref)
        if target is None:
            return {"$ref": ref, "unresolved": True}
        visited2 = visited | {ref}
        return _inline(spec, target, visited2)
    # 普通对象：递归内联其值。
    return {k: _inline(spec, v, visited) for k, v in node.items()}


def _resolve_ref(spec: dict, ref: str) -> Any:
    """解析 #/a/b/c 形式的本地引用。"""
    if not ref.startswith("#/"):
        return None
    cur: Any = spec
    for seg in ref[2:].split("/"):
        seg = seg.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            return None
    return cur


# ----------------------------------------------------------------------------- 辅助


def _schema_type_info(schema_node: Any) -> tuple[str, dict | None]:
    """从 schema 节点取 (type, info_json)。info_json 含 format/enum/items 等。"""
    if not isinstance(schema_node, dict):
        return "string", None
    stype = schema_node.get("type") or _infer_type_from_schema(schema_node)
    info: dict = {}
    for key in ("format", "enum", "pattern", "minimum", "maximum", "minLength", "maxLength",
                "minItems", "maxItems", "default", "items", "properties", "required"):
        if key in schema_node:
            info[key] = schema_node[key]
    return stype or "string", (info or None)


def _schema_to_info(schema_node: Any) -> dict | None:
    """把内联后的 schema 节点整体作为 schema_json 返回（保留结构）。"""
    if schema_node is None:
        return None
    return schema_node if isinstance(schema_node, dict) else {"value": schema_node}


def _infer_type_from_schema(schema: dict) -> str | None:
    """无显式 type 时按结构推断。"""
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    if "enum" in schema:
        return "string"
    return None


def _content_type_to_body_type(ct: str) -> str:
    """content-type → 内部 body_type。"""
    low = (ct or "").lower()
    if "application/json" in low or "+json" in low:
        return "json"
    if "multipart/form-data" in low:
        return "multipart"
    if "x-www-form-urlencoded" in low:
        return "form"
    return "raw"


def _pick_content_type(keys: list[str]) -> str:
    """从若干 content-type 里挑一个：优先 json，其次表单，再任意。"""
    lower = [k.lower() for k in keys]
    for pref in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data"):
        for i, k in enumerate(lower):
            if pref in k:
                return keys[i]
    return keys[0] if keys else "application/json"


def _infer_content_type(operation: dict, body: InternalBody, *, swagger2: bool) -> str:
    """接口级 content_type：取 body 的；无则 application/json。"""
    if body.body_type != "none" and body.content_type:
        return body.content_type
    return "application/json"


def _infer_auth_type(spec: dict, operation: dict, *, swagger2: bool) -> str:
    """由 security schemes 简单推断 auth_type；无则 none。"""
    security = operation.get("security")
    if security is None:
        security = spec.get("security")
    if not security or not isinstance(security, list):
        return "none"
    schemes = spec.get("securityDefinitions" if swagger2 else "components", {})
    if not swagger2 and isinstance(schemes, dict):
        schemes = schemes.get("securitySchemes") or {}
    first = security[0] if isinstance(security[0], dict) else {}
    if not isinstance(first, dict) or not first:
        return "none"
    scheme_name = next(iter(first.keys()))
    scheme = schemes.get(scheme_name) if isinstance(schemes, dict) else None
    if not isinstance(scheme, dict):
        return "custom"
    stype = scheme.get("type")
    if stype == "http":
        return scheme.get("scheme") or "none"
    if stype == "apiKey":
        return "apikey"
    if stype in ("oauth2", "openIdConnect"):
        return "oauth2"
    return "custom"


def _parse_status_code(code: Any) -> int:
    """状态码：数字直接取；'default'→0；'2XX'→ 取首位补齐为具体码无法，落 0。"""
    if isinstance(code, int):
        return code
    s = str(code).strip()
    if s.isdigit():
        return int(s)
    if s.lower() == "default":
        return 0
    # 形如 "2XX"：无法确定具体码，用 0 占位。
    return 0


__all__ = ["parse_openapi"]
