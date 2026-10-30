"""统一任务 P0–P4 真实 API 集成验收。

本测试通过鉴权 HTTP API 创建任务、确认方案并观察持久化调度；测试用例、出站白名单、RunService、HTTP 执行器与 ReportService 均使用真实实现。
仅模型边界返回可重复的结构化内容，避免依赖外部 LLM 凭据；因此不作为生产模型质量验收。
"""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import inspect, text

from app.features.test_management.models.test_case import TestCase as CaseEntity
from app.core.models.configuration import ModelConfiguration
from tests.conftest import unique
from tests.test_15_test_executor import (
    StubServer,
    _admin_id,
    _create_case,
    _make_env,
    _make_iface,
    _whitelist,
    _create_project,
)
from tests.test_32_web_agent_runtime import target_server, web_setup as web_authoring_web_setup  # noqa: F401

API = "/api/v1"


class DeterministicTaskLLM:
    """只替代外部模型 HTTP 边界，工具、业务服务和数据库链路继续真实执行。"""

    def __init__(self, db, model_config_id=None, *, model_config_ids=None, attempt_callback=None):
        """兼容生产 Provider 构造签名，不读取模型密钥。"""
        self.db = db
        self.model_config_id = model_config_id
        self.model_config_ids = model_config_ids or []
        self.attempt_callback = attempt_callback

    def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None, validator=None):
        """按任务角色返回最小合法结构化文本。"""
        if kind == "task_planner":
            output = {"summary": "执行已确认的健康检查 API 用例。", "acceptance_criteria": ["产生真实 TestRun 和正式报告"]}
        elif kind in {"task_api_worker", "task_ui_worker"}:
            payload = json.loads(user_content)
            output = {"case_ids": payload["allowed_case_ids"], "explanation": "只选择已批准用例"}
        elif kind == "task_reviewer":
            output = {"approved": True, "findings": []}
        elif kind == "report_summary":
            output = {"overview": "测试执行完成。", "key_findings": [], "recommendations": [], "risk_summary": "按正式报告统计。"}
        else:
            raise AssertionError(f"未覆盖的模型角色: {kind}")
        if validator is not None:
            validator(output)
        return output

    def chat(self, system, user_content, *, history=None):
        """为主 Agent 生成与报告事实一致的简短摘要。"""
        return "主 Agent 已根据正式执行与报告记录完成汇总。"


