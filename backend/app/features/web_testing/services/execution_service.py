"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import base64
import json
from sqlalchemy import or_
from app.features.web_testing.models import WebArtifact
from app.features.test_management.models.test_case import TestCase
from app.platform.projects.services.access_service import get_project_or_404
from app.platform.environment_configuration.services.environment_service import list_project_environment_options
from app.core.security.crypto import decrypt_secret
from app.core.http.errors import bad_request, conflict, not_found
from app.features.web_testing.services.case_inputs import case_response
from app.features.web_testing.services.access_service import get_row


def artifact(db, artifact_id, actor):
    """附件读取继承当前项目权限，不接受路径参数，也不返回密文存储位置。"""
    row = get_row(db, WebArtifact, artifact_id, actor)
    content = decrypt_secret(row.content_encrypted)
    if not content:
        raise not_found("附件无法读取")
    return row, base64.b64decode(content)


def debug(db, case_id, environment_id, actor):
    """人工确认校验通过后，使用既有 RunService 创建单例 TestRun。"""
    case = get_row(db, TestCase, case_id, actor, write=True)
    if not case_response(db, case)["confirmed"]:
        raise conflict("请先人工确认当前用例及其页面对象")
    from app.features.test_management.services.run_service import RunService
    return RunService().execute_case(db, case_id, environment_id, actor=actor)


def history(db, project_id, actor, *, case_id=None, page=1, page_size=20):
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


def trace_events(db, artifact_id, actor):
    """解密已脱敏 Trace 并返回动作事件，最多 2000 条。"""
    import io
    import zipfile
    row, content = artifact(db, artifact_id, actor)
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


def environment_options(db, project_id, actor, keyword=""):
    """项目成员读取可执行环境的最小元信息，不开放管理端的默认请求头或凭据。"""
    get_project_or_404(db, project_id, actor)
    rows = list_project_environment_options(db, project_id)
    term = keyword.strip().lower()
    if term:
        rows = [row for row in rows if term in row["name"].lower() or term in row["display_name"].lower()]
    rows = rows[:200]
    return {"items": [{"id": row["id"], "name": row["name"], "display_name": row["display_name"], "is_active": row["is_active"]} for row in rows],
            "total": len(rows), "page": 1, "page_size": 200}
