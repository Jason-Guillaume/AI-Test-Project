"""Agent 会话 / 消息持久化与 AgentState 重建（§26/§15）。

持久化全部落在自建表（`agent_session` / `agent_message`），**不**使用 langgraph
checkpointer：每次 HTTP 请求由 router 重建完整 AgentState 后做一次全新 invoke，
跑到 `interrupt_before` 或 END 后把新增产物追加为 ASSISTANT 消息并回写 current_stage。
进程重启 / 浏览器刷新后，load_state 从表里重建即可无损恢复（§15）。

`agent_message.metadata_json` 存脱敏后的结构化数据（§20）；待确认 Web 步骤另以
应用层密文保存。发送前经 `sanitizer.sanitize_context` 清洗，不保存完整敏感 prompt。
"""

from __future__ import annotations

import json
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
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import not_found


def create_session(
    db: Session, project_id: int, actor: User, *, title: str | None = None,
    task_run_id: int | None = None, task_agent_instance_id: int | None = None,
) -> AgentSession:
    """建会话。写操作需 project member（不足 403）。"""
    require_writable_project(db, project_id, actor)
    session = AgentSession(
        project_id=project_id, user_id=actor.id, title=title,
        task_run_id=task_run_id, task_agent_instance_id=task_agent_instance_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, project_id: int, user: User) -> list[AgentSession]:
    """列出项目内会话（按更新时间倒序）。viewer+ 可见。"""
    get_project_or_404(db, project_id, user)
    return (
        db.query(AgentSession)
        .filter(AgentSession.project_id == project_id, AgentSession.task_run_id.is_(None))
        .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
        .all()
    )


def get_session_or_404(db: Session, session_id: int, user: User) -> AgentSession:
    """取会话并校验项目可见性（viewer+）；不存在 / 不可见统一 404（§33）。"""
    session = db.get(AgentSession, session_id)
    if session is None or session.task_run_id is not None:
        raise not_found("会话不存在")
    get_project_or_404(db, session.project_id, user)
    return session


def get_session_for_write(db: Session, session_id: int, actor: User) -> AgentSession:
    """取会话并校验可写（member+）：发消息 / 删会话用。"""
    session = db.get(AgentSession, session_id)
    if session is None or session.task_run_id is not None:
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


def claim_web_proposal(db: Session, session_id: int) -> dict[str, Any] | None:
    """原子领取待确认步骤；真实 WebStep 只从加密消息载荷中解密，不用脱敏投影执行。"""
    message = (
        db.query(AgentMessage)
        .filter_by(session_id=session_id, message_type="WEB_AGENT_STEP")
        .order_by(AgentMessage.id.desc())
        .with_for_update()
        .populate_existing()
        .first()
    )
    if message is None:
        return None
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "PROPOSED":
        return None
    blob = metadata.get("pending_step_blob")
    if not isinstance(blob, str) or not blob:
        return None
    try:
        from app.features.web_ui.schemas import WebStep

        step = json.loads(decrypt_secret(blob))
        WebStep.model_validate(step)
    except Exception as exc:  # noqa: BLE001 — 密文损坏时不能执行占位值
        raise ValueError("待确认步骤无法安全读取，请重新提出步骤") from exc
    metadata["pending_status"] = "EXECUTING"
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()
    return {"message_id": message.id, "step": step}


