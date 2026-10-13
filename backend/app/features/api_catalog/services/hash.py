"""source_hash 计算：对 Internal API Schema 做规范化 sha256。

只对「接口结构」字段求哈希（method/path/auth_type/content_type/参数/body/响应），
排除 name/description/tags/suggested_module/source_type/source_hash 自身，
使同一接口经不同来源（curl vs openapi）导入时得到稳定哈希。
用于导入去重与变更检测：UNCHANGED（hash 相同）vs CHANGED（hash 不同）。
"""

from __future__ import annotations

import hashlib
import json

from app.features.api_catalog.schemas import InternalApiSchema

# 哈希排除字段：这些字段不构成接口结构，变更它们不算结构变更。
_HASH_EXCLUDE: frozenset[str] = frozenset(
    {"name", "description", "tags", "suggested_module", "source_type", "source_hash"}
)


def canonical_payload(schema: InternalApiSchema) -> dict:
    """返回用于哈希的规范化 dict（排除非结构字段，mode=json 递归可序列化）。"""
    return schema.model_dump(mode="json", exclude=_HASH_EXCLUDE)


def compute_source_hash(schema: InternalApiSchema) -> str:
    """计算 source_hash：sha256(规范化 JSON，字段排序，紧凑分隔)。"""
    payload = canonical_payload(schema)
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
