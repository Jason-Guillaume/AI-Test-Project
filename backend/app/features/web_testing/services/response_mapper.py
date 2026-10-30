"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json


def json_dump(value):
    """稳定序列化，保证人工确认指纹可复算。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def page_response(row):
    """页面对象不包含秘密，可作为 Agent 的结构化页面上下文。"""
    return {"id": row.id, "project_id": row.project_id, "name": row.name, "path": row.path,
            "elements": row.elements, "revision": row.revision}


def auth_response(row):
    """凭据响应仅返回是否配置及到期时间，不解密。"""
    return {"id": row.id, "project_id": row.project_id, "environment_id": row.environment_id,
            "name": row.name, "configured": bool(row.secret_encrypted), "expires_at": row.expires_at}


def list_result(query, mapper, page, page_size):
    """沿用平台分页信封与 200 条上限，避免用例附件配置无界加载。"""
    total = query.order_by(None).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [mapper(row) for row in items], "total": total, "page": page, "page_size": page_size}
