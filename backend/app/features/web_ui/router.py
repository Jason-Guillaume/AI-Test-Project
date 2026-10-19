"""Web UI 管理路由；同步调用服务层，所有执行均要求平台 JWT 与项目写权限。"""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from app.shared.auth import get_current_user
from app.shared.dependencies import get_db
from app.models.identity import User
from app.features.web_ui.schemas import AuthInput, BindingInput, CaseInput, ConfirmInput, DebugInput, GenerateInput, PageInput, CaseResponse, PageResponse, AuthResponse
from app.features.web_ui.services.web_ui_service import WebUIService
from app.features.test_management.schemas import TestRunResponse

router = APIRouter(tags=["Web UI 自动化"])
service = WebUIService()



@router.get("/projects/{project_id}/web-pages")
def pages(project_id: int, page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出页面对象。"""
    return service.list_pages(db, project_id, user, page=page, page_size=page_size)


@router.post("/projects/{project_id}/web-pages", status_code=201, response_model=PageResponse)
def create_page(project_id: int, body: PageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """创建页面与命名定位器。"""
    return service.save_page(db, project_id, body, user)


@router.put("/projects/{project_id}/web-pages/{page_id}", response_model=PageResponse)
def update_page(project_id: int, page_id: int, body: PageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按 revision 更新页面。"""
    return service.save_page(db, project_id, body, user, page_id)


@router.delete("/web-pages/{page_id}", status_code=204)
def delete_page(page_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除页面对象。"""
    service.delete_page(db, page_id, user)


@router.get("/projects/{project_id}/web-cases")
def cases(project_id: int, page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出 Web 用例。"""
    return service.list_cases(db, project_id, user, page=page, page_size=page_size)


@router.get("/web-cases/{case_id}", response_model=CaseResponse)
def case_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取用例与已脱离密文存储结构的步骤。"""
    return service.get_case(db, case_id, user)


@router.post("/projects/{project_id}/web-cases", status_code=201, response_model=CaseResponse)
def create_case(project_id: int, body: CaseInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """保存未确认的结构化用例。"""
    return service.save_case(db, project_id, body, user)


@router.put("/projects/{project_id}/web-cases/{case_id}", response_model=CaseResponse)
def update_case(project_id: int, case_id: int, body: CaseInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """原子保存、重排步骤并使旧确认失效。"""
    return service.save_case(db, project_id, body, user, case_id)


@router.delete("/web-cases/{case_id}", status_code=204)
def delete_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除测试资产，保留历史结果。"""
    service.delete_case(db, case_id, user)


@router.post("/web-cases/{case_id}/confirm", response_model=CaseResponse)
def confirm(case_id: int, body: ConfirmInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """显式人工确认当前版本。"""
    return service.confirm_case(db, case_id, body.revision, user)


@router.post("/web-cases/{case_id}/debug", response_model=TestRunResponse)
def debug(case_id: int, body: DebugInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """执行完整 TestRun 链路，包括 Fixture、Mock、清理和结果持久化。"""
    return service.debug(db, case_id, body.environment_id, user)


@router.get("/projects/{project_id}/web-auth-profiles")
def auth_profiles(project_id: int, page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """仅列出认证元信息。"""
    return service.list_auth(db, project_id, user, page=page, page_size=page_size)


@router.post("/projects/{project_id}/web-auth-profiles", status_code=201, response_model=AuthResponse)
def create_auth(project_id: int, body: AuthInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """加密保存账号或人工扫码后导入的登录态。"""
    return service.save_auth(db, project_id, body, user)


@router.put("/projects/{project_id}/web-auth-profiles/{auth_id}", response_model=AuthResponse)
def update_auth(project_id: int, auth_id: int, body: AuthInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """整体替换凭据，并使引用用例的旧确认失效。"""
    return service.save_auth(db, project_id, body, user, auth_id)


@router.delete("/web-auth-profiles/{auth_id}", status_code=204)
def delete_auth(auth_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """撤销已保存会话。"""
    service.delete_auth(db, auth_id, user)


@router.get("/projects/{project_id}/web-executions")
def history(project_id: int, case_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """查询既有执行记录。"""
    return service.history(db, project_id, user, case_id=case_id, page=page, page_size=page_size)


@router.get("/web-artifacts/{artifact_id}")
def artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """受项目权限保护的截图/Trace 下载；禁止缓存敏感附件。"""
    row, content = service.artifact(db, artifact_id, user)
    trace = row.kind == "TRACE"
    extension = "zip" if trace else "png"
    return Response(content, media_type="application/zip" if trace else "image/png", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="{row.id}.{extension}"'})


@router.post("/projects/{project_id}/web-agent/draft", status_code=201, response_model=CaseResponse)
def generate(project_id: int, body: GenerateInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Agent 只能生成未确认草稿。"""
    from app.features.agent.tools.web_ui_tool import generate_draft
    return generate_draft(db, project_id, body, user)


@router.post("/business-actions/{action_id}/web-binding", status_code=201)
def bind_action(action_id: int, body: BindingInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """为同项目业务动作绑定 WEB 通道。"""
    return service.bind_action(db, action_id, body.web_case_id, user)


@router.get("/web-artifacts/{artifact_id}/events")
def trace_events(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """授权读取脱敏 Trace 事件，不将登录页面或附件上传到外部 Viewer。"""
    return service.trace_events(db, artifact_id, user)


@router.get("/projects/{project_id}/web-environments")
def environment_options(project_id: int, keyword: str = Query("", max_length=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """项目内执行环境候选，仅返回名称和 ID，不暴露环境凭据。"""
    return service.environment_options(db, project_id, user, keyword)