def _seed_default_model(db, admin_id):
    """创建本测试独占的启用默认模型绑定；模型调用由测试模型边界控制。"""
    row = ModelConfiguration(
        domain_id=unique("task-model"),
        label="任务集成验证模型",
        provider="openai-compatible",
        api_base="http://127.0.0.1:9/v1",
        api_key_encrypted=None,
        model_name="test-boundary-only",
        is_enabled=True,
        is_default=True,
        created_by=admin_id,
    )
    # 平台模型表的默认位至多一个；测试隔离库内已有配置时先清除旧默认标记。
    db.query(ModelConfiguration).filter(ModelConfiguration.is_default.is_(True)).update(
        {ModelConfiguration.is_default: False}, synchronize_session=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _bind_environment(db, project_id, environment_id, admin_id):
    """为测试项目显式绑定隔离环境，保持生产侧项目环境校验生效。"""
    from app.platform.environment_configuration.models import ProjectEnvironment
    from app.core.models.configuration import Environment

    environment = db.get(Environment, environment_id)
    db.add(ProjectEnvironment(project_id=project_id, environment_id=environment_id, base_url=environment.base_url, gateway_prefix=environment.gateway_prefix or "", default_headers=environment.default_headers or {}, created_by=admin_id))
    db.commit()


def test_p4_migration_adds_scan_polling_and_idempotency_contract(db):
    """0016 的调度字段与 0017 的备用路由字段均已持久化。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from tests.conftest import BACKEND_DIR

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    inspector = inspect(db.bind)
    assert db.execute(text("select version_num from alembic_version")).scalar() == ScriptDirectory.from_config(config).get_current_head()
    assert "security_scan_json" in {item["name"] for item in inspector.get_columns("task")}
    assert "available_at" in {item["name"] for item in inspector.get_columns("task_work_item")}
    assert "idempotency_key" in {item["name"] for item in inspector.get_columns("security_scan_job")}
    assert "ix_task_work_item_available_at" in {item["name"] for item in inspector.get_indexes("task_work_item")}
    assert "uq_security_scan_job_idempotency" in {item["name"] for item in inspector.get_indexes("security_scan_job")}
    assert "fallback_model_ids" in {item["name"] for item in inspector.get_columns("model_configuration")}
    assert "task_mode" in {item["name"] for item in inspector.get_columns("task")}
    assert "task_run_id" in {item["name"] for item in inspector.get_columns("agent_session")}
    assert "agent_session_id" in {item["name"] for item in inspector.get_columns("web_agent_session")}


def test_production_provider_falls_back_after_primary_http_error(db, monkeypatch):
    """主模型 HTTP 故障时按快照顺序调用备用模型，并校验其结构化结果。"""
    import httpx

    from app.llm.providers import openai_compatible as llm_provider
    from app.orchestration.tasks.schemas import TaskPlanOutput

    backup = ModelConfiguration(
        domain_id=unique("fallback"), label="备用模型", provider="openai-compatible",
        api_base="http://backup.invalid/v1", model_name="backup-model", is_enabled=True,
    )
    db.add(backup)
    db.flush()
    primary = ModelConfiguration(
        domain_id=unique("primary"), label="主模型", provider="openai-compatible",
        api_base="http://primary.invalid/v1", model_name="primary-model", is_enabled=True,
        fallback_model_ids=[backup.id],
    )
    db.add(primary)
    db.commit()
    calls: list[str] = []

    def post(url, *, json, headers, timeout):
        """按请求模型模拟主模型故障和备用模型成功响应。"""
        calls.append(json["model"])
        if json["model"] == "primary-model":
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"summary":"备用接手","acceptance_criteria":["完成验证"]}'}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
        })

    monkeypatch.setattr(llm_provider.httpx, "post", post)
    events: list[dict] = []
    provider = llm_provider.ProductionLLMProvider(
        db, model_config_ids=[primary.id, backup.id], attempt_callback=events.append,
    )
    result = provider.generate_structured(
        "系统", "目标", schema=TaskPlanOutput.model_json_schema(),
        kind="task_planner", validator=TaskPlanOutput.model_validate,
    )

    assert result["summary"] == "备用接手"
    assert calls == ["primary-model", "backup-model"]
    assert provider.last_model_config_id == backup.id
    assert [event["status"] for event in events] == ["FAILED", "SUCCEEDED"]
    assert events[0]["error_code"] == "LLM_PROVIDER_ERROR"


def test_production_provider_exhaustion_is_retryable_and_redacts_response(db, monkeypatch):
    """候选模型全部超时后返回可恢复错误，不把服务端响应正文泄入事件。"""
    import httpx

    from app.llm import LLMError
    from app.llm.providers import ProductionLLMProvider

    primary = ModelConfiguration(
        domain_id=unique("unavailable"), label="不可用模型", provider="openai-compatible",
        api_base="http://unavailable.invalid/v1", model_name="down-model", is_enabled=True,
    )
    db.add(primary)
    db.commit()
    monkeypatch.setattr(
        "app.llm.providers.openai_compatible.httpx.post",
        lambda *args, **kwargs: httpx.Response(503, text="sensitive upstream body"),
    )
    provider = ProductionLLMProvider(db, model_config_ids=[primary.id])

    with pytest.raises(LLMError) as raised:
        provider.chat("系统", "问题")

    assert raised.value.code == "LLM_FALLBACK_EXHAUSTED"
    assert raised.value.retryable is True
    assert "sensitive upstream body" not in str(raised.value)
    assert provider.last_attempts[0]["error_code"] == "LLM_PROVIDER_ERROR"


def test_retryable_llm_failure_requeues_task_instead_of_failing(api, admin, db, monkeypatch):
    """真实任务的模型路由耗尽会持久化延迟重试，不把运行直接终止为 FAILED。"""
    from app.llm import LLMError
    from app.orchestration.tasks.runtime import worker as task_worker_module

    class UnavailableTaskLLM:
        """只模拟外部 LLM 边界连续不可用，实际调度仍由 TaskWorker 完成。"""

        def __init__(self, db, model_config_ids=None, attempt_callback=None, **kwargs):
            """保存 Worker 注入的授权候选与审计回调。"""
            self.attempt_callback = attempt_callback
            self.model_config_id = (model_config_ids or [None])[0]

        def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None, validator=None):
            """模拟全部模型候选失败，并将同一错误交给 Worker 的恢复状态机。"""
            entry = {"model_config_id": self.model_config_id, "model_name": "down", "candidate_index": 0, "status": "FAILED", "error_code": "LLM_PROVIDER_ERROR"}
            if self.attempt_callback:
                self.attempt_callback(entry)
            raise LLMError("LLM_FALLBACK_EXHAUSTED", "模型路由不可用", retryable=True, attempts=[entry])

        def chat(self, system, user_content, *, history=None):
            """模拟主 Agent 会话的模型路由耗尽。"""
            raise LLMError("LLM_FALLBACK_EXHAUSTED", "模型路由不可用", retryable=True)

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", UnavailableTaskLLM)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)
    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1", admin_id)
    _bind_environment(db, project_id, environment_id, admin_id)
    api_id = _make_iface(db, project_id, "GET", "/health", "模型降级验证接口")
    case_id = _create_case(api, admin, project_id, name=unique("fallback-case"), api_id=api_id)
    case = db.get(CaseEntity, case_id)
    case.status = "ACTIVE"
    db.commit()
    created = api.post(
        f"/projects/{project_id}/tasks", username=admin,
        json={"goal": "模型服务暂不可用时保留任务并重试", "environment_id": environment_id, "case_ids": [case_id]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["latest_run"]["id"]

    deadline = time.monotonic() + 10
    detail = None
    while time.monotonic() < deadline:
        detail = api.get(f"/task-runs/{run_id}", username=admin).json()
        if detail["run"]["stage"] == "MODEL_RETRY":
            break
        time.sleep(0.05)

    assert detail["run"]["status"] == "QUEUED", detail
    assert detail["run"]["stage"] == "MODEL_RETRY", detail
    plan_work = next(item for item in detail["work_items"] if item["kind"] == "PLAN")
    assert plan_work["status"] == "PENDING"
    assert plan_work["error_code"] == "LLM_FALLBACK_EXHAUSTED"
    events = api.get(f"/task-runs/{run_id}/events", username=admin).json()
    assert any(event["event_type"] == "llm.retry_scheduled" for event in events)


def test_task_web_authoring_creates_isolated_worker_plan(api, admin, db, monkeypatch):
    """无已确认用例的 Web 编写创建独立运行与 UI Worker，不混入执行用例/报告链路。"""
    from app.orchestration.tasks.models import TaskAgentInstance
    from app.orchestration.tasks.runtime import worker as task_worker_module

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)
    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1:18080", admin_id)
    _bind_environment(db, project_id, environment_id, admin_id)
    body = {
        "title": "登录页交互式编写",
        "goal": "观察登录页并设计可复用的登录 Web 用例",
        "environment_id": environment_id,
        "case_ids": [],
        "task_mode": "WEB_AUTHORING",
        "web_authoring": {"target_page_path": "/login", "step_budget": 6},
        "request_key": unique("web-authoring-request"),
    }

    created = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["task_mode"] == "WEB_AUTHORING"
    duplicate = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == task["id"]

    run_id = task["latest_run"]["id"]
    deadline = time.monotonic() + 15
    detail = None
    while time.monotonic() < deadline:
        response = api.get(f"/task-runs/{run_id}", username=admin)
        assert response.status_code == 200, response.text
        detail = response.json()
        if detail["plans"] and detail["run"]["status"] == "WAITING_CONFIRMATION":
            break
        time.sleep(0.05)

    assert detail is not None and detail["run"]["status"] == "WAITING_CONFIRMATION", detail
    snapshot = detail["run"]["input_snapshot"]
    assert snapshot["target_type"] == "WEB_AUTHORING"
    assert snapshot["web_authoring"] == {
        "auth_profile_id": None,
        "target_page_path": "/login",
        "step_budget": 6,
    }
    roles = {item["role"] for item in detail["agents"]}
    assert roles == {"MAIN", "PLANNER", "UI_WORKER"}
    ui_worker = next(item for item in detail["agents"] if item["role"] == "UI_WORKER")
    assert {"web-authoring.start", "web-authoring.turn", "web-case.draft"} <= set(ui_worker["tool_allowlist_json"])
    plan_work = detail["plans"][-1]["plan_json"]["work_items"]
    assert [item["key"] for item in plan_work] == ["web_authoring"]
    assert db.query(TaskAgentInstance).filter_by(task_run_id=run_id, role="REPORT_AGENT").count() == 0


@pytest.fixture
def task_browser_registry():
    """保证任务内浏览器在真实 Chromium 集成用例退出时释放。"""
    from app.execution.browser.session_manager import registry

    registry.close_all()
    yield
    registry.close_all()


def test_task_web_authoring_browser_approval_draft_and_reverse_trace(api, admin, db, monkeypatch, web_authoring_web_setup, task_browser_registry):
    """任务内真实受控浏览器遵守人工步骤门禁，草稿未确认且双向追溯到本次运行。"""
    from app.agents.models.session import AgentSession
    from app.orchestration.tasks.models import TaskAgentInstance
    from app.orchestration.tasks.router import web_authoring_service
    from app.orchestration.tasks.runtime import worker as task_worker_module
    from app.features.web_testing.models import WebAgentSession, WebAgentStep
    from app.execution.browser.session_manager import registry
    from tests.test_33_web_agent_loop import ScriptedProvider, _propose, _web_intent

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)
    project_id, environment_id = web_authoring_web_setup
    provider = ScriptedProvider([_propose("CLICK", "submit")])
    provider.set_response("intent", _web_intent())
    monkeypatch.setattr(web_authoring_service, "_provider", lambda *_args: provider)
    body = {
        "title": "任务内编写登录交互",
        "goal": "检查页面并提出点击 Submit 的 Web 用例步骤",
        "environment_id": environment_id,
        "task_mode": "WEB_AUTHORING",
        "web_authoring": {"target_page_path": "/", "step_budget": 3},
        "request_key": unique("task-web-flow"),
    }
    created = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    run_id = created.json()["latest_run"]["id"]

    deadline = time.monotonic() + 15
    detail = None
    while time.monotonic() < deadline:
        detail = api.get(f"/task-runs/{run_id}", username=admin).json()
        if detail["plans"] and detail["run"]["status"] == "WAITING_CONFIRMATION":
            break
        time.sleep(0.05)
    assert detail is not None and detail["run"]["stage"] == "PLAN_REVIEW", detail
    approved = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "APPROVE_PLAN", "idempotency_key": unique("web-plan-approve")},
    )
    assert approved.status_code == 200, approved.text

    workspace = None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = api.get(f"/task-runs/{run_id}/web-authoring", username=admin)
        if response.status_code == 200:
            workspace = response.json()
            break
        time.sleep(0.1)
    assert workspace is not None, response.text
    assert workspace["agent"]["role"] == "UI_WORKER"
    browser_id = workspace["web_session"]["id"]
    agent_session_id = workspace["agent_session"]["id"]
    agent_row = db.get(AgentSession, agent_session_id)
    browser_row = db.get(WebAgentSession, browser_id)
    assert agent_row.task_run_id == run_id and agent_row.task_agent_instance_id == workspace["agent"]["id"]
    assert browser_row.task_run_id == run_id and browser_row.agent_session_id == agent_session_id
    assert browser_row.task_agent_instance_id == workspace["agent"]["id"]
    assert {"MAIN", "PLANNER", "UI_WORKER"} == {item["role"] for item in api.get(f"/task-runs/{run_id}", username=admin).json()["agents"]}
    assert api.get(f"/agent/sessions/{agent_session_id}", username=admin).status_code == 404
    assert api.get(f"/web-agent/sessions/{browser_id}", username=admin).status_code == 404
    visible_sessions = api.get(f"/projects/{project_id}/web-agent/sessions", username=admin).json()["items"]
    assert all(item["id"] != browser_id for item in visible_sessions)

    registry.close_session(browser_id)
    lost = api.get(f"/task-runs/{run_id}/web-authoring", username=admin)
    assert lost.status_code == 200 and lost.json()["web_session"]["status"] == "FAILED"
    restarted = api.post(f"/task-runs/{run_id}/web-authoring/restart", username=admin, json={})
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["web_session"]["id"] != browser_id
    db.refresh(browser_row)
    assert browser_row.status == "FAILED"
    browser_id = restarted.json()["web_session"]["id"]
    browser_row = db.get(WebAgentSession, browser_id)

    goal_key = unique("web-goal-turn")
    goal_turn = {"request_key": goal_key, "content": "提出点击 Submit 按钮这一步", "web_session_id": browser_id}
    proposed = api.post(f"/task-runs/{run_id}/web-authoring/messages", username=admin, json=goal_turn)
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["workspace"]["stage"] == "WEB_STEP_REVIEW"
    assert db.query(WebAgentStep).filter_by(session_id=browser_id, status="ACCEPTED").count() == 0
    assert api.post(f"/task-runs/{run_id}/web-authoring/messages", username=admin, json=goal_turn).status_code == 200

    confirm_key = unique("web-confirm-turn")
    confirm_turn = {"request_key": confirm_key, "action": "confirm_web_step", "web_session_id": browser_id}
    accepted = api.post(f"/task-runs/{run_id}/web-authoring/messages", username=admin, json=confirm_turn)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["workspace"]["stage"] == "COMPLETED"
    assert db.query(WebAgentStep).filter_by(session_id=browser_id, status="ACCEPTED", source="AI").count() == 1
    assert api.post(f"/task-runs/{run_id}/web-authoring/messages", username=admin, json=confirm_turn).status_code == 200

    draft = api.post(
        f"/task-runs/{run_id}/web-authoring/draft", username=admin,
        json={"name": unique("task-web-draft")},
    )
    assert draft.status_code == 201, draft.text
    case = draft.json()
    assert case["confirmed"] is False
    duplicate_draft = api.post(
        f"/task-runs/{run_id}/web-authoring/draft", username=admin,
        json={"name": case["name"]},
    )
    assert duplicate_draft.status_code == 409
    assert "已生成" in duplicate_draft.json()["message"]
    assert db.query(TaskAgentInstance).filter_by(task_run_id=run_id, role="UI_WORKER").one().status == "COMPLETED"
    resources = api.get(f"/task-runs/{run_id}/resources", username=admin).json()
    case_ref = next(item for item in resources if item["resource_type"] == "TEST_CASE" and item["resource_id"] == str(case["id"]))
    assert case_ref["direction"] == "OUTPUT" and case_ref["metadata_json"]["confirmed"] is False
    assert case_ref["task_id"] == task_id and case_ref["run_number"] == 1
    reverse = api.get("/task-resources", username=admin, params={"resource_type": "TEST_CASE", "resource_id": str(case["id"])})
    assert reverse.status_code == 200, reverse.text
    assert any(item["task_id"] == task_id and item["task_run_id"] == run_id for item in reverse.json())
    db.refresh(browser_row)
    assert browser_row.status == "CLOSED"
    registry.close_all()


def test_task_api_runs_existing_executor_report_and_reverse_links(api, admin, db, monkeypatch):
    """从创建、幂等、方案确认到真实 HTTP TestRun、报告和管理页回链走完闭环。"""
    from app.orchestration.tasks.runtime import worker as task_worker_module

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    admin_id = _admin_id(db)
    model = _seed_default_model(db, admin_id)

    with StubServer() as stub:
        stub.add("GET", "/health", 200, {"status": "ok"})
        environment_id = _make_env(db, stub.base_url, admin_id)
        project_id = _create_project(api, admin)
        _bind_environment(db, project_id, environment_id, admin_id)
        _whitelist(db, project_id, stub.port, admin_id)
        api_id = _make_iface(db, project_id, "GET", "/health", "健康检查")
        case_id = _create_case(api, admin, project_id, name=unique("health-case"), api_id=api_id)
        case = db.get(CaseEntity, case_id)
        case.status = "ACTIVE"
        db.commit()

        body = {
            "title": "真实 API 任务闭环",
            "goal": "调用已确认的健康检查用例并生成报告",
            "environment_id": environment_id,
            "case_ids": [case_id],
            "request_key": unique("request"),
        }
        created = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
        assert created.status_code == 201, created.text
        task = created.json()
        assert task["latest_run"]["status"] == "QUEUED"

        outsider = unique("task-outsider")
        assert api.register(outsider).status_code == 201
        api.login(outsider)
        hidden_run = api.get(f"/task-runs/{task['latest_run']['id']}", username=outsider)
        assert hidden_run.status_code == 404, hidden_run.text

        duplicate = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["id"] == task["id"]
        mismatched_duplicate = api.post(
            f"/projects/{project_id}/tasks", username=admin,
            json={**body, "goal": "通过相同请求键提交不同目标"},
        )
        assert mismatched_duplicate.status_code == 409, mismatched_duplicate.text

        run_id = task["latest_run"]["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin)
            assert detail.status_code == 200, detail.text
            if detail.json()["plans"] and detail.json()["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert detail.json()["run"]["status"] == "WAITING_CONFIRMATION", detail.text
        notices = api.get("/notifications", username=admin, params={"project_id": project_id, "event_type": "task.plan_ready"})
        assert notices.status_code == 200
        assert any(item["payload"]["detail"] == {"task_id": task["id"], "run_id": run_id} for item in notices.json()["items"])
        roles = {agent["role"] for agent in detail.json()["agents"]}
        assert {"MAIN", "PLANNER", "API_WORKER", "REVIEWER", "REPORT_AGENT"} <= roles

        main_agent = next(agent for agent in detail.json()["agents"] if agent["role"] == "MAIN")
        goal_update_body = {
            "recipient_instance_id": main_agent["id"],
            "message_type": "GOAL_UPDATE",
            "content": "新的整体目标仍是执行健康检查并核实正式报告",
            "client_message_id": unique("goal-update"),
        }
        goal_update = api.post(
            f"/task-runs/{run_id}/messages",
            username=admin,
            json=goal_update_body,
        )
        assert goal_update.status_code == 202, goal_update.text
        duplicate_goal_update = api.post(
            f"/task-runs/{run_id}/messages", username=admin, json=goal_update_body,
        )
        assert duplicate_goal_update.status_code == 202, duplicate_goal_update.text
        assert duplicate_goal_update.json()["created_run_id"] == goal_update.json()["created_run_id"]
        old_run = api.get(f"/task-runs/{run_id}", username=admin)
        assert old_run.json()["run"]["status"] == "SUPERSEDED"
        run_id = goal_update.json()["created_run_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin)
            if detail.json()["plans"] and detail.json()["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert detail.json()["run"]["status"] == "WAITING_CONFIRMATION", detail.text

        paused = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "PAUSE", "idempotency_key": unique("pause")},
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["response_json"]["status"] == "PAUSED"
        resumed = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "RESUME", "idempotency_key": unique("resume")},
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["response_json"]["status"] == "WAITING_CONFIRMATION"

        approve_key = unique("approve")
        approved = api.post(
            f"/task-runs/{run_id}/commands",
            username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": approve_key},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "COMPLETED"
        duplicate_approval = api.post(
            f"/task-runs/{run_id}/commands",
            username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": approve_key},
        )
        assert duplicate_approval.status_code == 200, duplicate_approval.text
        assert duplicate_approval.json()["id"] == approved.json()["id"]

        final_detail = None
        while time.monotonic() < deadline + 30:
            response = api.get(f"/task-runs/{run_id}", username=admin)
            assert response.status_code == 200, response.text
            final_detail = response.json()
            if final_detail["run"]["status"] in {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "RECONCILIATION_REQUIRED"}:
                break
            time.sleep(0.05)

        assert final_detail is not None
        assert final_detail["run"]["status"] == "SUCCEEDED", final_detail
        notices = api.get("/notifications", username=admin, params={"project_id": project_id, "event_type": "task.completed"})
        assert notices.status_code == 200
        assert sum(item["payload"]["detail"] == {"task_id": task["id"], "run_id": run_id} for item in notices.json()["items"]) == 1
        work_statuses = {item["kind"]: item["status"] for item in final_detail["work_items"]}
        assert work_statuses["EXECUTE_API"] == "SUCCEEDED"
        assert work_statuses["REPORT"] == "SUCCEEDED"
        assert work_statuses["REVIEW"] == "SUCCEEDED"
        assert work_statuses["FINALIZE"] == "SUCCEEDED"

        resources = api.get(f"/task-runs/{run_id}/resources", username=admin)
        assert resources.status_code == 200, resources.text
        output_types = {row["resource_type"] for row in resources.json() if row["direction"] == "OUTPUT"}
        assert {"TEST_RUN", "TEST_PLAN", "TEST_SUITE", "REPORT"} <= output_types
        test_run_ref = next(row for row in resources.json() if row["resource_type"] == "TEST_RUN")
        reverse = api.get(
            "/task-resources",
            username=admin,
            params={"resource_type": "TEST_RUN", "resource_id": test_run_ref["resource_id"]},
        )
        assert reverse.status_code == 200, reverse.text
        assert any(row["metadata_json"]["task_id"] == task["id"] for row in reverse.json())

        events = api.get(f"/task-runs/{run_id}/events", username=admin)
        assert events.status_code == 200, events.text
        event_seqs = [row["event_seq"] for row in events.json()]
        assert event_seqs == sorted(set(event_seqs))

    # 运行使用任务创建时的显式模型配置 ID；密钥没有进入实例配置快照。
    assert all(agent["model_config_id"] == model.id for agent in final_detail["agents"])
    assert all("api_key" not in json.dumps(agent["config_snapshot"]) for agent in final_detail["agents"])


def test_task_planner_retry_and_cancel_are_persisted(api, admin, db, monkeypatch):
    """Planner 的可重试失败回队列，之后可取消待确认运行且命令可幂等重放。"""
    from app.orchestration.tasks.runtime import worker as task_worker_module

    class FailFirstPlanner(DeterministicTaskLLM):
        """首个 Planner 调用失败一次，其余模型职责复用确定性输出。"""

        planner_calls = 0

        def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None, validator=None):
            """模拟一次可恢复的模型边界故障，不替代调度或业务服务。"""
            if kind == "task_planner" and type(self).planner_calls == 0:
                type(self).planner_calls += 1
                raise RuntimeError("可重试的模型边界中断")
            return super().generate_structured(system, user_content, schema, kind=kind, history=history, validator=validator)

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", FailFirstPlanner)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)
    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1", admin_id)
    _bind_environment(db, project_id, environment_id, admin_id)
    api_id = _make_iface(db, project_id, "GET", "/health", "重试验证接口")
    case_id = _create_case(api, admin, project_id, name=unique("retry-case"), api_id=api_id)
    case = db.get(CaseEntity, case_id)
    case.status = "ACTIVE"
    db.commit()
    created = api.post(
        f"/projects/{project_id}/tasks", username=admin,
        json={"goal": "验证 Planner 安全重试", "environment_id": environment_id, "case_ids": [case_id]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["latest_run"]["id"]

    deadline = time.monotonic() + 15
    failed_detail = None
    while time.monotonic() < deadline:
        response = api.get(f"/task-runs/{run_id}", username=admin)
        failed_detail = response.json()
        if failed_detail["run"]["status"] == "FAILED":
            break
        time.sleep(0.05)
    assert failed_detail["run"]["status"] == "FAILED", failed_detail
    plan_work = next(item for item in failed_detail["work_items"] if item["kind"] == "PLAN")

    retried = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "RETRY", "work_item_id": plan_work["id"], "idempotency_key": unique("retry")},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["response_json"]["status"] == "QUEUED"

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = api.get(f"/task-runs/{run_id}", username=admin)
        detail = response.json()
        if detail["plans"]:
            break
        time.sleep(0.05)
    assert detail["run"]["status"] == "WAITING_CONFIRMATION", detail

    cancel_key = unique("cancel")
    cancelled = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "CANCEL", "idempotency_key": cancel_key},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["response_json"]["status"] == "CANCELLED"
    duplicate_cancel = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "CANCEL", "idempotency_key": cancel_key},
    )
    assert duplicate_cancel.status_code == 200, duplicate_cancel.text
    assert duplicate_cancel.json()["id"] == cancelled.json()["id"]
    conflicting_cancel = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "PAUSE", "idempotency_key": cancel_key},
    )
    assert conflicting_cancel.status_code == 409, conflicting_cancel.text


def test_task_model_binding_obeys_organization_grants(db):
    """任务创建和后台调用分别尊重组织智能体开关、模型白名单及配置停用。"""
    from app.orchestration.tasks.services.task_service import TaskService
    from app.orchestration.tasks.services.assembly_service import resolve_authorized_model
    from app.core.models.identity import Organization, OrganizationMember, User
    from app.core.models.project import Project
    from fastapi import HTTPException

    actor = User(username=unique("task-member"), role="test", is_active=True)
    db.add(actor)
    db.flush()
    organization = Organization(name=unique("task-org"), owner_id=actor.id)
    db.add(organization)
    db.flush()
    project = Project(name=unique("task-org-project"), owner_id=actor.id, organization_id=organization.id)
    model = ModelConfiguration(
        domain_id=unique("org-model"), label="组织授权模型", provider="openai-compatible",
        api_base="http://127.0.0.1:9/v1", model_name="test-boundary-only",
        is_enabled=True, is_default=True, created_by=actor.id,
    )
    db.add_all([project, model])
    db.flush()
    grant = OrganizationMember(
        organization_id=organization.id, user_id=actor.id, role="owner",
        agent_enabled=False, allowed_model_ids=[],
    )
    db.add(grant)
    db.commit()

    with pytest.raises(HTTPException) as disabled:
        resolve_authorized_model(db, project.id, actor)
    assert disabled.value.status_code == 403

    grant.agent_enabled = True
    db.commit()
    with pytest.raises(HTTPException) as unassigned:
        resolve_authorized_model(db, project.id, actor)
    assert unassigned.value.status_code == 403

    grant.allowed_model_ids = [model.domain_id]
    db.commit()
    assert resolve_authorized_model(db, project.id, actor).id == model.id
    assert TaskService.assert_agent_model_access(db, project.id, actor, model.id).id == model.id

    grant.allowed_model_ids = []
    db.commit()
    with pytest.raises(RuntimeError, match="授权已撤销"):
        TaskService.assert_agent_model_access(db, project.id, actor, model.id)


def test_task_ui_worker_reuses_confirmed_web_testrun(api, admin, db, monkeypatch):
    """已确认 Web 用例由独立 UI Worker 走真实 TestRun/Playwright/ReportService 链。"""
    from app.orchestration.tasks.runtime import worker as task_worker_module

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)

    with StubServer() as stub:
        stub.add("GET", "/health", 200, {"status": "ok"})
        environment_id = _make_env(db, stub.base_url, admin_id)
        project_id = _create_project(api, admin)
        _bind_environment(db, project_id, environment_id, admin_id)
        _whitelist(db, project_id, stub.port, admin_id)
        created_case = api.post(
            f"/projects/{project_id}/web-cases", username=admin,
            json={"name": unique("confirmed-web-case"), "steps": [
                {"name": "打开健康页", "operation": "NAVIGATE", "value": "/health"},
            ]},
        )
        assert created_case.status_code == 201, created_case.text
        web_case_id = created_case.json()["id"]
        confirmed = api.post(
            f"/web-cases/{web_case_id}/confirm", username=admin,
            json={"revision": created_case.json()["revision"]},
        )
        assert confirmed.status_code == 200 and confirmed.json()["confirmed"]

        created = api.post(
            f"/projects/{project_id}/tasks", username=admin,
            json={"goal": "执行已确认的 Web 健康页用例并产出报告", "environment_id": environment_id, "case_ids": [web_case_id]},
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["latest_run"]["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail_response = api.get(f"/task-runs/{run_id}", username=admin)
            detail = detail_response.json()
            if detail["plans"] and detail["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert {agent["role"] for agent in detail["agents"]} >= {"MAIN", "PLANNER", "UI_WORKER", "REPORT_AGENT", "REVIEWER"}
        assert "API_WORKER" not in {agent["role"] for agent in detail["agents"]}

        accepted = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": unique("web-approve")},
        )
        assert accepted.status_code == 200, accepted.text
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin).json()
            if detail["run"]["status"] in {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED"}:
                break
            time.sleep(0.05)
        assert detail["run"]["status"] == "SUCCEEDED", detail
        assert any(item["kind"] == "EXECUTE_WEB" and item["status"] == "SUCCEEDED" for item in detail["work_items"])
        resources = api.get(f"/task-runs/{run_id}/resources", username=admin).json()
        test_run_ref = next(item for item in resources if item["resource_type"] == "TEST_RUN")
        assert test_run_ref["display_name"].startswith("测试运行 #")
        source_links = api.get(
            "/task-resources", username=admin,
            params={"resource_type": "TEST_RUN", "resource_id": test_run_ref["resource_id"], "project_id": project_id},
        )
        assert source_links.status_code == 200, source_links.text
        assert any(
            item["task_title"] == created.json()["title"] and item["run_number"] == 1
            for item in source_links.json()
        )


def test_task_creation_rejects_retired_or_unknown_security_fields(api, admin, db):
    """旧 ZAP 配置和未知安全选项必须显式报错，不能被当成普通任务静默忽略。"""
    from app.orchestration.tasks.models import Task

    project_id = _create_project(api, admin)
    base = {"goal": "验证未知任务字段不会被忽略", "environment_id": 1, "case_ids": [1]}
    retired_zap = api.post(
        f"/projects/{project_id}/tasks", username=admin,
        json={**base, "security_scan": {"target_id": 1, "scan_profile_id": 1}},
    )
    assert retired_zap.status_code == 422, retired_zap.text

    unknown_security_option = api.post(
        f"/projects/{project_id}/tasks", username=admin,
        json={
            "goal": "验证未知安全选项不会被忽略",
            "environment_id": 1,
            "security_assessment": {
                "api_ids": [1], "strategy_ids": [1], "skip_human_approval": True,
            },
        },
    )
    assert unknown_security_option.status_code == 422, unknown_security_option.text
    assert db.query(Task).filter(Task.project_id == project_id).count() == 0
