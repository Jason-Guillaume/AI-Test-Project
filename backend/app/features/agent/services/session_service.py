"""Agent 会话 / 消息持久化与 AgentState 重建（§26/§15）。

持久化全部落在自建表（`agent_session` / `agent_message`），**不**使用 langgraph
checkpointer：每次 HTTP 请求由 router 重建完整 AgentState 后做一次全新 invoke，
跑到 `interrupt_before` 或 END 后把新增产物追加为 ASSISTANT 消息并回写 current_stage。
进程重启 / 浏览器刷新后，load_state 从表里重建即可无损恢复（§15）。

`agent_message.metadata_json` 只存脱敏后的结构化数据（§20）：发送前经
`sanitizer.sanitize_context` 清洗，不保存完整敏感 prompt 内容。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.agent.models.agent_message import AgentMessage
from app.features.agent.models.agent_session import AgentSession
from app.features.agent.providers.sanitizer import sanitize_context, sanitize_text
from app.features.agent.state import AgentState, make_initial_state
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
)
from app.models.identity import User
from app.shared.errors import not_found


def create_session(db: Session, project_id: int, actor: User, *, title: str | None = None) -> AgentSession:
    """建会话。写操作需 project member（不足 403）。"""
    require_writable_project(db, project_id, actor)
    session = AgentSession(project_id=project_id, user_id=actor.id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, project_id: int, user: User) -> list[AgentSession]:
    """列出项目内会话（按更新时间倒序）。viewer+ 可见。"""
    get_project_or_404(db, project_id, user)
    return (
        db.query(AgentSession)
        .filter(AgentSession.project_id == project_id)
        .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
        .all()
    )


def get_session_or_404(db: Session, session_id: int, user: User) -> AgentSession:
    """取会话并校验项目可见性（viewer+）；不存在 / 不可见统一 404（§33）。"""
    session = db.get(AgentSession, session_id)
    if session is None:
        raise not_found("会话不存在")
    get_project_or_404(db, session.project_id, user)
    return session


def get_session_for_write(db: Session, session_id: int, actor: User) -> AgentSession:
    """取会话并校验可写（member+）：发消息 / 删会话用。"""
    session = db.get(AgentSession, session_id)
    if session is None:
        raise not_found("会话不存在")
    require_writable_project(db, session.project_id, actor)
    return session


def delete_session(db: Session, session_id: int, actor: User) -> None:
    """删会话（连带消息，agent_message.session_id 外键 ON DELETE CASCADE）。"""
    session = get_session_for_write(db, session_id, actor)
    db.delete(session)
    db.commit()


def append_message(
    db: Session,
    session_id: int,
    *,
    role: str,
    message_type: str,
    content: str | None,
    metadata: dict[str, Any] | None = None,
) -> AgentMessage:
    """追加一条消息。content / metadata 均脱敏后落库（§20/§34）。"""
    msg = AgentMessage(
        session_id=session_id,
        role=role,
        message_type=message_type,
        content=sanitize_text(content),
        metadata_json=sanitize_context(metadata) if metadata is not None else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages(db: Session, session_id: int) -> list[AgentMessage]:
    """按时间升序取会话全部消息。"""
    return (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.id.asc())
        .all()
    )


def next_generation_version(db: Session, session_id: int, *, message_type: str) -> int:
    """本轮生成版本号 = 该类型历史消息条数 + 1。

    写入 test_point/test_case.generation_version 用于追溯「第几轮生成」（§11）。
    使用 with_for_update 加行锁防止并发请求返回重复版本号。
    """
    # 对 session 行加行锁，确保同一 session 同时只有一个请求执行
    db.query(AgentSession).filter(AgentSession.id == session_id).with_for_update().one_or_none()
    count = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id, AgentMessage.message_type == message_type)
        .count()
    )
    return int(count) + 1


def load_state(db: Session, session: AgentSession) -> AgentState:
    """从 agent_session + agent_message 重建 AgentState（刷新 / 续轮恢复，§15）。

    重建口径：current_stage 取会话行；各产物取**该类型最新一条** ASSISTANT 消息的
    metadata_json（再生成会追加新消息，旧消息保留在历史中）。消息历史取最近 8 条
    供 prompt 使用（脱敏，已在上游 sanitize）。
    """
    msgs = list_messages(db, session.id)
    state = make_initial_state(session.project_id, session.user_id, session.id)
    state["current_stage"] = session.current_stage

    def latest(msg_type: str) -> dict[str, Any] | None:
        for m in reversed(msgs):
            if m.message_type == msg_type and m.metadata_json:
                return m.metadata_json
        return None

    plan_meta = latest("TEST_PLAN")
    if plan_meta:
        state["test_plan"] = plan_meta.get("plan")
        state["intent"] = plan_meta.get("intent")
        state["target_type"] = plan_meta.get("target_type")
        state["target_ids"] = plan_meta.get("target_ids", [])
        # 跨轮次恢复被测上下文（confirm_points / regenerate_* 时复用）
        state["api_context"] = plan_meta.get("api_context")
        state["business_context"] = plan_meta.get("business_context")
        state["strategy_context"] = plan_meta.get("strategy_context") or []
        state["existing_test_context"] = plan_meta.get("existing_test_context")

    pts_meta = latest("TEST_POINTS")
    if pts_meta:
        state["generated_test_points"] = pts_meta.get("points", [])
        state["confirmed_point_ids"] = pts_meta.get("confirmed_point_ids", [])

    cases_meta = latest("TEST_CASES")
    if cases_meta:
        state["generated_test_cases"] = cases_meta.get("cases", [])
        state["confirmed_case_ids"] = cases_meta.get("confirmed_case_ids", [])

    exec_meta = latest("EXECUTION")
    if exec_meta:
        state["test_run_id"] = exec_meta.get("run_id")
        state["execution_result"] = exec_meta.get("run")

    result_meta = latest("RESULT")
    if result_meta:
        state["analysis"] = result_meta.get("analysis")

    report_meta = latest("REPORT")
    if report_meta:
        state["report_id"] = report_meta.get("report_id")
        state["report_brief"] = report_meta.get("report")

    notif_meta = latest("NOTIFICATION")
    if notif_meta:
        state["notification_record_id"] = notif_meta.get("record_id")
        state["notification_brief"] = notif_meta.get("notification")

    # prompt 消息历史：只保留 role + content（已脱敏），最近 8 条控制 token。
    state["messages"] = [
        {"role": m.role, "content": m.content}
        for m in msgs if m.content
    ][-8:]
    return state


def _points_changed(before: AgentState, after: AgentState, key: str) -> bool:
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

    if _points_changed(initial, final, "test_plan"):
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

    if _points_changed(initial, final, "generated_test_points"):
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

    if _points_changed(initial, final, "generated_test_cases"):
        cases = final.get("generated_test_cases") or []
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="TEST_CASES",
                content=f"已生成 {len(cases)} 条测试用例",
                metadata={
                    "cases": cases,
                    "confirmed_case_ids": final.get("confirmed_case_ids", []),
                },
            )
        )

    if _points_changed(initial, final, "test_run_id"):
        run = final.get("execution_result") or {}
        passed, failed, error = run.get("passed", 0), run.get("failed", 0), run.get("error", 0)
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="EXECUTION",
                content=f"执行完成：{passed} 通过 / {failed} 失败 / {error} 错误",
                metadata={"run": run, "run_id": final.get("test_run_id")},
            )
        )

    if _points_changed(initial, final, "analysis"):
        analysis = final.get("analysis") or {}
        emitted.append(
            append_message(
                db, session.id, role="ASSISTANT", message_type="RESULT",
                content=analysis.get("summary") or "已完成结果分析",
                metadata={"analysis": analysis},
            )
        )

    # 报告：本轮新生成 / 重新生成时才追加（regenerate 会产生新的 report_id）。
    if _points_changed(initial, final, "report_id") or _points_changed(
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
    if _points_changed(initial, final, "notification_brief") or (
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
