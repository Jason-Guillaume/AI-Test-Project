"""Postman Collection v2.0/v2.1 → InternalApiSchema。"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.features.api_catalog.schemas import (
    HTTP_METHODS,
    InternalApiSchema,
    InternalBody,
    InternalParameter,
    InternalResponse,
)
from app.features.api_catalog.services.module_resolver import infer_module_name_from_path

_PATH_PARAM_RE = re.compile(r"(^|/):([A-Za-z_]\w*)")
_DOUBLE_BRACE_RE = re.compile(r"\{\{([A-Za-z_]\w*)\}\}")
_SENSITIVE_NAME_RE = re.compile(
    r"(?:authorization|token|secret|password|passwd|credential|api.?key|"
    r"access.?key|private.?key|signature|cookie|session|jwt|client.?secret)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(\b(?:password|passwd|token|secret|api[_-]?key|client[_-]?secret)\b\s*[:=]\s*)"
    r"([\"']?)[^\s,;\"'}]+"
)


def is_postman_collection(document: Any) -> bool:
    """识别 Postman 导出的集合及 Postman API 的 collection 包装。"""
    root = document.get("collection") if isinstance(document, dict) else None
    candidate = root if isinstance(root, dict) else document
    if not isinstance(candidate, dict):
        return False
    info = candidate.get("info")
    items = candidate.get("item")
    return isinstance(info, dict) and isinstance(items, list)


def parse_postman(document: dict[str, Any]) -> list[InternalApiSchema]:
    """展平 Postman 集合及嵌套文件夹，过滤凭据后输出接口定义。"""
    if isinstance(document.get("collection"), dict):
        document = document["collection"]
    info = document.get("info")
    if not isinstance(info, dict) or not isinstance(document.get("item"), list):
        raise ValueError("Postman Collection 格式无效：需要 info 和 item 字段")

    schema_url = str(info.get("schema") or document.get("_postman_schema") or "")
    if schema_url and not re.search(r"2\.[01](?:\.0)?(?:/|#|$)", schema_url):
        raise ValueError("当前仅支持 Postman Collection v2.0/v2.1；请导出为 Collection v2.1 JSON")

    results: list[InternalApiSchema] = []
    _walk_items(
        document["item"],
        folders=[],
        inherited_auth=document.get("auth"),
        output=results,
    )
    if not results:
        raise ValueError("Postman Collection 中没有可导入的 HTTP 请求")
    return results


def _walk_items(
    items: list[Any],
    *,
    folders: list[str],
    inherited_auth: Any,
    output: list[InternalApiSchema],
) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if isinstance(item.get("item"), list):
            folder_auth = item.get("auth", inherited_auth)
            _walk_items(
                item["item"],
                folders=folders + ([name] if name else []),
                inherited_auth=folder_auth,
                output=output,
            )
            continue
        request = item.get("request")
        if not isinstance(request, (dict, str)):
            continue
        schema = _parse_request(
            item,
            request,
            folders=folders,
            inherited_auth=inherited_auth,
        )
        if schema is not None:
            output.append(schema)


def _parse_request(
    item: dict[str, Any],
    request: dict[str, Any] | str,
    *,
    folders: list[str],
    inherited_auth: Any,
) -> InternalApiSchema | None:
    if isinstance(request, str):
        method, url_obj, headers, body, auth = "GET", request, [], {}, None
    else:
        method = str(request.get("method") or "GET").upper()
        url_obj = request.get("url") or ""
        headers = request.get("header") if isinstance(request.get("header"), list) else []
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        auth = request.get("auth")

    if method not in HTTP_METHODS:
        return None
    path, query, path_variables = _parse_url(url_obj)
    parameters = _build_parameters(path, query, path_variables, headers)
    auth_mode = str(auth.get("type") or "").lower() if isinstance(auth, dict) else ""
    effective_auth = auth if isinstance(auth, dict) and auth_mode != "inherit" else inherited_auth
    auth_type = _apply_auth(parameters, effective_auth)

    content_type = _header_value(headers, "content-type")
    parsed_body = _parse_body(body, content_type)
    if parsed_body.content_type:
        content_type = parsed_body.content_type
    responses = _parse_responses(item.get("response"))

    description = _description(request.get("description") if isinstance(request, dict) else None)
    if not description:
        description = _description(item.get("description"))
    tags = [folder for folder in folders if folder]
    request_name = str(item.get("name") or f"{method} {path}").strip()
    return InternalApiSchema(
        name=request_name[:200],
        description=description[:1000] if description else None,
        method=method,
        path=path,
        auth_type=auth_type,
        content_type=content_type or "application/json",
        parameters=parameters,
        body=parsed_body,
        responses=responses,
        tags=tags,
        suggested_module=infer_module_name_from_path(path),
        source_type="POSTMAN",
    )


def _parse_url(url_obj: Any) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(url_obj, str):
        raw = url_obj
        url_data: dict[str, Any] = {}
    elif isinstance(url_obj, dict):
        url_data = url_obj
        raw = str(url_obj.get("raw") or "")
        if not raw:
            protocol = str(url_obj.get("protocol") or "https")
            host = url_obj.get("host") or []
            host_text = ".".join(str(part) for part in host) if isinstance(host, list) else str(host)
            port = str(url_obj.get("port") or "")
            netloc = f"{host_text}:{port}" if port and host_text else host_text
            path_value = url_obj.get("path") or []
            path_text = "/".join(str(part) for part in path_value) if isinstance(path_value, list) else str(path_value).lstrip("/")
            raw = f"{protocol}://{netloc}/{path_text}"
    else:
        raise ValueError("Postman 请求缺少有效的 URL")

    if not raw.strip():
        raise ValueError("Postman 请求缺少有效的 URL")
    normalized_raw = _DOUBLE_BRACE_RE.sub(r"{\1}", raw.strip())
    parts = urlsplit(normalized_raw)
    if not parts.scheme and not normalized_raw.startswith("/"):
        parts = urlsplit("//" + normalized_raw)

    path_value = url_data.get("path") if isinstance(url_data, dict) else None
    if isinstance(path_value, list) and path_value:
        raw_path = "/" + "/".join(str(part) for part in path_value)
    elif isinstance(path_value, str) and path_value:
        raw_path = path_value if path_value.startswith("/") else "/" + path_value
    else:
        raw_path = parts.path or "/"
    raw_path = _DOUBLE_BRACE_RE.sub(r"{\1}", raw_path)
    path = _PATH_PARAM_RE.sub(lambda match: f"{match.group(1)}{{{match.group(2)}}}", raw_path)
    if len(path) > 500:
        raise ValueError("Postman 请求路径超过 500 个字符，无法导入")

    query_value = url_data.get("query") if isinstance(url_data, dict) else None
    if isinstance(query_value, list) and query_value:
        query = [entry for entry in query_value if isinstance(entry, dict) and not entry.get("disabled")]
    else:
        query = [{"key": key, "value": value} for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    variables = url_data.get("variable") if isinstance(url_data, dict) else None
    path_variables = [entry for entry in variables if isinstance(entry, dict)] if isinstance(variables, list) else []
    return path or "/", query, path_variables


def _build_parameters(
    path: str,
    query: list[dict[str, Any]],
    path_variables: list[dict[str, Any]],
    headers: list[Any],
) -> list[InternalParameter]:
    result: list[InternalParameter] = []
    seen: set[tuple[str, str]] = set()
    variable_map = {str(v.get("key") or v.get("id") or ""): v for v in path_variables}
    sort = 0

    def add(param: InternalParameter) -> None:
        nonlocal sort
        key = (param.location, param.name.lower())
        if key in seen or not param.name:
            return
        seen.add(key)
        param.sort = sort
        sort += 1
        result.append(param)

    for name in re.findall(r"\{([A-Za-z_]\w*)\}", path):
        variable = variable_map.get(name, {})
        value = variable.get("value")
        sensitive = _is_sensitive(name)
        add(InternalParameter(
            name=name,
            location="PATH",
            type=str(variable.get("type") or "string"),
            required=True,
            description=_description(variable.get("description")),
            example=_masked_value(name, value) if sensitive and value is not None else _as_text(value),
            schema_json={"sensitive": True} if sensitive else None,
        ))

    for entry in query:
        name = str(entry.get("key") or "").strip()
        if not name:
            continue
        value = entry.get("value")
        sensitive = _is_sensitive(name)
        add(InternalParameter(
            name=name,
            location="QUERY",
            type="string",
            required=False,
            description=_description(entry.get("description")),
            example=_masked_value(name, value) if sensitive and value is not None else _as_text(value),
            schema_json={"sensitive": True} if sensitive else None,
        ))

    for entry in headers:
        if not isinstance(entry, dict) or entry.get("disabled"):
            continue
        name = str(entry.get("key") or "").strip()
        low = name.lower()
        if not name or low in {"content-type", "content-length", "host"}:
            continue
        value = entry.get("value")
        if low == "cookie":
            for cookie in str(value or "").split(";"):
                cookie_name = cookie.partition("=")[0].strip()
                if cookie_name:
                    add(InternalParameter(
                        name=cookie_name,
                        location="COOKIE",
                        type="string",
                        required=False,
                        example="${cookie}",
                        schema_json={"sensitive": True},
                    ))
            continue
        sensitive = _is_sensitive(name)
        add(InternalParameter(
            name=name,
            location="HEADER",
            type="string",
            required=False,
            description=_description(entry.get("description")),
            example=_masked_value(name, value) if sensitive else _as_text(value),
            schema_json={"sensitive": True} if sensitive else None,
        ))
    return result


def _apply_auth(parameters: list[InternalParameter], auth: Any) -> str:
    if not isinstance(auth, dict):
        return "none"
    auth_type = str(auth.get("type") or "none").lower()
    if auth_type in {"", "none", "noauth", "inherit"}:
        return "none"
    if auth_type == "apikey":
        values = auth.get("apikey") if isinstance(auth.get("apikey"), list) else []
        key_data = next((v for v in values if isinstance(v, dict) and v.get("key") == "key"), {})
        name = str(key_data.get("value") or "X-API-Key")
        where = next((v.get("value") for v in values if isinstance(v, dict) and v.get("key") == "in"), "header")
        location = {"query": "QUERY", "cookie": "COOKIE"}.get(str(where).lower(), "HEADER")
        if not any(p.location == location and p.name.lower() == name.lower() for p in parameters):
            parameters.append(InternalParameter(
                name=name,
                location=location,
                type="string",
                required=False,
                example=_masked_value(name, None),
                schema_json={"sensitive": True},
                sort=len(parameters),
            ))
        return "apikey"
    aliases = {"bearer": "bearer", "basic": "basic", "oauth2": "oauth2", "digest": "digest"}
    return aliases.get(auth_type, auth_type[:30])


def _parse_body(body: dict[str, Any], content_type: str | None) -> InternalBody:
    mode = str(body.get("mode") or "none").lower()
    if mode == "raw":
        raw = str(body.get("raw") or "")
        if not raw.strip():
            return InternalBody(body_type="none")
        options = body.get("options") if isinstance(body.get("options"), dict) else {}
        raw_options = options.get("raw") if isinstance(options.get("raw"), dict) else {}
        language = str(raw_options.get("language") or "").lower()
        ct = content_type or ("application/json" if language == "json" or _looks_json(raw) else "text/plain")
        if _is_json_content_type(ct) or _looks_json(raw):
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                return InternalBody(body_type="raw", content_type=ct, raw_text=_sanitize_text(raw))
            safe = _sanitize_json(parsed)
            raw_safe = json.dumps(safe, ensure_ascii=False)
            return InternalBody(
                body_type="json",
                content_type=ct,
                schema_json={"example": safe},
                raw_text=raw_safe,
            )
        return InternalBody(body_type="raw", content_type=ct, raw_text=_sanitize_text(raw))

    if mode in {"urlencoded", "formdata"}:
        multipart = mode == "formdata"
        fields = body.get(mode) if isinstance(body.get(mode), list) else []
        properties: dict[str, dict[str, Any]] = {}
        for field in fields:
            if not isinstance(field, dict) or field.get("disabled"):
                continue
            name = str(field.get("key") or "").strip()
            if not name:
                continue
            entry: dict[str, Any] = {"type": "file"} if field.get("type") == "file" else {"type": "string"}
            if field.get("type") != "file" and field.get("value") is not None:
                entry["example"] = _masked_value(name, field["value"]) if _is_sensitive(name) else _as_text(field["value"])
            description = _description(field.get("description"))
            if description:
                entry["description"] = description
            if _is_sensitive(name):
                entry["sensitive"] = True
            properties[name] = entry
        if not properties:
            return InternalBody(body_type="none")
        default_ct = "multipart/form-data" if multipart else "application/x-www-form-urlencoded"
        return InternalBody(
            body_type="multipart" if multipart else "form",
            content_type=content_type or default_ct,
            schema_json={"type": "object", "properties": properties},
        )

    if mode == "graphql":
        safe = _sanitize_json(body.get("graphql") or {})
        return InternalBody(
            body_type="json",
            content_type=content_type or "application/json",
            schema_json={"example": safe},
            raw_text=json.dumps(safe, ensure_ascii=False),
        )
    return InternalBody(body_type="none")


def _parse_responses(raw_responses: Any) -> list[InternalResponse]:
    results: list[InternalResponse] = []
    if isinstance(raw_responses, list):
        for response in raw_responses:
            if not isinstance(response, dict):
                continue
            try:
                code = int(response.get("code"))
            except (TypeError, ValueError):
                continue
            if not 100 <= code <= 599:
                continue
            body = response.get("body")
            schema_json = None
            example_json = None
            if isinstance(body, str) and body.strip():
                try:
                    parsed = json.loads(body)
                except (TypeError, ValueError):
                    example_json = _sanitize_text(body)
                else:
                    safe = _sanitize_json(parsed)
                    schema_json = {"example": safe}
                    example_json = json.dumps(safe, ensure_ascii=False)
            results.append(InternalResponse(
                status_code=code,
                description=str(response.get("status") or response.get("name") or "") or None,
                schema_json=schema_json,
                example_json=example_json,
                sort=len(results),
            ))
    return results or [InternalResponse(status_code=200, description="成功（Postman 未携带响应示例）", sort=0)]


def _header_value(headers: list[Any], name: str) -> str | None:
    for entry in headers:
        if isinstance(entry, dict) and str(entry.get("key") or "").lower() == name.lower():
            return str(entry.get("value") or "")
    return None


def _description(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("content") or value.get("value")
    if isinstance(value, list):
        value = "\n".join(str(part) for part in value)
    text = str(value).strip() if value is not None else ""
    return text or None


def _sanitize_json(value: Any, key: str = "") -> Any:
    if key and _is_sensitive(key):
        return _masked_value(key, value)
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    return value


def _sanitize_text(value: str) -> str:
    return _SENSITIVE_TEXT_RE.sub(lambda match: f"{match.group(1)}${{secret}}", value)


def _is_sensitive(name: str) -> bool:
    normalized = (name or "").lower()
    return bool(
        _SENSITIVE_NAME_RE.search(normalized)
        or normalized in {"auth", "authentication"}
        or re.search(r"(?:^|[_-])auth(?:[_-]|$)", normalized)
    )


def _masked_value(name: str, value: Any) -> str:
    if name.lower() == "authorization" and isinstance(value, str):
        scheme = value.split(None, 1)[0] if value.strip() else ""
        if scheme.lower() in {"bearer", "basic", "digest", "negotiate", "ntlm"}:
            return f"{scheme} ${{token}}"
    safe_name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower() or "secret"
    return f"${{{safe_name}}}"


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _looks_json(value: str) -> bool:
    return value.lstrip().startswith(("{", "["))


def _is_json_content_type(value: str) -> bool:
    low = value.lower()
    return "json" in low or "+json" in low


__all__ = ["is_postman_collection", "parse_postman"]
