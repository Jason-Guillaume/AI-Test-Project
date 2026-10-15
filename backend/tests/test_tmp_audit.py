"""临时审计验证脚本。"""

from __future__ import annotations

from tests.test_16_agent import (
    _create_api,
    _create_project,
    _create_session_http,
    _create_strategy,
    _full_responses,
    _get_session_obj,
    _get_user,
    _make_fake,
)

from app.features.agent.graph import run_agent
from app.features.agent.services import session_service


def test_context_survives_turn(api, admin, db):
    pid = _create_project(api, admin)
    api_id = _create_api(api, admin, pid)
    _create_strategy(api, admin, pid)
    sid = _create_session_http(api, admin, pid)
    session_obj = _get_session_obj(db, sid)
    user = _get_user(db, admin)
    fake = _make_fake()
    resp = _full_responses(api_id)
    fake.set_response("intent", resp["intent"])
    fake.set_response("test_plan", resp["test_plan"])
    fake.set_response("test_points", resp["test_points"])

    state1, _ = run_agent(db, session_obj, user, fake, content="生成测试点")
    point_id = state1["generated_test_points"][0]["id"]

    rebuilt = session_service.load_state(db, session_obj)
    print("REBUILT:", {
        k: (rebuilt.get(k) is not None and rebuilt.get(k) != [] and rebuilt.get(k) != {})
        for k in ("api_context", "business_context", "strategy_context",
                  "existing_test_context", "test_plan", "target_ids")
    })

    fake.set_response("test_cases", _full_responses(api_id, point_id=point_id)["test_cases"])
    state2, _ = run_agent(db, session_obj, user, fake, action="confirm_points")
    call = [c for c in fake.calls if c["kind"] == "test_cases"][-1]
    print("STATE2_stage:", state2["current_stage"])
    print("CASE_PROMPT_HAS_API:", str(state1.get("api_context"))[:60] in call["user"])
    print("CASE_PROMPT_SNIP:", call["user"][:400])

    # regenerate_points 是否也有上下文
    fake.set_response("test_points", resp["test_points"])
    state3, _ = run_agent(db, session_obj, user, fake, action="regenerate_points")
    call3 = [c for c in fake.calls if c["kind"] == "test_points"][-1]
    print("REGEN_HAS_API_CONTEXT:", "null" in call3["user"][:200])


def test_generate_test_cases_intent(api, admin, db):
    pid = _create_project(api, admin)
    api_id = _create_api(api, admin, pid)
    sid = _create_session_http(api, admin, pid)
    session_obj = _get_session_obj(db, sid)
    user = _get_user(db, admin)
    fake = _make_fake()
    fake.set_response("intent", {
        "intent": "GENERATE_TEST_CASES", "target_type": "API",
        "target_ids": [api_id], "target_description": "生成用例",
    })
    state, msgs = run_agent(db, session_obj, user, fake, content="帮我生成测试用例")
    print("GEN_CASES stage:", state["current_stage"], "intent:", state["intent"],
          "error:", state.get("error"), "n_msgs:", len(msgs))
    db.refresh(session_obj)
    print("GEN_CASES session_stage:", session_obj.current_stage, "status:", session_obj.status)

    sid2 = _create_session_http(api, admin, pid)
    session_obj2 = _get_session_obj(db, sid2)
    fake.set_response("intent", {
        "intent": "EXECUTE_EXISTING_CASES", "target_type": "API",
        "target_ids": [api_id], "target_description": "执行用例",
    })
    state4, msgs4 = run_agent(db, session_obj2, user, fake, content="执行已有用例")
    print("EXEC_EXIST stage:", state4["current_stage"], "error:", state4.get("error"),
          "n_msgs:", len(msgs4))
    db.refresh(session_obj2)
    print("EXEC_EXIST session_stage:", session_obj2.current_stage, "status:", session_obj2.status)


def test_confirm_points_on_fresh_session(api, admin, db):
    pid = _create_project(api, admin)
    sid = _create_session_http(api, admin, pid)
    session_obj = _get_session_obj(db, sid)
    user = _get_user(db, admin)
    fake = _make_fake()
    state, msgs = run_agent(db, session_obj, user, fake, action="confirm_points")
    print("FRESH_CONFIRM stage:", state["current_stage"], "cases:", len(state["generated_test_cases"]),
          "error:", state.get("error"), "n_msgs:", len(msgs))
