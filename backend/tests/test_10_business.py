"""验收项 10：业务管理全链路。

覆盖：
- 迁移：0004 建出 10 张业务表（business_*）且 head 推进到 0004
- 验收主流程：建域「AI选址」→建流程→6 个动作→重排→在「创建任务」上配前置条件/
  输入输出变量→选 POST /api/task 接口绑定→配 project_id→body.project_id 输入映射→
  配 $.data.id→task_id 输出映射→配状态 CREATED→RUNNING→加业务规则→拉聚合详情→
  重载持久
- 绑定失效可见：接口硬删 → valid=False「已删除」；接口 DEPRECATED → valid=False「已废弃」
- 权限：viewer 不可写（403）、可读；跨项目越权 404
"""

from __future__ import annotations

from tests.conftest import unique

# ---------------------------------------------------------------- 建项目/成员辅助


def _create_project(api, actor, name=None):
    proj_name = name or unique("proj")
    response = api.post(
        "/projects", username=actor, json={"name": proj_name, "description": "biz test project"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], proj_name


def _register_and_login(api, username):
    response = api.register(username)
    assert response.status_code == 201, response.text
    user_id = response.json()["user"]["id"]
    api.login(username, "Init-Password-123")
    return user_id


def _add_project_member(api, actor, project_id, user_id, role="member"):
    response = api.put(
        f"/projects/{project_id}/members/{user_id}",
        username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text


def _create_domain(api, actor, project_id, name="AI选址"):
    r = api.post(
        f"/projects/{project_id}/business-domains",
        username=actor,
        json={"name": name, "description": "选址业务域", "sort": 0, "status": "ACTIVE"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_flow(api, actor, project_id, domain_id, name="AI选址任务流程"):
    r = api.post(
        f"/projects/{project_id}/business-flows",
        username=actor,
        json={"name": name, "description": "创建并执行选址任务", "domain_id": domain_id, "status": "DRAFT"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_action(api, actor, flow_id, name, action_key):
    r = api.post(
        f"/business-flows/{flow_id}/actions",
        username=actor,
        json={"name": name, "action_key": action_key, "action_type": "NORMAL"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_interface(api, actor, project_id, name="创建任务接口", method="POST", path="/api/task"):
    r = api.post(
        f"/projects/{project_id}/apis",
        username=actor,
        json={"name": name, "method": method, "path": path, "status": "ACTIVE", "parameters": [], "responses": []},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------- 迁移


def test_business_tables_created_by_migration(db):
    """业务表由 0004 迁移建出；迁移链 head 推进到 0011（0005 执行引擎、0006 测试管理、0007 Agent、0008 报告/通知、0009 测试数据中心、0010 Mock Management、0011 Security Testing）。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head == "0012", f"迁移 head 应为 0012，实际 {head}"

    from sqlalchemy import inspect

    inspector = inspect(db.bind)
    tables = set(inspector.get_table_names())
    expected = {
        "business_domain", "business_flow", "business_action", "business_precondition",
        "business_variable", "business_state", "business_variable_ref", "business_rule",
        "business_binding", "business_api_mapping",
    }
    missing = expected - tables
    assert not missing, f"缺少业务表: {missing}"


# ---------------------------------------------------------------- 验收主流程


def test_business_full_acceptance_flow(api, admin):
    """端到端验收：域→流程→6 动作→重排→前置条件/变量→绑定+映射→状态→规则→聚合详情→持久。"""
    project_id, _ = _create_project(api, admin)
    domain_id = _create_domain(api, admin, project_id, "AI选址")
    flow_id = _create_flow(api, admin, project_id, domain_id)

    # 6 个业务动作（按验收步骤）。
    steps = [
        ("登录", "LOGIN"),
        ("创建项目", "CREATE_PROJECT"),
        ("上传数据", "UPLOAD_DATA"),
        ("创建任务", "CREATE_TASK"),
        ("执行任务", "RUN_TASK"),
        ("查询结果", "QUERY_RESULT"),
    ]
    action_ids = {key: _create_action(api, admin, flow_id, name, key) for name, key in steps}

    # 重排：把「查询结果」移到第二位，验证 reorder 生效。
    r = api.patch(
        f"/business-flows/{flow_id}/actions/reorder",
        username=admin,
        json={"items": [
            {"action_id": action_ids["LOGIN"], "sort": 10},
            {"action_id": action_ids["QUERY_RESULT"], "sort": 20},
            {"action_id": action_ids["CREATE_PROJECT"], "sort": 30},
            {"action_id": action_ids["UPLOAD_DATA"], "sort": 40},
            {"action_id": action_ids["CREATE_TASK"], "sort": 50},
            {"action_id": action_ids["RUN_TASK"], "sort": 60},
        ]},
    )
    assert r.status_code == 200, r.text
    keys_after = [a["action_key"] for a in r.json()]
    assert keys_after == ["LOGIN", "QUERY_RESULT", "CREATE_PROJECT", "UPLOAD_DATA", "CREATE_TASK", "RUN_TASK"]

    # 在「创建任务」上配前置条件。
    create_task_id = action_ids["CREATE_TASK"]
    r = api.post(
        f"/business-actions/{create_task_id}/preconditions",
        username=admin,
        json={"type": "STATE", "target": "project.status", "operator": "EQ",
              "expected_value": "ACTIVE", "description": "项目须为启用状态", "sort": 0},
    )
    assert r.status_code == 201, r.text

    # 输入变量：project_id / user_id；输出变量：task_id。
    r = api.post(
        f"/business-actions/{create_task_id}/variables",
        username=admin,
        json={"direction": "INPUT", "name": "project_id", "data_type": "INTEGER", "required": True, "sort": 0},
    )
    assert r.status_code == 201, r.text
    r = api.post(
        f"/business-actions/{create_task_id}/variables",
        username=admin,
        json={"direction": "OUTPUT", "name": "task_id", "data_type": "INTEGER", "required": True, "sort": 0},
    )
    assert r.status_code == 201, r.text

    # 从接口管理选 POST /api/task 并绑定。
    api_id = _create_interface(api, admin, project_id, "创建任务接口", "POST", "/api/task")
    r = api.post(
        f"/business-actions/{create_task_id}/bindings",
        username=admin,
        json={"binding_type": "API", "api_id": api_id, "enabled": True},
    )
    assert r.status_code == 201, r.text
    binding = r.json()
    assert binding["valid"] is True
    assert binding["api_method"] == "POST"
    assert binding["api_path"] == "/api/task"
    binding_id = binding["id"]

    # 输入映射：project_id → body.project_id。
    r = api.post(
        f"/business-bindings/{binding_id}/mappings",
        username=admin,
        json={"direction": "INPUT", "business_variable": "project_id",
              "api_location": "BODY", "api_field": "project_id"},
    )
    assert r.status_code == 201, r.text
    # 输出映射：$.data.id → task_id。
    r = api.post(
        f"/business-bindings/{binding_id}/mappings",
        username=admin,
        json={"direction": "OUTPUT", "business_variable": "task_id",
              "api_location": "RESPONSE", "expression": "$.data.id"},
    )
    assert r.status_code == 201, r.text

    # 状态：CREATED → RUNNING。
    r = api.post(
        f"/business-actions/{create_task_id}/states",
        username=admin,
        json={"entity": "task", "pre_state": "CREATED", "post_state": "RUNNING"},
    )
    assert r.status_code == 201, r.text

    # 业务规则。
    r = api.post(
        f"/projects/{project_id}/business-rules",
        username=admin,
        json={"name": "任务执行前置状态", "flow_id": flow_id, "rule_type": "CONSTRAINT",
              "expression": "task.status == CREATED", "enabled": True},
    )
    assert r.status_code == 201, r.text

    # 聚合详情：一次性拿到全部子配置。
    r = api.get(f"/business-flows/{flow_id}/detail", username=admin)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["domain_name"] == "AI选址"
    assert detail["project_id"] == project_id
    assert [a["action_key"] for a in detail["actions"]] == keys_after

    ct = next(a for a in detail["actions"] if a["action_key"] == "CREATE_TASK")
    assert ct["preconditions"][0]["target"] == "project.status"
    assert any(v["name"] == "project_id" and v["direction"] == "INPUT" for v in ct["input_variables"])
    assert any(v["name"] == "task_id" and v["direction"] == "OUTPUT" for v in ct["output_variables"])
    assert ct["states"][0]["pre_state"] == "CREATED"
    assert ct["states"][0]["post_state"] == "RUNNING"
    assert ct["binding"] is not None
    assert ct["binding"]["valid"] is True
    assert any(m["business_variable"] == "project_id" and m["api_location"] == "BODY"
               for m in ct["binding"]["input_mappings"])
    assert any(m["business_variable"] == "task_id" and m["expression"] == "$.data.id"
               for m in ct["binding"]["output_mappings"])
    assert any(rule["expression"] == "task.status == CREATED" for rule in detail["rules"])

    # 重载持久：再次拉取详情，结构一致。
    r2 = api.get(f"/business-flows/{flow_id}/detail", username=admin)
    assert r2.status_code == 200
    assert r2.json()["actions"][0]["action_key"] == detail["actions"][0]["action_key"]


# ---------------------------------------------------------------- 绑定失效可见


def test_business_binding_invalid_on_interface_delete(api, admin):
    """接口被硬删 → ondelete=SET NULL 置空 api_id → 绑定 valid=False「已删除」。"""
    project_id, _ = _create_project(api, admin)
    domain_id = _create_domain(api, admin, project_id, unique("域"))
    flow_id = _create_flow(api, admin, project_id, domain_id, unique("流程"))
    action_id = _create_action(api, admin, flow_id, "调用接口", "CALL_API")
    api_id = _create_interface(api, admin, project_id, unique("接口"), "POST", unique("/p/"))

    r = api.post(
        f"/business-actions/{action_id}/bindings",
        username=admin,
        json={"binding_type": "API", "api_id": api_id, "enabled": True},
    )
    binding_id = r.json()["id"]
    assert r.json()["valid"] is True

    # 删除接口（走接口管理真实删除路径）。
    r = api.delete(f"/apis/{api_id}", username=admin)
    assert r.status_code == 204

    r = api.get(f"/business-bindings/{binding_id}", username=admin)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["valid"] is False
    assert detail["invalid_reason"] == "绑定接口已失效（已删除）"
    assert detail["api_id"] is None
    # 绑定行仍保留（未随接口级联删除）。
    assert detail["id"] == binding_id


def test_business_binding_invalid_on_deprecated(api, admin):
    """接口 status=DEPRECATED → 绑定 valid=False「已废弃」，api_id 仍在。"""
    project_id, _ = _create_project(api, admin)
    domain_id = _create_domain(api, admin, project_id, unique("域"))
    flow_id = _create_flow(api, admin, project_id, domain_id, unique("流程"))
    action_id = _create_action(api, admin, flow_id, "调用接口2", "CALL_API2")
    api_id = _create_interface(api, admin, project_id, unique("接口"), "POST", unique("/p/"))

    r = api.post(
        f"/business-actions/{action_id}/bindings",
        username=admin,
        json={"binding_type": "API", "api_id": api_id, "enabled": True},
    )
    binding_id = r.json()["id"]

    # 把接口置为 DEPRECATED。
    r = api.patch(f"/apis/{api_id}", username=admin, json={"status": "DEPRECATED"})
    assert r.status_code == 200, r.text

    r = api.get(f"/business-bindings/{binding_id}", username=admin)
    detail = r.json()
    assert detail["valid"] is False
    assert detail["invalid_reason"] == "绑定接口已废弃"
    assert detail["api_id"] == api_id


# ---------------------------------------------------------------- 权限


def test_business_viewer_cannot_write(api, admin):
    """viewer 只能读，写操作（建域/建流程）应 403。"""
    viewer_name = unique("viewer")
    viewer_id = _register_and_login(api, viewer_name)
    project_id, _ = _create_project(api, admin)
    _add_project_member(api, admin, project_id, viewer_id, role="viewer")

    r = api.post(
        f"/projects/{project_id}/business-domains",
        username=viewer_name,
        json={"name": "越权域", "sort": 0, "status": "ACTIVE"},
    )
    assert r.status_code == 403

    # viewer 可读（项目可见）。
    r = api.get(f"/projects/{project_id}/business-domains", username=viewer_name)
    assert r.status_code == 200


def test_business_cross_project_hidden_as_404(api, admin):
    """其他用户项目下的业务域，越权访问按 404 隐藏。"""
    observer_name = unique("observer")
    _register_and_login(api, observer_name)
    project_id, _ = _create_project(api, admin)
    domain_id = _create_domain(api, admin, project_id, unique("域"))

    # 观察者看不到该域 → 404。
    r = api.get(f"/business-domains/{domain_id}", username=observer_name)
    assert r.status_code == 404
    # 观察者列该项目下的域 → 项目不可见 → 404。
    r = api.get(f"/projects/{project_id}/business-domains", username=observer_name)
    assert r.status_code == 404
