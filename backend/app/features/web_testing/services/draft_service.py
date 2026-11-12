"""Web 用例草稿生成服务。

复用 Agent 模型提供方与既有 Web UI、业务流程服务；只保存未确认的 AI 草稿，
正式执行仍由原 Web UI 确认与执行服务控制。
"""
from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.llm import LLMError
from app.llm.providers import ProductionLLMProvider
from app.agents.browser_authoring.draft_generator import generate_web_step_candidate
from app.core.security.sanitizer import sanitize_context
from app.features.business.models.business_flow import BusinessFlow
from app.platform.projects.services.access_service import get_project_or_404
from app.features.business.services.flow_service import FlowService
from app.platform.projects.services.access_service import require_writable_project
from app.features.web_testing.schemas import CaseInput
from app.features.web_testing.services.web_ui_service import WebUIService
from app.core.http.errors import AppError, bad_request, not_found


def generate_draft(db: Session, project_id: int, body, actor, provider=None):
    """生成并保存 Web UI 未确认草稿，保留项目写权限与人工审核门槛。"""
    require_writable_project(db, project_id, actor)
    service = WebUIService()
    pages = service.list_pages(db, project_id, actor)["items"]
    if body.page_object_ids:
        wanted = set(body.page_object_ids)
        pages = [page for page in pages if page["id"] in wanted]
        if len(pages) != len(wanted):
            raise bad_request("生成请求包含不可见页面对象")
    if not pages:
        raise bad_request("请先创建页面对象，提供稳定的页面元素")
    flow = None
    if body.flow_id:
        get_project_or_404(db, project_id, actor)
        flow_row = db.get(BusinessFlow, body.flow_id)
        if flow_row is None or flow_row.project_id != project_id:
            raise not_found("业务流程不存在")
        flow = FlowService().get_flow_detail(db, body.flow_id, actor).model_dump(mode="json")
    context = sanitize_context({"instruction": body.instruction, "pages": pages, "business_flow": flow})
    try:
        raw = generate_web_step_candidate(context, provider or ProductionLLMProvider(db))
        draft = CaseInput.model_validate(raw)
        if draft.auth_profile_id:
            raise bad_request("Agent 草稿不可选择或修改认证配置，请人工配置")
        return service.save_case(db, project_id, draft, actor, source_type="AI")
    except LLMError as exc:
        raise AppError("Web 步骤生成失败，请检查默认模型配置", status_code=400, code=exc.code) from exc
    except (ValueError, ValidationError) as exc:
        raise bad_request("模型返回的 Web 步骤不符合结构化契约") from exc
