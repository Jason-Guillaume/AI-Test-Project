"""自动化测试中心路由。

业务判断和事务都在服务层。回调接口使用签名，不使用用户登录态。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.features.automation_center.schemas import (
    AutomationProjectCreate,
    AutomationProjectListResponse,
    AutomationProjectResponse,
    AutomationProjectUpdate,
    CallbackResponse,
    ConnectionTestResponse,
    ExecutionListResponse,
    ExecutionResponse,
    ExecutionTrigger,
    IntegrationCreate,
    IntegrationListResponse,
    IntegrationResponse,
    IntegrationUpdate,
    ReportCompareResponse,
    ReportGrantResponse,
    ReportListResponse,
    ReportResponse,
)
from app.features.automation_center.services import AutomationCenterService

router = APIRouter(tags=["自动化测试中心"])
_SERVICE = AutomationCenterService()
_MEDIA = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def _headers(request: Request) -> dict[str, str]:
    """统一成小写头，签名字段不依赖客户端的大小写。"""
    return {key.lower(): value for key, value in request.headers.items()}


@router.get("/projects/{project_id}/automation-integrations", response_model=IntegrationListResponse, summary="云效接入配置列表")
def list_integrations(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
    page: int = Query(1, ge=1), page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出云效接入配置。"""
    return _SERVICE.list_integrations(db, project_id, user, page=page, page_size=page_size)


