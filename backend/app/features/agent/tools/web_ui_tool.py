"""Agent Web 工具：读取项目页面/流程生成结构化草稿；不暴露人工确认或执行工具。"""
import json
from pydantic import ValidationError
from app.features.agent.providers.llm_provider import LLMError, ProductionLLMProvider
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.agent.tools.business_tool import get_flow_detail
from app.features.web_ui.schemas import CaseInput
from app.features.web_ui.services.web_ui_service import WebUIService
from app.features.test_management.services._access import require_writable_project
from app.shared.errors import AppError, bad_request

SYSTEM = """你是测试开发平台的 Web UI 步骤生成助手。仅返回一个 JSON 对象：
{name,description,steps:[{name,operation,locator?,page_object_id?,element_key?,value?,assertion?,operator?,expected?,sensitive?}]}。
operation 仅 NAVIGATE/CLICK/FILL/SELECT/UPLOAD/WAIT/ASSERT；优先 TEST_ID、ROLE、LABEL、TEXT。
locator 为 {strategy,value,name?,exact?}。只引用提供的页面元素，不能猜测真实页面 DOM。
NAVIGATE 使用页面 path；密码只使用 ${data.auth_password} 且 sensitive=true。
禁止 Python、JavaScript、evaluate、脚本、SQL、命令、凭据和任意执行代码。只生成草稿，人工审核后执行。
"""


def generate_draft(db, project_id, body, actor, provider=None):
    """复用平台 LLMProvider 和业务上下文；Pydantic 二次校验后保存未确认 AI 草稿。"""
    require_writable_project(db, project_id, actor)
    service = WebUIService()
    pages = service.list_pages(db, project_id, actor)["items"]
    if body.page_object_ids:
        wanted = set(body.page_object_ids)
        pages = [p for p in pages if p["id"] in wanted]
        if len(pages) != len(wanted):
            raise bad_request("生成请求包含不可见页面对象")
    if not pages:
        raise bad_request("请先创建页面对象，提供稳定的页面元素")
    flow = get_flow_detail(db, body.flow_id, actor, project_id=project_id) if body.flow_id else None
    context = sanitize_context({"instruction": body.instruction, "pages": pages, "business_flow": flow})
    try:
        raw = (provider or ProductionLLMProvider(db)).generate_structured(
            SYSTEM, json.dumps(context, ensure_ascii=False), kind="web_ui_steps")
        body = CaseInput.model_validate(raw)
        if body.auth_profile_id:
            raise bad_request("Agent 草稿不可选择或修改认证配置，请人工配置")
        return service.save_case(db, project_id, body, actor, source_type="AI")
    except LLMError as exc:
        raise AppError("Web 步骤生成失败，请检查默认模型配置", status_code=400, code=exc.code) from exc
    except (ValueError, ValidationError) as exc:
        raise bad_request("模型返回的 Web 步骤不符合结构化契约") from exc
