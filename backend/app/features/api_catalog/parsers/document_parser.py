"""识别常见接口文档格式并转成统一接口结构。"""

from __future__ import annotations

from typing import Any

import yaml

from app.features.api_catalog.parsers.openapi_parser import parse_openapi
from app.features.api_catalog.parsers.postman_parser import is_postman_collection, parse_postman
from app.features.api_catalog.schemas import InternalApiSchema


def parse_api_document(content: str, *, required: bool = True) -> list[InternalApiSchema] | None:
    """自动识别 OpenAPI/Swagger/Postman；无法识别时可返回 None 供 cURL 回退。"""
    if not content or not content.strip():
        if required:
            raise ValueError("接口文档内容为空")
        return None
    try:
        document: Any = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        if required:
            raise ValueError(f"JSON/YAML 文档解析失败：{exc}") from exc
        return None
    if not isinstance(document, dict):
        if required:
            raise ValueError(_supported_formats_message())
        return None

    collection = document.get("collection")
    candidate = collection if isinstance(collection, dict) else document
    if is_postman_collection(document) or (
        isinstance(candidate, dict)
        and isinstance(candidate.get("info"), dict)
        and ("item" in candidate or "schema.getpostman.com" in str(candidate["info"].get("schema") or ""))
    ):
        return parse_postman(document)
    if "openapi" in document or "swagger" in document:
        return parse_openapi(content)
    if required:
        raise ValueError(_supported_formats_message())
    return None


def _supported_formats_message() -> str:
    return (
        "无法识别接口文档；支持 cURL、OpenAPI 3.x、Swagger 2.0 和 Postman Collection v2.0/v2.1。"
        "Apifox 文件请导出为 OpenAPI/Swagger 或 Postman 格式后导入"
    )


__all__ = ["parse_api_document"]