@router.post(
    "/projects/{project_id}/automation-integrations", response_model=IntegrationResponse,
    status_code=201, summary="创建云效接入配置",
)
def create_integration(
    project_id: int, body: IntegrationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建云效接入配置。"""
    return _SERVICE.create_integration(db, project_id, body, user)


@router.patch("/automation-integrations/{config_id}", response_model=IntegrationResponse, summary="更新云效接入配置")
def update_integration(
    config_id: int, body: IntegrationUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新云效接入配置。"""
    return _SERVICE.update_integration(db, config_id, body, user)


@router.delete("/automation-integrations/{config_id}", status_code=204, summary="删除云效接入配置")
def delete_integration(config_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除云效接入配置。"""
    _SERVICE.delete_integration(db, config_id, user)


@router.post("/automation-integrations/{config_id}/rotate-callback-key", response_model=IntegrationResponse, summary="轮换回调标识")
def rotate_callback_key(config_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """轮换回调标识。"""
    return _SERVICE.rotate_callback_key(db, config_id, user)


@router.post("/automation-integrations/{config_id}/test-connection", response_model=ConnectionTestResponse, summary="测试云效连接")
def test_connection(
    config_id: int, pipeline_id: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """测试云效连接。"""
    return _SERVICE.test_connection(db, config_id, user, pipeline_id)


@router.get("/projects/{project_id}/automation-projects", response_model=AutomationProjectListResponse, summary="自动化项目列表")
def list_projects(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
    page: int = Query(1, ge=1), page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = None,
):
    """列出自动化项目。"""
    return _SERVICE.list_projects(db, project_id, user, page=page, page_size=page_size, keyword=keyword)


@router.post(
    "/projects/{project_id}/automation-projects", response_model=AutomationProjectResponse,
    status_code=201, summary="创建自动化项目",
)
def create_project(
    project_id: int, body: AutomationProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建自动化项目。"""
    return _SERVICE.create_project(db, project_id, body, user)


@router.patch("/automation-projects/{automation_project_id}", response_model=AutomationProjectResponse, summary="更新自动化项目")
def update_project(
    automation_project_id: int, body: AutomationProjectUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新自动化项目。"""
    return _SERVICE.update_project(db, automation_project_id, body, user)


@router.delete("/automation-projects/{automation_project_id}", status_code=204, summary="删除自动化项目")
def delete_project(
    automation_project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """删除自动化项目。"""
    _SERVICE.delete_project(db, automation_project_id, user)


@router.post(
    "/automation-projects/{automation_project_id}/verify", response_model=ConnectionTestResponse, summary="验证自动化项目",
)
def verify_project(
    automation_project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """验证自动化项目绑定的流水线。"""
    return _SERVICE.verify_project(db, automation_project_id, user)


@router.post(
    "/automation-projects/{automation_project_id}/executions", response_model=ExecutionResponse,
    status_code=201, summary="触发自动化执行",
)
def trigger_execution(
    automation_project_id: int, body: ExecutionTrigger,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """触发云效流水线。"""
    return _SERVICE.trigger(db, automation_project_id, body, user)


@router.get("/projects/{project_id}/automation-executions", response_model=ExecutionListResponse, summary="自动化执行历史")
def list_executions(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
    page: int = Query(1, ge=1), page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    automation_project_id: int | None = None, status: str | None = None, branch: str | None = None,
    environment_name: str | None = None, started_from: datetime | None = None, started_to: datetime | None = None,
):
    """列出自动化执行。"""
    return _SERVICE.list_executions(
        db, project_id, user, page=page, page_size=page_size, automation_project_id=automation_project_id,
        status=status, branch=branch, environment_name=environment_name,
        started_from=started_from, started_to=started_to,
    )


@router.get("/automation-executions/{execution_id}", response_model=ExecutionResponse, summary="自动化执行详情")
def get_execution(execution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取自动化执行。"""
    return _SERVICE.get_execution(db, execution_id, user)


@router.post("/automation-executions/{execution_id}/cancel", response_model=ExecutionResponse, summary="取消自动化执行")
def cancel_execution(execution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """取消云效运行。"""
    return _SERVICE.cancel(db, execution_id, user)


@router.post("/automation-executions/{execution_id}/sync", response_model=ExecutionResponse, summary="同步云效执行状态")
def sync_execution(execution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """立即同步云效状态。"""
    return _SERVICE.sync_execution(db, execution_id, user)


@router.get("/projects/{project_id}/automation-reports", response_model=ReportListResponse, summary="Allure 报告列表")
def list_reports(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
    page: int = Query(1, ge=1), page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    automation_project_id: int | None = None, environment_name: str | None = None, branch: str | None = None,
    started_from: datetime | None = None, started_to: datetime | None = None,
):
    """列出 Allure 报告。"""
    return _SERVICE.list_reports(
        db, project_id, user, page=page, page_size=page_size, automation_project_id=automation_project_id,
        environment_name=environment_name, branch=branch, started_from=started_from, started_to=started_to,
    )


@router.get("/projects/{project_id}/automation-report-trend", response_model=list[ReportResponse], summary="Allure 历史趋势")
def report_trend(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user),
    automation_project_id: int | None = None, environment_name: str | None = None, branch: str | None = None,
):
    """读取报告趋势。"""
    return _SERVICE.trend(
        db, project_id, user, automation_project_id=automation_project_id,
        environment_name=environment_name, branch=branch,
    )


@router.get("/automation-reports/compare", response_model=ReportCompareResponse, summary="对比两次 Allure 报告")
def compare_reports(
    left_id: int = Query(ge=1), right_id: int = Query(ge=1),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """对比两次报告统计。"""
    return _SERVICE.compare_reports(db, left_id, right_id, user)


@router.get("/automation-reports/{report_id}", response_model=ReportResponse, summary="Allure 报告详情")
def get_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取 Allure 报告统计。"""
    return _SERVICE.get_report(db, report_id, user)


@router.post("/automation-reports/{report_id}/view-grant", response_model=ReportGrantResponse, summary="签发报告访问凭据")
def issue_grant(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """签发报告文件访问凭据。"""
    return _SERVICE.issue_grant(db, report_id, user)


@router.get("/automation-reports/{report_id}/download", summary="下载 Allure 报告压缩包")
def download_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """下载完整报告压缩包。"""
    path = _SERVICE.report_archive(db, report_id, user)
    return FileResponse(path, media_type="application/zip", filename=f"allure-{report_id}.zip")


@router.get("/automation-reports/{report_id}/content/{token}/{file_path:path}", summary="读取 Allure 报告文件")
def report_file(report_id: int, token: str, file_path: str, db: Session = Depends(get_db)):
    """按短期凭据返回报告静态文件。"""
    path = _SERVICE.open_report_file(db, report_id, token, file_path)
    return FileResponse(path, media_type=_MEDIA.get(path.suffix.lower(), "application/octet-stream"), headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "frame-ancestors 'self'; base-uri 'none'; object-src 'none'",
        "X-Frame-Options": "SAMEORIGIN",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "private, max-age=60",
    })


@router.post("/automation-callbacks/{callback_key}", response_model=CallbackResponse, summary="接收云效执行回传")
async def ingest_callback(callback_key: str, request: Request, db: Session = Depends(get_db)):
    """接收云效回传的状态和 Allure 报告。"""
    content_type = request.headers.get("content-type", "")
    report_bytes = b""
    results_bytes = b""
    log_bytes = b""
    if "multipart/form-data" in content_type:
        form = await request.form()
        metadata = str(form.get("metadata") or "")
        report = form.get("report")
        results = form.get("results")
        log = form.get("log")
        if report is not None and hasattr(report, "read"):
            report_bytes = await report.read()
        if results is not None and hasattr(results, "read"):
            results_bytes = await results.read()
        if log is not None and hasattr(log, "read"):
            log_bytes = await log.read()
    else:
        metadata = (await request.body()).decode("utf-8")
    return _SERVICE.ingest_callback(
        db, callback_key, _headers(request), metadata, report_bytes, results_bytes, log_bytes,
    )


@router.get("/automation-callbacks/{callback_key}/history", summary="下载上一份 Allure history")
def callback_history(
    callback_key: str, request: Request, automation_project_id: int = Query(ge=1),
    db: Session = Depends(get_db),
):
    """下载上一份报告的 history，供下一次生成继承趋势。"""
    payload = _SERVICE.history_archive(db, callback_key, automation_project_id, _headers(request))
    return Response(payload, media_type="application/zip", headers={
        "Content-Disposition": "attachment; filename=allure-history.zip",
    })
