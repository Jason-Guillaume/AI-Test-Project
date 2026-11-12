"""将已接受的 Agent 探索步骤提升为未确认的正式 Web 用例。"""

from __future__ import annotations

import json

from app.agents.browser_authoring.services.session_service import get_session_row
from app.agents.models.browser_authoring import WebAgentStep
from app.features.web_testing.schemas import CaseInput, PromoteInput, WebStep
from app.features.web_testing.services.case_service import save_case
from app.core.security.crypto import decrypt_secret
from app.core.http.errors import bad_request, not_found


def promote_session(db, session_id, body: PromoteInput, actor, *, task_run_id: int | None = None):
    """把会话中已接受的步骤提升为正式 Web 用例（未确认草稿）。

    只取 status=ACCEPTED 且来源为 AI 的已执行步骤——被驳回的提案不会进入
    正式用例。会话目标页非空时补一条 NAVIGATE 作为用例首步，保证用例从
    已知入口出发可重放。产物一律 confirmed=false：正式执行仍只走
    save_case → confirm_case → debug，confirmed_digest 门禁不变。
    敏感步骤沿用 WebStep 既有约束：凭据必须写成 ${data.auth_*} 一类变量引用，
    否则在 load_steps 读取时会失败，这里提前拒绝而不是留下坏用例。
    """
    # 提升会在项目内创建用例，属于写操作：入口即按可写项目校验，
    # 不依赖 save_case 内部的校验兜底（防止后续重构漏掉）。
    row = get_session_row(db, session_id, actor, write=True, allow_task_bound=task_run_id is not None)
    if task_run_id is not None and row.task_run_id != task_run_id:
        raise not_found("Web 资源不存在")
    steps = [
        decrypt_secret(r.step_encrypted)
        for r in db.query(WebAgentStep).filter_by(session_id=row.id, status="ACCEPTED", source="AI")
            .order_by(WebAgentStep.sort, WebAgentStep.id).all()
    ]
    decoded: list[WebStep] = []
    for raw in steps:
        data = json.loads(raw) if raw else {}
        if data:
            try:
                decoded.append(WebStep.model_validate(data))
            except (ValueError, Exception) as exc:  # noqa: BLE001
                raise bad_request(f"智能体步骤不符合用例约束，无法提升：{exc}") from exc
    if not decoded:
        raise bad_request("会话内还没有已接受的步骤，无法提升")

    # 沙箱会话是相对路径导航；正式用例从项目目标页根路径可解析，补一条 NAVIGATE。
    target = (row.target_page_path or "").strip()
    if target and decoded[0].operation != "NAVIGATE":
        decoded.insert(0, WebStep(name="打开目标页", operation="NAVIGATE", value=target))

    name = (body.name or "").strip() or f"智能体会话 {row.id} 探索用例"
    return save_case(
        db, row.project_id,
        CaseInput(name=name, description=body.description or "",
                  auth_profile_id=row.auth_profile_id,
                  timeout_ms=body.timeout_ms, total_timeout_ms=body.total_timeout_ms,
                  steps=decoded),
        actor, source_type="AI",
    )


