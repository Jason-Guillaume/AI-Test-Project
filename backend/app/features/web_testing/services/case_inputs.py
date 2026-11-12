"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import hashlib
import json
from app.features.web_testing.models import PageObject, WebAuthProfile, WebCase
from app.features.web_testing.schemas import WebStep
from app.features.test_management.models.test_step import TestStep
from app.core.security.crypto import decrypt_secret
from app.core.http.errors import bad_request, not_found
from app.features.web_testing.services.response_mapper import json_dump


def load_steps(db, case_id):
    """解密 TestStep 配置后按持久化顺序返回，非 Web 步骤不能混入。"""
    rows = db.query(TestStep).filter_by(test_case_id=case_id).order_by(TestStep.sort, TestStep.id).all()
    steps = []
    for row in rows:
        config = row.config_json or {}
        if row.target_type != "WEB" or set(config) != {"web_encrypted"}:
            raise bad_request("Web 用例包含非法步骤，请在 Web 步骤编辑器重新保存")
        raw = decrypt_secret(config["web_encrypted"])
        if not raw:
            raise bad_request("Web 步骤密文无法解密")
        step = WebStep.model_validate(json.loads(raw)).model_dump()
        # 名称与排序取 TestStep 的当前值；通用编辑器修改后也会使确认失效。
        step["name"] = row.name
        steps.append(step)
    return steps


def expand_steps(db, project_id, steps):
    """将项目内页面元素引用展开，跨项目/失效引用拒绝执行。"""
    expanded = []
    for original in steps:
        step = dict(original)
        if step.get("page_object_id"):
            page = db.get(PageObject, step["page_object_id"])
            if page is None or page.project_id != project_id:
                raise not_found("页面对象不存在")
            if step.get("element_key"):
                element = next((e for e in page.elements if e["key"] == step["element_key"]), None)
                if element is None:
                    raise bad_request("页面元素引用已失效")
                step["locator"] = element["locator"]
            elif step["operation"] == "NAVIGATE" and not step.get("value"):
                step["value"] = page.path
        expanded.append(step)
    return expanded


def case_digest(db, case, config, steps):
    """指纹覆盖用例状态、实际步骤、页面定位及认证配置；任何改动都要求再次确认。"""
    auth = db.get(WebAuthProfile, config.auth_profile_id) if config.auth_profile_id else None
    payload = {"revision": case.revision, "name": case.name, "target_type": case.target_type,
               "status": case.status, "enabled": case.enabled,
               "steps": expand_steps(db, case.project_id, steps), "auth_profile_id": config.auth_profile_id,
               "auth_version": auth.secret_encrypted if auth else None,
               "timeout_ms": config.timeout_ms, "total_timeout_ms": config.total_timeout_ms}
    return hashlib.sha256(json_dump(payload).encode()).hexdigest()


def case_response(db, case):
    """供编辑器读取结构化步骤；加密配置和确认摘要不对外返回。"""
    config = db.get(WebCase, case.id)
    if config is None:
        raise not_found("Web 用例不存在")
    steps = load_steps(db, case.id)
    try:
        confirmed = bool(config.confirmed_digest and config.confirmed_digest == case_digest(db, case, config, steps))
    except Exception:
        confirmed = False
    return {"id": case.id, "project_id": case.project_id, "name": case.name, "description": case.description or "",
            "revision": case.revision, "source_type": case.source_type, "confirmed": confirmed,
            "auth_profile_id": config.auth_profile_id, "timeout_ms": config.timeout_ms,
            "total_timeout_ms": config.total_timeout_ms, "steps": steps}
