"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from app.features.web_testing.models import WebAuthProfile, WebCase
from app.features.web_testing.schemas import CaseInput
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_step import TestStep
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.security.crypto import encrypt_secret
from app.core.http.errors import bad_request, conflict, not_found
from app.features.web_testing.services.case_inputs import case_digest
from app.features.web_testing.services.case_inputs import case_response
from app.features.web_testing.services.case_inputs import expand_steps
from app.features.web_testing.services.access_service import get_row
from app.features.web_testing.services.response_mapper import json_dump
from app.features.web_testing.services.response_mapper import list_result
from app.features.web_testing.services.case_inputs import load_steps


def list_cases(db, project_id, actor, *, page=1, page_size=20):
    """复用 TestCase 资产，仅返回有 Web 扩展的项目内用例。"""
    get_project_or_404(db, project_id, actor)
    query = db.query(TestCase).join(WebCase, WebCase.test_case_id == TestCase.id).filter(TestCase.project_id == project_id).order_by(TestCase.id.desc())
    return list_result(query, lambda row: case_response(db, row), page, page_size)


def get_case(db, case_id, actor):
    """编辑器详情继承项目可见性。"""
    case = get_row(db, TestCase, case_id, actor)
    return case_response(db, case)


def save_case(db, project_id, body: CaseInput, actor, case_id=None, source_type="MANUAL"):
    """原子保存 TestCase/TestStep/WebCase，更新使旧人工确认失效。"""
    require_writable_project(db, project_id, actor)
    if len(json_dump(body.model_dump())) > 2000000:
        raise bad_request("单用例配置不能超过 2MB")
    expand_steps(db, project_id, [s.model_dump() for s in body.steps])
    if body.auth_profile_id:
        auth = get_row(db, WebAuthProfile, body.auth_profile_id, actor)
        if auth.project_id != project_id:
            raise not_found("认证配置不存在")
    if case_id:
        case = get_row(db, TestCase, case_id, actor, write=True)
        if case.project_id != project_id or db.get(WebCase, case_id) is None:
            raise not_found("Web 用例不存在")
        case = db.query(TestCase).filter_by(id=case_id).with_for_update().populate_existing().one()
        if body.revision != case.revision:
            raise conflict("用例已被修改，请刷新")
        case.revision += 1
        config = db.get(WebCase, case_id)
        db.query(TestStep).filter_by(test_case_id=case_id).delete(synchronize_session=False)
    else:
        case = TestCase(project_id=project_id, name=body.name.strip(), target_type="WEB", source_type=source_type,
                        status="DRAFT", enabled=True, created_by=actor.id)
        db.add(case)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise conflict("项目内用例名称已存在") from exc
        config = WebCase(test_case_id=case.id)
        db.add(config)
    case.name, case.description, case.status, case.target_type = body.name.strip(), body.description, "DRAFT", "WEB"
    if not case.name:
        raise bad_request("用例名称不能为空")
    config.auth_profile_id, config.timeout_ms = body.auth_profile_id, body.timeout_ms
    config.total_timeout_ms, config.confirmed_digest, config.confirmed_by = body.total_timeout_ms, None, None
    for index, step in enumerate(body.steps):
        db.add(TestStep(test_case_id=case.id, name=step.name, step_type="ACTION", target_type="WEB", sort=index,
                        config_json={"web_encrypted": encrypt_secret(json_dump(step.model_dump()))}))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("项目内用例名称已存在") from exc
    return case_response(db, case)


def confirm_case(db, case_id, revision, actor):
    """人工确认当前版本；执行端仍复核完整指纹，生成接口不能绕过该入口。"""
    case = get_row(db, TestCase, case_id, actor, write=True)
    case = db.query(TestCase).filter_by(id=case_id).with_for_update().populate_existing().one()
    config = db.get(WebCase, case.id)
    if config is None:
        raise not_found("Web 用例不存在")
    if revision != case.revision:
        raise conflict("用例版本已变更，请重新审核")
    if case.target_type != "WEB" or not case.enabled:
        raise bad_request("用例已被停用或变更类型，请先在 Web 编辑器恢复配置")
    case.status = "ACTIVE"
    config.confirmed_digest = case_digest(db, case, config, load_steps(db, case.id))
    config.confirmed_by = actor.id
    db.commit()
    return case_response(db, case)


def delete_case(db, case_id, actor):
    """删除既有测试资产；历史执行由原有外键 SET NULL 保留。"""
    case = get_row(db, TestCase, case_id, actor, write=True)
    if db.get(WebCase, case_id) is None:
        raise not_found("Web 用例不存在")
    db.delete(case)
    db.commit()


def bind_action(db, action_id, case_id, actor):
    """同项目动作绑定 WEB，取消其他通道默认选择；不修改 API/WEB 绑定数据契约。"""
    from app.features.business.models.business_action import BusinessAction
    from app.features.business.models.business_binding import BusinessBinding
    from app.features.business.services.access_service import resolve_action_project_id
    project_id = resolve_action_project_id(db, action_id)
    require_writable_project(db, project_id, actor)
    # 锁动作行，防止两个并发选择留下两个通道都默认。
    db.query(BusinessAction).filter_by(id=action_id).with_for_update().populate_existing().one()
    case = get_row(db, TestCase, case_id, actor)
    if case.project_id != project_id or db.get(WebCase, case_id) is None:
        raise not_found("Web 用例不存在")
    db.query(BusinessBinding).filter_by(action_id=action_id, is_default=True).update({"is_default": False}, synchronize_session=False)
    db.flush()
    binding = BusinessBinding(action_id=action_id, binding_type="WEB", name=case.name,
        config_json={"web_case_id": case.id}, enabled=True, is_default=True)
    db.add(binding)
    db.commit()
    return {"id": binding.id, "action_id": action_id, "binding_type": "WEB", "web_case_id": case.id}
