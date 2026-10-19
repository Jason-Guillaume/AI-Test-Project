"""Web UI 管理服务：页面对象、用例、人工确认、加密凭据及附件权限。

既有执行编排只通过 RunService 调用，浏览器运行逻辑不在路由层实现。
"""
from __future__ import annotations
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.features.web_ui.models import PageObject, WebArtifact, WebAuthProfile, WebCase
from app.features.web_ui.schemas import AuthInput, CaseInput, PageInput, WebStep
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.services._access import get_project_or_404, require_writable_project
from app.models.configuration import Environment
from app.shared.crypto import encrypt_secret, decrypt_secret
from app.shared.errors import bad_request, conflict, not_found


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


def get_row(db, model, row_id, actor, *, write=False):
    """按资源归属判权限；跨项目和不存在均返回 404。"""
    row = db.get(model, row_id)
    if row is None:
        raise not_found("Web 资源不存在")
    project_id = row.project_id
    (require_writable_project if write else get_project_or_404)(db, project_id, actor)
    return row


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


def list_result(query, mapper, page, page_size):
    """沿用平台分页信封与 200 条上限，避免用例附件配置无界加载。"""
    total = query.order_by(None).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [mapper(row) for row in items], "total": total, "page": page, "page_size": page_size}


class WebUIService:
    """无状态管理服务；所有写操作先校验项目 member+ 并负责 commit。"""
    def list_pages(self, db, project_id, actor, *, page=1, page_size=200):
        """读取当前项目页面对象。"""
        get_project_or_404(db, project_id, actor)
        return list_result(db.query(PageObject).filter_by(project_id=project_id).order_by(PageObject.id.desc()), page_response, page, page_size)

    def save_page(self, db, project_id, body: PageInput, actor, page_id=None):
        """新增或按 revision 更新页面；所有引用该页面的旧确认自然失效。"""
        require_writable_project(db, project_id, actor)
        if page_id:
            row = get_row(db, PageObject, page_id, actor, write=True)
            if row.project_id != project_id:
                raise not_found("页面对象不存在")
            row = db.query(PageObject).filter_by(id=page_id).with_for_update().populate_existing().one()
            if body.revision != row.revision:
                raise conflict("页面已被修改，请刷新")
            row.revision += 1
        else:
            row = PageObject(project_id=project_id)
            db.add(row)
        row.name, row.path = body.name.strip(), body.path
        row.elements = [e.model_dump() for e in body.elements]
        if not row.name:
            raise bad_request("页面名称不能为空")
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise conflict("项目内页面名称已存在") from exc
        return page_response(row)

    def delete_page(self, db, page_id, actor):
        """删除页面，引用它的用例将显示未确认并在执行前失败。"""
        db.delete(get_row(db, PageObject, page_id, actor, write=True))
        db.commit()

    def list_cases(self, db, project_id, actor, *, page=1, page_size=20):
        """复用 TestCase 资产，仅返回有 Web 扩展的项目内用例。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(TestCase).join(WebCase, WebCase.test_case_id == TestCase.id).filter(TestCase.project_id == project_id).order_by(TestCase.id.desc())
        return list_result(query, lambda row: case_response(db, row), page, page_size)

    def get_case(self, db, case_id, actor):
        """编辑器详情继承项目可见性。"""
        case = get_row(db, TestCase, case_id, actor)
        return case_response(db, case)

    def save_case(self, db, project_id, body: CaseInput, actor, case_id=None, source_type="MANUAL"):
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

    def confirm_case(self, db, case_id, revision, actor):
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

    def delete_case(self, db, case_id, actor):
        """删除既有测试资产；历史执行由原有外键 SET NULL 保留。"""
        case = get_row(db, TestCase, case_id, actor, write=True)
        if db.get(WebCase, case_id) is None:
            raise not_found("Web 用例不存在")
        db.delete(case)
        db.commit()

    def list_auth(self, db, project_id, actor, *, page=1, page_size=200):
        """列出凭据元信息，永不返回 Cookie/Token/密码。"""
        get_project_or_404(db, project_id, actor)
        return list_result(db.query(WebAuthProfile).filter_by(project_id=project_id).order_by(WebAuthProfile.id.desc()), auth_response, page, page_size)

    def save_auth(self, db, project_id, body: AuthInput, actor, auth_id=None):
        """加密保存账号与人工扫码后的 storage_state；限定最长 30 天有效期。"""
        require_writable_project(db, project_id, actor)
        environment = db.get(Environment, body.environment_id)
        if environment is None or not environment.is_active:
            raise not_found("环境不存在或已停用")
        expires = body.expires_at.replace(tzinfo=timezone.utc) if body.expires_at.tzinfo is None else body.expires_at.astimezone(timezone.utc)
        if not datetime.now(timezone.utc) < expires <= datetime.now(timezone.utc) + timedelta(days=30):
            raise bad_request("认证有效期必须在未来 30 天内")
        from app.features.web_ui.runtime.adapter import validate_storage_state
        from app.features.web_ui.runtime.policy import TargetPolicy
        state = validate_storage_state(body.storage_state, TargetPolicy(db, project_id), environment)
        payload = {"username": body.username, "password": body.password, "jwt": body.jwt,
                   "jwt_storage_key": body.jwt_storage_key, "storage_state": state}
        if auth_id:
            row = get_row(db, WebAuthProfile, auth_id, actor, write=True)
            if row.project_id != project_id:
                raise not_found("认证配置不存在")
        else:
            row = WebAuthProfile(project_id=project_id, created_by=actor.id)
            db.add(row)
        row.name, row.environment_id = body.name, body.environment_id
        row.secret_encrypted, row.expires_at = encrypt_secret(json_dump(payload)), expires.replace(tzinfo=None)
        db.commit()
        return auth_response(row)

    def delete_auth(self, db, auth_id, actor):
        """撤销认证配置，清除引用用例的人工确认，避免静默变为匿名执行。"""
        row = get_row(db, WebAuthProfile, auth_id, actor, write=True)
        db.query(WebCase).filter_by(auth_profile_id=auth_id).update({"confirmed_digest": None}, synchronize_session=False)
        db.delete(row)
        db.commit()

    def artifact(self, db, artifact_id, actor):
        """附件读取继承当前项目权限，不接受路径参数，也不返回密文存储位置。"""
        row = get_row(db, WebArtifact, artifact_id, actor)
        content = decrypt_secret(row.content_encrypted)
        if not content:
            raise not_found("附件无法读取")
        return row, base64.b64decode(content)

    def debug(self, db, case_id, environment_id, actor):
        """人工确认校验通过后，使用既有 RunService 创建单例 TestRun。"""
        case = get_row(db, TestCase, case_id, actor, write=True)
        if not case_response(db, case)["confirmed"]:
            raise conflict("请先人工确认当前用例及其页面对象")
        from app.features.test_management.services.run_service import RunService
        return RunService().execute_case(db, case_id, environment_id, actor=actor)

    def history(self, db, project_id, actor, *, case_id=None, page=1, page_size=20):
        """历史直接读取 CaseExecution/TestRun，返回既有结果与报告编号。"""
        from app.features.test_management.models.execution import CaseExecution, TestRun
        from app.features.test_management.schemas import CaseExecutionResponse
        from app.features.reports.models.report import TestReport
        get_project_or_404(db, project_id, actor)
        query = db.query(CaseExecution).join(TestRun, TestRun.id == CaseExecution.test_run_id).filter(
            TestRun.project_id == project_id,
            or_(CaseExecution.executor_type == "WEB", CaseExecution.response_snapshot["web"].is_not(None)))
        if case_id:
            case = get_row(db, TestCase, case_id, actor)
            if case.project_id != project_id:
                raise not_found("Web 用例不存在")
            query = query.filter(CaseExecution.test_case_id == case_id)
        total = query.count()
        rows = query.order_by(CaseExecution.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = []
        for row in rows:
            item = CaseExecutionResponse.model_validate(row).model_dump(mode="json")
            report = db.query(TestReport).filter_by(test_run_id=row.test_run_id, status="COMPLETED").first()
            item["report_id"] = report.id if report else None
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def bind_action(self, db, action_id, case_id, actor):
        """同项目动作绑定 WEB，取消其他通道默认选择；不修改 API/WEB 绑定数据契约。"""
        from app.features.business.models.business_action import BusinessAction
        from app.features.business.models.business_binding import BusinessBinding
        from app.features.business.services._access import resolve_action_project_id
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

    def trace_events(self, db, artifact_id, actor):
        """解密已脱敏 Trace 并返回动作事件，最多 2000 条。"""
        import io
        import zipfile
        row, content = self.artifact(db, artifact_id, actor)
        if row.kind != "TRACE":
            raise bad_request("该附件不是 Trace")
        events = []
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for name in archive.namelist():
                if name.endswith(".trace"):
                    for line in archive.read(name).decode().splitlines():
                        if len(events) >= 2000:
                            break
                        events.append(json.loads(line))
        return {"events": events}

    def environment_options(self, db, project_id, actor, keyword=""):
        """项目成员读取可执行环境的最小元信息，不开放管理端的默认请求头或凭据。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(Environment).filter(Environment.is_active.is_(True))
        if keyword.strip():
            query = query.filter(or_(Environment.name.ilike(f"%{keyword.strip()}%"), Environment.display_name.ilike(f"%{keyword.strip()}%")))
        total = query.count()
        rows = query.order_by(Environment.id.desc()).limit(200).all()
        return {"items": [{"id": e.id, "name": e.name, "display_name": e.display_name, "is_active": e.is_active} for e in rows],
                "total": total, "page": 1, "page_size": 200}
