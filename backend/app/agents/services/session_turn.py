"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from sqlalchemy.orm import Session
from app.agents.models.message import AgentMessage
from app.agents.models.session import AgentSession
from app.agents.workflows.legacy.state import AgentState
from app.core.security.crypto import encrypt_secret
from app.agents.services.message_store import append_message
from app.agents.services.session_response import redact_web_steps


def points_changed(before: AgentState, after: AgentState, key: str) -> bool:
    """判断产物是否本轮新增 / 变更（用于决定是否追加消息，避免重复刷消息）。"""
    prev, new = before.get(key), after.get(key)
    if new is None or new == [] or new is False:
        return False
    return prev != new


def persist_turn(
    db: Session,
    session: AgentSession,
    *,
    initial: AgentState,
    final: AgentState,
) -> list[AgentMessage]:
    """把本轮 invoke 的新增产物追加为 ASSISTANT 消息，并回写 current_stage / status。

    只追加「本轮新增或变更」的产物（与 initial 比对），避免每次 invoke 重复刷同一条
    消息。错误与澄清同理：仅当相对 initial 变化时才追加。
    """
    emitted: list[AgentMessage] = []

    if points_changed(initial, final, "test_plan"):
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="TEST_PLAN",
                content="已生成测试计划",
                metadata={
                    "plan": final.get("test_plan"),
                    "intent": final.get("intent"),
                    "target_type": final.get("target_type"),
                    "target_ids": final.get("target_ids", []),
                    # 持久化上下文（已脱敏），供 load_state 跨轮次重建（§6/§7/§8）
                    "api_context": final.get("api_context"),
                    "business_context": final.get("business_context"),
                    "strategy_context": final.get("strategy_context"),
                    "existing_test_context": final.get("existing_test_context"),
                },
            )
        )

    if points_changed(initial, final, "generated_test_points"):
        points = final.get("generated_test_points") or []
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="TEST_POINTS",
                content=f"已生成 {len(points)} 条测试点",
                metadata={
                    "points": points,
                    "confirmed_point_ids": final.get("confirmed_point_ids", []),
                },
            )
        )

    if points_changed(initial, final, "generated_test_cases"):
        cases = final.get("generated_test_cases") or []
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="TEST_CASES",
                content=f"已生成 {len(cases)} 条测试用例",
                metadata={
                    "cases": cases,
                    "confirmed_case_ids": final.get("confirmed_case_ids", []),
                    # 高风险确认待办（materializer / security_risk_confirm 写入），
                    # 供刷新恢复后重建工作区按钮。
                    "security_risk_pending": final.get("security_risk_pending"),
                },
            )
        )

    # 安全计划：preview 的预览项（确认前不落 TestCase）；人工确认后 materializer 追加
    # TEST_CASES 消息，本消息留作「哪几条预览项被接受」的追溯。
    if points_changed(initial, final, "security_plan") or (
        final.get("security_plan_id") != initial.get("security_plan_id")
    ):
        plan = final.get("security_plan") or {}
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="SECURITY_PLAN",
                content=f"已生成安全计划（{len(plan.get('items') or [])} 条预览项，待确认）",
                metadata={
                    "plan": plan,
                    "plan_id": final.get("security_plan_id"),
                    "strategy_keys": final.get("security_strategy_keys") or [],
                    "target_type": final.get("target_type"),
                    "target_ids": final.get("target_ids") or [],
                    # 持久化安全上下文，供跨轮次重建（confirm_security_plan 复用）
                    "context": final.get("security_context"),
                },
            )
        )

    # ZAP 扫描计划（Phase 2，§二十三）：计划预览先落一条待确认消息；人工确认后
    # 同一个键更新为 confirmed=True + job_id，再落一条创建结果。approval_note 不
    # 入这里——它只在扫描任务表上留痕，避免在对话消息里重复保存批准理由。
    if points_changed(initial, final, "zap_scan_plan") or (
        final.get("zap_scan_job_id") != initial.get("zap_scan_job_id")
    ):
        plan = final.get("zap_scan_plan") or {}
        job_id = final.get("zap_scan_job_id")
        if job_id:
            text = f"扫描任务 #{job_id} 已创建"
        else:
            target = (plan.get("target") or {}).get("name") or "目标"
            intensity = "主动" if plan.get("is_active_scan") else "被动"
            text = f"已生成扫描计划（{intensity}扫描，目标：{target}），待确认"
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="SECURITY_SCAN_PLAN",
                content=text,
                metadata={
                    "plan": plan,
                    "job_id": job_id,
                    "target_id": plan.get("target_id"),
                    "scan_profile_id": plan.get("scan_profile_id"),
                },
            )
        )

    # Web 智能体二轮：步骤提案（含当前待确认项）与页面观测分两条消息留痕。
    # 提案按「列表或待确认项变化」触发（首次提案时列表仍为空，靠 current_step 兜住）；
    # 观测每次都会变，落库时截断语义树且不含截图。
    #
    # 加密边界：agent_message.metadata_json 对会话内所有 viewer 明文可读。这里仅保存
    # 不带真实值的步骤投影；待确认步骤另存应用层密文，刷新恢复时必须解密后才能执行。
    # 凭据类字段（value / expected / upload）与执行结果中的同名字段一律掩码。
    # 已执行步骤仍写入加密的 web_agent_step；本轮 workspace 只供当前项目成员查看。
    if (
        initial.get("web_state_reset") or final.get("web_state_reset")
        or initial.get("web_current_step") != final.get("web_current_step")
        or any(
            points_changed(initial, final, key)
            for key in (
                "web_agent_session_id", "web_goal", "web_proposed_steps",
                "web_observe_count",
            )
        )
    ):
        steps = redact_web_steps(final.get("web_proposed_steps") or [])
        pending = redact_web_steps([final["web_current_step"]])[0] if final.get("web_current_step") else None
        pending_step = final.get("web_current_step")
        text = f"已执行 {len(steps)} 步"
        if pending:
            text += f"，另有 1 步待确认（{pending.get('operation') or '?'}）"
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="WEB_AGENT_STEP",
                content=text,
                metadata={
                    # 键名不用 session_id：sanitize_context 会把敏感字段名掩码掉，
                    # 跨轮次恢复时就拿不到真实会话 ID。
                    "browser_id": final.get("web_agent_session_id"),
                    "goal": final.get("web_goal"),
                    "budget": final.get("web_step_budget"),
                    "steps": steps,
                    "steps_redacted": True,
                    "current_step": pending,
                    "pending_step_blob": encrypt_secret(json.dumps(
                        pending_step, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    )) if pending_step else None,
                    "pending_status": "PROPOSED" if pending_step else None,
                    "last_decision": final.get("web_last_decision"),
                    "observe_count": final.get("web_observe_count"),
                },
            )
        )

    if points_changed(initial, final, "web_current_observation") or (
        (initial.get("web_state_reset") or final.get("web_state_reset"))
        and final.get("web_current_observation") is None
    ):
        obs = final.get("web_current_observation") or {}
        observation = None
        if obs:
            observation = {
                "url": obs.get("url"),
                "title": obs.get("title"),
                "accessibility_tree": (obs.get("accessibility_tree") or "")[:2000],
            }
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="WEB_OBSERVATION",
                content=(
                    f"页面观测：{obs.get('title') or obs.get('url') or '未知页面'}"
                    if obs else "当前页面观测已清除"
                ),
                # 不含 screenshot_b64：体积大且无追溯价值，遮罩截图只在观测时实时返回。
                metadata={"observation": observation},
            )
        )

    if points_changed(initial, final, "test_run_id"):
        run = final.get("execution_result") or {}
        passed, failed, error = run.get("passed", 0), run.get("failed", 0), run.get("error", 0)
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="EXECUTION",
                content=f"执行完成：{passed} 通过 / {failed} 失败 / {error} 错误",
                metadata={"run": run, "run_id": final.get("test_run_id")},
            )
        )

    if points_changed(initial, final, "analysis"):
        analysis = final.get("analysis") or {}
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="RESULT",
                content=analysis.get("summary") or "已完成结果分析",
                metadata={"analysis": analysis},
            )
        )

    # 报告：本轮新生成 / 重新生成时才追加（regenerate 会产生新的 report_id）。
    if points_changed(initial, final, "report_id") or points_changed(
        initial, final, "report_brief",
    ):
        brief = final.get("report_brief") or {}
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="REPORT",
                content=f"已生成测试报告 {brief.get('report_no') or ''}".strip(),
                # metadata 为脱敏 brief（report_no/风险/通过率/AI 总结），不含 webhook/sign（§31）
                metadata={"report": brief, "report_id": final.get("report_id")},
            )
        )

    # 通知：本轮确实执行了发送 / 跳过时才追加。record_id 每次发送都变，因此重复
    # 点击「发送通知」也会留下新的留痕；跳过则靠 brief 内容变化触发。
    if points_changed(initial, final, "notification_brief") or (
        final.get("notification_record_id") != initial.get("notification_record_id")
    ):
        brief = final.get("notification_brief") or {}
        if brief.get("skipped"):
            text = brief.get("message") or "已跳过飞书通知"
        elif brief.get("status") == "SUCCESS":
            text = f"飞书通知发送成功（{brief.get('channel_name') or '未指定渠道'}）"
        else:
            text = f"飞书通知发送失败：{brief.get('error_message') or '未知错误'}"
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="NOTIFICATION",
                content=text,
                metadata={"notification": brief, "record_id": final.get("notification_record_id")},
            )
        )

    # 澄清：仅当本轮进入 CLARIFY 且带了提问。
    if final.get("current_stage") == "CLARIFY" and final.get("clarify_question"):
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="CLARIFY",
                content=final["clarify_question"], metadata={},
            )
        )

    # 错误：仅当相对 initial 出现新错误。
    if final.get("error") and final["error"] != initial.get("error"):
        emitted.append(
            append_message(
                db, session.id, role="SYSTEM", message_type="TEXT",
                content=final["error"].get("message") or "处理失败",
                metadata={"error": final["error"]},
            )
        )

    # 首条消息后补会话标题（便于列表展示）。
    if not session.title and initial.get("user_message"):
        session.title = initial["user_message"].strip()[:50]

    stage = final.get("current_stage") or session.current_stage
    session.current_stage = stage
    if stage == "COMPLETED":
        session.status = "COMPLETED"
    elif stage == "FAILED":
        session.status = "FAILED"
    db.commit()
    return emitted