def finish_web_proposal(db: Session, session_id: int, message_id: int, *, status: str) -> None:
    """更新已领取提案的最终状态并清除密文副本。"""
    if status not in {"ACCEPTED", "FAILED"}:
        raise ValueError("非法的 Web 提案终态")
    message = (
        db.query(AgentMessage)
        .filter_by(id=message_id, session_id=session_id, message_type="WEB_AGENT_STEP")
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if message is None:
        raise ValueError("待执行提案不存在")
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "EXECUTING":
        raise ValueError("待执行提案已被处理")
    metadata["pending_status"] = status
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()


def reject_web_proposal(db: Session, session_id: int) -> None:
    """驳回当前待确认提案，避免刷新后再次出现或被重复确认。"""
    message = (
        db.query(AgentMessage)
        .filter_by(session_id=session_id, message_type="WEB_AGENT_STEP")
        .order_by(AgentMessage.id.desc())
        .with_for_update()
        .populate_existing()
        .first()
    )
    if message is None:
        raise ValueError("待驳回步骤不存在")
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "PROPOSED":
        raise ValueError("待驳回步骤不存在或已处理")
    metadata["pending_status"] = "REJECTED"
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()


def discard_web_proposal(db: Session, session_id: int) -> bool:
    """新消息到达时作废尚未确认的旧提案，避免旧动作跨目标继续执行。

    返回是否实际作废；已领取或已处理的步骤保持其现有终态。
    """
    message = (
        db.query(AgentMessage)
        .filter_by(session_id=session_id, message_type="WEB_AGENT_STEP")
        .order_by(AgentMessage.id.desc())
        .with_for_update()
        .populate_existing()
        .first()
    )
    if message is None:
        return False
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "PROPOSED":
        return False
    metadata["pending_status"] = "REJECTED"
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()
    return True


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
        """读取会话中的最新消息。"""
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
        # 高风险确认待办随用例一起恢复：materializer 写入，刷新后工作区仍要给出
        # confirm_security_risk 按钮，否则用户看不到「执行前需人工确认」的提示。
        state["security_risk_pending"] = cases_meta.get("security_risk_pending")

    sec_meta = latest("SECURITY_PLAN")
    if sec_meta:
        state["security_plan"] = sec_meta.get("plan")
        state["security_plan_id"] = sec_meta.get("plan_id")
        state["security_strategy_keys"] = sec_meta.get("strategy_keys") or []
        state["target_type"] = sec_meta.get("target_type")
        state["target_ids"] = sec_meta.get("target_ids") or []
        # 安全上下文跨轮次保留（confirm_security_plan 时 materializer 需要重放 preview）
        state["security_context"] = sec_meta.get("context")

    scan_meta = latest("SECURITY_SCAN_PLAN")
    if scan_meta:
        # 旧版扫描工作区字段继续读取，用于历史会话兼容；当前图不再注册扫描节点。
        state["zap_scan_plan"] = scan_meta.get("plan")
        state["zap_scan_job_id"] = scan_meta.get("job_id")

    step_meta = latest("WEB_AGENT_STEP")
    if step_meta:
        # Web 智能体二轮：会话绑定、目标与步数预算跨轮次恢复。提案列表供 promote
        # 提升为正式用例，当前待确认提案决定 web_step_review 暂停点能否执行。
        # 键名刻意不用 session_id：metadata 落库前经 sanitize_context 清洗，
        # session_id 属敏感字段名会被掩成 ******，跨轮次就丢绑定。
        state["web_agent_session_id"] = step_meta.get("browser_id")
        state["web_goal"] = step_meta.get("goal")
        state["web_step_budget"] = step_meta.get("budget") or 20  # 与会话默认一致
        state["web_proposed_steps"] = step_meta.get("steps") or []
        state["web_current_step"] = step_meta.get("current_step")
        state["web_last_decision"] = step_meta.get("last_decision")
        state["web_observe_count"] = step_meta.get("observe_count") or 0
        # 对话消息里的 current_step 是脱敏投影，不能作为执行参数。刷新恢复时只从
        # 应用层加密的载荷解密待确认步骤；旧消息或已领取提案一律不再显示为可执行。
        if step_meta.get("pending_status") == "PROPOSED" and step_meta.get("pending_step_blob"):
            try:
                state["web_current_step"] = json.loads(decrypt_secret(step_meta["pending_step_blob"]))
            except Exception:  # noqa: BLE001 — 损坏载荷关闭确认入口，不回退到脱敏占位值
                state["web_current_step"] = None
        elif state.get("web_current_step"):
            state["web_current_step"] = None

    obs_meta = latest("WEB_OBSERVATION")
    if obs_meta:
        # 只恢复语义树与元信息（不含截图）；执行下一步前会重新观测真实页面。
        state["web_current_observation"] = obs_meta.get("observation")

    result_meta = latest("RESULT")
    if result_meta:
        state["analysis"] = result_meta.get("analysis")
        # 未关闭 Finding 摘要由 result_analyzer 挂在 analysis 上，这里同步到顶层键。
        state["security_finding_brief"] = (result_meta.get("analysis") or {}).get(
            "security_findings", [],
        ) or []

    exec_meta = latest("EXECUTION")
    if exec_meta:
        state["test_run_id"] = exec_meta.get("run_id")
        state["execution_result"] = exec_meta.get("run")

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


# Web 步骤里承载真实值（含 ${data.auth_*} 一类敏感变量引用）的字段：只写不回显。
_WEB_STEP_SECRET_FIELDS = ("value", "expected", "upload")
_WEB_STEP_MASK = "[已脱敏]"


def redact_web_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 Web 步骤里承载真实值的字段掩掉，供 agent_message.metadata_json 落库。

    执行结果中的断言 actual / expected 也要掩，避免页面内容通过结果字段回显；运行日志
    已在 Playwright 层按会话秘密清洗。遮罩后仍保留 operation / locator / status 供页面展示。
    """
    masked: list[dict[str, Any]] = []
    for step in steps:
        # 非 dict 条目原样保留：预算守卫只数长度，不因类型问题炸掉整轮留痕。
        if not isinstance(step, dict):
            masked.append(step)
            continue
        item = dict(step)
        for field in _WEB_STEP_SECRET_FIELDS:
            if item.get(field) not in (None, ""):
                item[field] = _WEB_STEP_MASK
        result = item.get("result")
        if isinstance(result, dict) and any(result.get(k) for k in _WEB_STEP_SECRET_FIELDS):
            result = dict(result)
            for field in _WEB_STEP_SECRET_FIELDS:
                if result.get(field) not in (None, ""):
                    result[field] = _WEB_STEP_MASK
        elif isinstance(result, dict):
            result = dict(result)
        if isinstance(result, dict):
            # 断言实际值可能含页面个人信息，不能因字段名不是 value 而回显。
            assertions = result.get("assertions")
            if isinstance(assertions, list):
                result["assertions"] = [
                    {
                        **assertion,
                        **{
                            key: _WEB_STEP_MASK
                            for key in ("actual", "expected")
                            if assertion.get(key) not in (None, "")
                        },
                    }
                    if isinstance(assertion, dict) else assertion
                    for assertion in assertions
                ]
            item["result"] = result
        masked.append(item)
    return masked


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
                    # 高风险确认待办（materializer / security_risk_confirm 写入），
                    # 供刷新恢复后重建工作区按钮。
                    "security_risk_pending": final.get("security_risk_pending"),
                },
            )
        )

    # 安全计划：preview 的预览项（确认前不落 TestCase）；人工确认后 materializer 追加
    # TEST_CASES 消息，本消息留作「哪几条预览项被接受」的追溯。
    if _points_changed(initial, final, "security_plan") or (
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
    if _points_changed(initial, final, "zap_scan_plan") or (
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
            _points_changed(initial, final, key)
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

    if _points_changed(initial, final, "web_current_observation") or (
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
