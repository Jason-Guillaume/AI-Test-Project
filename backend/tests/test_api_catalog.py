"""验收项（接口管理）：模块/接口/参数/响应/关联 CRUD + 导入 + 调试 + 权限。

覆盖（spec §17 闭环）：
- 模块 CRUD + 两级限制 + 未分类默认模块（不可删/改名）
- 接口 CRUD + 去重（project_id+method+path 唯一）
- Curl 导入预览 + 敏感值脱敏（Authorization/Cookie 不落库真实值）
- OpenAPI JSON / YAML / Swagger 2.0 批量解析
- 导入预览→确认（CREATED 入库 / 重复 UNCHANGED 跳过 / 变更 CHANGED 更新）
- 变更检测写 change_log（UPDATED + 粒度日志）
- 调试出站白名单：未命中 403 / 命中后发请求（连接失败 400，证明白名单放行）
- 权限：viewer 不可写 403；越权项目按 404 隐藏存在性；调试仅平台管理员
"""

from __future__ import annotations

from tests.conftest import unique


# ---------------------------------------------------------------- 建项目/成员辅助（与 test_08 同款）

def _create_project(api, actor, name=None):
    """以 actor 身份创建个人项目，返回 (project_id, project_name)。"""
    proj_name = name or unique("proj")
    response = api.post(
        "/projects",
        username=actor,
        json={"name": proj_name, "description": "api catalog test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], proj_name


def _register_and_login(api, username):
    """注册新用户并缓存令牌，返回 user_id。"""
    response = api.register(username)
    assert response.status_code == 201, response.text
    user_id = response.json()["user"]["id"]
    api.login(username, "Init-Password-123")
    return user_id


def _add_project_member(api, actor, project_id, user_id, role="member"):
    """以 actor 身份把 user_id 加为项目成员。"""
    response = api.put(
        f"/projects/{project_id}/members/{user_id}",
        username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------- 模块

def test_module_crud_two_level_and_default(api, admin):
    """模块 CRUD + 两级限制 + 未分类默认模块。"""
    project_id, _ = _create_project(api, admin)

    # 1. 列出模块：自动创建「未分类」默认模块（读端点已提交，跨请求可见）。
    r = api.get(f"/projects/{project_id}/api-modules", username=admin)
    assert r.status_code == 200, r.text
    modules = r.json()
    defaults = [m for m in modules if m["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == "未分类"
    default_id = defaults[0]["id"]

    # 2. 新建一级模块。
    r = api.post(
        f"/projects/{project_id}/api-modules",
        username=admin,
        json={"name": "用户"},
    )
    assert r.status_code == 201, r.text
    level1_id = r.json()["id"]
    assert r.json()["name"] == "用户"

    # 3. 新建二级模块（parent_id 指向一级）。
    r = api.post(
        f"/projects/{project_id}/api-modules",
        username=admin,
        json={"name": "登录", "parent_id": level1_id},
    )
    assert r.status_code == 201, r.text
    level2_id = r.json()["id"]

    # 4. 三级模块应被拒（parent 的 parent 已非 None）。
    r = api.post(
        f"/projects/{project_id}/api-modules",
        username=admin,
        json={"name": "不该出现", "parent_id": level2_id},
    )
    assert r.status_code == 400, r.text

    # 5. 未分类不可改名。
    r = api.patch(f"/api-modules/{default_id}", username=admin, json={"name": "改不掉"})
    assert r.status_code == 400, r.text

    # 6. 改名普通模块。
    r = api.patch(f"/api-modules/{level1_id}", username=admin, json={"name": "用户域"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "用户域"

    # 7. 未分类不可删。
    r = api.delete(f"/api-modules/{default_id}", username=admin)
    assert r.status_code == 400, r.text

    # 8. 有子模块的一级模块不可直接删（先要求清掉子模块）。
    r = api.delete(f"/api-modules/{level1_id}", username=admin)
    assert r.status_code == 400, r.text
    assert "子模块" in r.json()["message"]

    # 9. 删掉子模块后，建接口到一级模块，再删一级模块：接口归未分类。
    r = api.delete(f"/api-modules/{level2_id}", username=admin)
    assert r.status_code == 204, r.text

    r = api.post(
        f"/projects/{project_id}/apis",
        username=admin,
        json={
            "name": "登录接口",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "module_id": level1_id,
        },
    )
    assert r.status_code == 201, r.text
    api_id = r.json()["id"]

    r = api.delete(f"/api-modules/{level1_id}", username=admin)
    assert r.status_code == 204, r.text

    # 接口仍在，且模块归未分类。
    r = api.get(f"/apis/{api_id}", username=admin)
    assert r.status_code == 200
    assert r.json()["module_name"] == "未分类"


# ---------------------------------------------------------------- 接口

def test_interface_crud_and_dedup(api, admin):
    """接口 CRUD + 去重（project_id+method+path 唯一）。"""
    project_id, _ = _create_project(api, admin)

    # 1. 创建接口。
    r = api.post(
        f"/projects/{project_id}/apis",
        username=admin,
        json={
            "name": "获取任务",
            "method": "GET",
            "path": "/api/v1/tasks/{id}",
            "parameters": [
                {"name": "id", "location": "PATH", "type": "integer", "required": True}
            ],
            "body": {"body_type": "none"},
            "responses": [
                {"status_code": 200, "description": "成功"},
                {"status_code": 404, "description": "不存在"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    api_id = r.json()["id"]
    assert r.json()["method"] == "GET"
    assert r.json()["parameters"][0]["name"] == "id"

    # 2. 详情。
    r = api.get(f"/apis/{api_id}", username=admin)
    assert r.status_code == 200
    assert len(r.json()["responses"]) == 2

    # 3. 列表（按方法过滤）。
    r = api.get(
        f"/projects/{project_id}/apis",
        username=admin,
        params={"method": "GET"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # 4. 重复创建（同 method+path）→ 409。
    r = api.post(
        f"/projects/{project_id}/apis",
        username=admin,
        json={"name": "重复", "method": "GET", "path": "/api/v1/tasks/{id}"},
    )
    assert r.status_code == 409, r.text

    # 5. 更新基本信息 + 状态。
    r = api.patch(f"/apis/{api_id}", username=admin, json={"status": "ACTIVE", "name": "获取任务详情"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ACTIVE"
    assert r.json()["name"] == "获取任务详情"

    # 6. 请求参数整体替换。
    r = api.put(
        f"/apis/{api_id}/request",
        username=admin,
        json={
            "parameters": [
                {"name": "id", "location": "PATH", "type": "integer", "required": True},
                {"name": "fields", "location": "QUERY", "type": "string"},
            ],
            "body": {"body_type": "json", "content_type": "application/json",
                      "schema_json": {"type": "object"}},
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["parameters"]) == 2

    # 7. 响应整体替换。
    r = api.put(
        f"/apis/{api_id}/responses",
        username=admin,
        json={"responses": [{"status_code": 200, "description": "ok"}]},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["responses"]) == 1

    # 8. 删除 → 详情 404。
    r = api.delete(f"/apis/{api_id}", username=admin)
    assert r.status_code == 204, r.text
    r = api.get(f"/apis/{api_id}", username=admin)
    assert r.status_code == 404


# ---------------------------------------------------------------- Curl 导入 + 脱敏

CURL_WITH_SECRETS = (
    'curl -X POST "https://api.example.com/v1/tasks" '
    '-H "Authorization: Bearer secret-token-123" '
    '-H "Content-Type: application/json" '
    '-d \'{"title":"x"}\''
)


def test_curl_import_preview_masks_sensitive_values(api, admin):
    """Curl 导入预览：Authorization 值脱敏为 Bearer ${token}，真实凭证不落库。"""
    project_id, _ = _create_project(api, admin)

    r = api.post(
        f"/projects/{project_id}/apis/import/preview",
        username=admin,
        json={"source_type": "CURL", "content": CURL_WITH_SECRETS},
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["total"] == 1
    assert preview["new_count"] == 1

    schema = preview["items"][0]["schema"]
    assert schema["method"] == "POST"
    assert schema["path"] == "/v1/tasks"

    # Authorization 头被脱敏为变量占位。
    auth_param = next(
        p for p in schema["parameters"] if p["name"] == "Authorization"
    )
    assert auth_param["example"] == "Bearer ${token}"
    assert auth_param["schema_json"] == {"sensitive": True}

    # 真实凭证不得出现在响应里。
    assert "secret-token-123" not in r.text


# ---------------------------------------------------------------- OpenAPI 接口 文档导出 / Swagger 批量

_OPENAPI_JSON = """{
  "openapi": "3.0.0",
  "info": {"title": "demo", "version": "1"},
  "paths": {
    "/pets": {
      "get": {
        "summary": "list pets",
        "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
        "responses": {"200": {"description": "ok"}}
      },
      "post": {
        "summary": "create pet",
        "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
        "responses": {"201": {"description": "created"}}
      }
    }
  }
}"""

_OPENAPI_YAML = """openapi: 3.0.0
info:
  title: demo
  version: "1"
paths:
  /users:
    get:
      summary: list users
      parameters:
        - name: page
          in: query
          schema:
            type: integer
      responses:
        "200":
          description: ok
    delete:
      summary: delete a user
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        "204":
          description: deleted
"""

_SWAGGER_2 = """{
  "swagger": "2.0",
  "info": {"title": "demo2", "version": "1"},
  "paths": {
    "/orders/{id}": {
      "get": {
        "summary": "get order",
        "parameters": [
          {"name": "id", "in": "path", "required": true, "type": "integer"},
          {"name": "token", "in": "header", "type": "string"}
        ],
        "responses": {"200": {"description": "ok"}}
      }
    }
  }
}"""

_POSTMAN_21 = r'''{
  "info": {
    "name": "用户接口",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "auth": {
    "type": "bearer",
    "bearer": [{"key": "token", "value": "collection-secret-token", "type": "string"}]
  },
  "item": [{
    "name": "用户管理",
    "item": [{
      "name": "获取用户",
      "request": {
        "method": "GET",
        "header": [
          {"key": "X-API-Key", "value": "header-secret-key"},
          {"key": "Accept", "value": "application/json"}
        ],
        "url": {
          "raw": "https://example.com/v1/users/:userId?limit=20&access_token=query-secret",
          "host": ["example", "com"],
          "path": ["v1", "users", ":userId"],
          "query": [
            {"key": "limit", "value": "20"},
            {"key": "access_token", "value": "query-secret"}
          ],
          "variable": [{"key": "userId", "value": "123"}]
        }
      },
      "response": [{
        "name": "成功",
        "status": "OK",
        "code": 200,
        "body": "{\"id\":123,\"token\":\"response-secret\"}"
      }]
    }, {
      "name": "创建用户",
      "request": {
        "method": "POST",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "url": "https://example.com/v1/users",
        "body": {
          "mode": "raw",
          "raw": "{\"name\":\"Ada\",\"password\":\"body-secret\"}",
          "options": {"raw": {"language": "json"}}
        }
      }
    }]
  }]
}'''


def test_openapi_json_yaml_swagger_batch_preview(api, admin):
    """OpenAPI 3.x JSON/YAML 与 Swagger 2.0 均可批量解析。"""
    project_id, _ = _create_project(api, admin)

    for source_type, content, expected in [
        ("OPENAPI", _OPENAPI_JSON, 2),
        ("OPENAPI", _OPENAPI_YAML, 2),
        ("SWAGGER", _SWAGGER_2, 1),
    ]:
        r = api.post(
            f"/projects/{project_id}/apis/import/preview",
            username=admin,
            json={"source_type": source_type, "content": content},
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == expected, (source_type, r.text)

    # Swagger 路径参数应识别为 PATH。
    r = api.post(
        f"/projects/{project_id}/apis/import/preview",
        username=admin,
        json={"source_type": "SWAGGER", "content": _SWAGGER_2},
    )
    schema = r.json()["items"][0]["schema"]
    path_params = [p for p in schema["parameters"] if p["location"] == "PATH"]
    assert any(p["name"] == "id" for p in path_params)


def test_import_detects_postman_and_honors_selected_module(api, admin):
    project_id, _ = _create_project(api, admin)
    url = f"/projects/{project_id}/apis/import"
    # 即使用户保留默认的 OpenAPI 来源，仍按文档内容识别 Postman。
    preview = api.post(
        f"{url}/preview",
        username=admin,
        json={"source_type": "OPENAPI", "content": _POSTMAN_21},
    )
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["source_type"] == "POSTMAN"
    assert result["total"] == 2
    assert "collection-secret-token" not in preview.text
    assert "header-secret-key" not in preview.text
    assert "query-secret" not in preview.text
    assert "response-secret" not in preview.text
    assert "body-secret" not in preview.text

    postman20 = _POSTMAN_21.replace("v2.1.0", "v2.0.0")
    version_preview = api.post(
        f"{url}/preview",
        username=admin,
        json={"source_type": "POSTMAN", "content": postman20},
    )
    assert version_preview.status_code == 200, version_preview.text
    assert version_preview.json()["total"] == 2
    assert version_preview.json()["source_type"] == "POSTMAN"

    get_user = result["items"][0]["schema"]
    assert get_user["name"] == "获取用户"
    assert get_user["method"] == "GET"
    assert get_user["path"] == "/v1/users/{userId}"
    assert get_user["source_type"] == "POSTMAN"
    assert get_user["auth_type"] == "bearer"
    assert get_user["tags"] == ["用户管理"]
    assert any(p["name"] == "userId" and p["location"] == "PATH" for p in get_user["parameters"])
    assert next(p for p in get_user["parameters"] if p["name"] == "limit")["example"] == "20"
    api_key = next(p for p in get_user["parameters"] if p["name"] == "X-API-Key")
    assert api_key["schema_json"] == {"sensitive": True}
    assert api_key["example"] == "${x_api_key}"
    assert get_user["responses"][0]["status_code"] == 200

    create_user = result["items"][1]["schema"]
    assert create_user["body"]["body_type"] == "json"
    assert "${password}" in create_user["body"]["raw_text"]

    confirm = api.post(
        f"{url}/confirm",
        username=admin,
        json={"source_type": "OPENAPI", "content": _POSTMAN_21},
    )
    assert confirm.status_code == 201, confirm.text
    imported = api.get(f"/projects/{project_id}/api-import-records", username=admin)
    assert imported.status_code == 200, imported.text
    records = imported.json()["items"]
    assert records[0]["source_type"] == "POSTMAN"
    assert records[0]["total"] == 2

    module = api.post(f"/projects/{project_id}/api-modules", username=admin,
                      json={"name": "指定模块"})
    assert module.status_code == 201, module.text
    body = {"source_type": "OPENAPI", "content": _OPENAPI_JSON,
            "user_module_id": module.json()["id"], "selected_items": [0]}
    preview = api.post(f"{url}/preview", username=admin, json=body)
    assert preview.status_code == 200, preview.text
    selected = preview.json()["items"][0]["schema"]
    confirm = api.post(f"{url}/confirm", username=admin, json=body)
    assert confirm.status_code == 201, confirm.text
    interfaces = api.get(f"/projects/{project_id}/apis", username=admin)
    assert interfaces.status_code == 200, interfaces.text
    items = interfaces.json()
    if isinstance(items, dict):
        items = items["items"]
    match = next(item for item in items if item["path"] == selected["path"] and item["method"] == selected["method"])
    assert match["module_id"] == module.json()["id"]


# ---------------------------------------------------------------- 导入预览→确认（幂等 + 变更检测）

CURL_SIMPLE = (
    'curl -X POST "https://api.example.com/v1/tasks" '
    '-H "Content-Type: application/json" '
    '-d \'{"title":"x"}\''
)
CURL_CHANGED = (
    'curl -X POST "https://api.example.com/v1/tasks" '
    '-H "Content-Type: application/json" '
    '-d \'{"title":"y","done":false}\''
)


def test_import_confirm_creates_then_idempotent(api, admin):
    """首次确认入库 → 再次确认同内容 UNCHANGED 跳过（幂等）。"""
    project_id, _ = _create_project(api, admin)

    # 预览。
    r = api.post(
        f"/projects/{project_id}/apis/import/preview",
        username=admin,
        json={"source_type": "CURL", "content": CURL_SIMPLE},
    )
    assert r.status_code == 200
    assert r.json()["new_count"] == 1

    # 确认 → 新建 1 条。
    r = api.post(
        f"/projects/{project_id}/apis/import/confirm",
        username=admin,
        json={"source_type": "CURL", "content": CURL_SIMPLE},
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_count"] == 1
    assert r.json()["skipped_count"] == 0
    record_id = r.json()["record_id"]

    # 再次确认同内容 → UNCHANGED 跳过。
    r = api.post(
        f"/projects/{project_id}/apis/import/confirm",
        username=admin,
        json={"source_type": "CURL", "content": CURL_SIMPLE},
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_count"] == 0
    assert r.json()["updated_count"] == 0
    assert r.json()["skipped_count"] == 1

    # 导入记录落库。
    r = api.get(
        f"/projects/{project_id}/api-import-records",
        username=admin,
    )
    assert r.status_code == 200
    assert r.json()["total"] >= 2
    assert any(rec["id"] == record_id for rec in r.json()["items"])


def _find_api(api, admin, project_id, method, path):
    """按 method+path 在项目内找接口，返回详情。"""
    r = api.get(
        f"/projects/{project_id}/apis",
        username=admin,
        params={"page": 1, "page_size": 200, "method": method},
    )
    assert r.status_code == 200
    for item in r.json()["items"]:
        if item["path"] == path:
            return api.get(f"/apis/{item['id']}", username=admin).json()
    raise AssertionError(f"接口未找到：{method} {path}")


def test_import_update_writes_change_log(api, admin):
    """变更导入：CHANGED 更新接口 + version+1 + change_log 写入 UPDATED。"""
    project_id, _ = _create_project(api, admin)

    # 先建。
    api.post(
        f"/projects/{project_id}/apis/import/confirm",
        username=admin,
        json={"source_type": "CURL", "content": CURL_SIMPLE},
    )
    api_before = _find_api(api, admin, project_id, "POST", "/v1/tasks")
    version_before = api_before["version"]
    api_id = api_before["id"]

    # 改内容后预览应判 CHANGED。
    r = api.post(
        f"/projects/{project_id}/apis/import/preview",
        username=admin,
        json={"source_type": "CURL", "content": CURL_CHANGED},
    )
    assert r.status_code == 200
    assert r.json()["changed_count"] == 1

    # 确认更新。
    r = api.post(
        f"/projects/{project_id}/apis/import/confirm",
        username=admin,
        json={"source_type": "CURL", "content": CURL_CHANGED},
    )
    assert r.status_code == 201, r.text
    assert r.json()["updated_count"] == 1

    # version 递增。
    api_after = _find_api(api, admin, project_id, "POST", "/v1/tasks")
    assert api_after["version"] == version_before + 1

    # 变更记录含 UPDATED。
    r = api.get(f"/apis/{api_id}/history", username=admin, params={"page": 1, "page_size": 50})
    assert r.status_code == 200
    change_types = [log["change_type"] for log in r.json()["items"]]
    assert "UPDATED" in change_types


# ---------------------------------------------------------------- 调试 + 出站白名单

def test_debug_outbound_whitelist_deny_and_hit(api, admin, db):
    """调试出站白名单：未配目标 403；配目标后放行（连接失败 400，证明白名单通过）。"""
    from app.models.configuration import Environment
    from app.models.identity import User
    from app.models.project import ProjectOutboundTarget

    project_id, _ = _create_project(api, admin)

    # 建一个 GET /ping 接口。
    r = api.post(
        f"/projects/{project_id}/apis",
        username=admin,
        json={"name": "ping", "method": "GET", "path": "/ping"},
    )
    assert r.status_code == 201, r.text
    api_id = r.json()["id"]

    # 直接在测试库写一个环境（指向本机不可达端口，连接会立即被拒）。
    # Environment.name 是全局唯一键：用 unique() 生成名字，避免测试库未被重建
    # （残留上一次会话的数据）时重复插入报 UniqueViolation。
    env_name = unique("env")
    admin_id = db.query(User).filter(User.username == admin).one().id
    env = Environment(
        name=env_name,
        display_name="unit",
        base_url="http://127.0.0.1:9",
        gateway_prefix="",
        default_headers={},
        is_active=True,
    )
    db.add(env)
    db.flush()
    from app.models.project_environment import ProjectEnvironment
    db.add(ProjectEnvironment(project_id=project_id, environment_id=env.id,
        display_name=env.display_name, base_url=env.base_url, gateway_prefix="", default_headers={}, is_active=True))
    db.commit()

    # 1. 未配出站目标 → 403。
    r = api.post(
        f"/apis/{api_id}/debug",
        username=admin,
        json={"environment_name": env_name, "timeout": 2},
    )
    assert r.status_code == 403, r.text
    assert "白名单" in r.json()["message"]

    # 2. 配置出站目标（http/127.0.0.1/9）后放行；连接被拒 → 400（非 403）。
    target = ProjectOutboundTarget(
        project_id=project_id,
        scheme="http",
        host="127.0.0.1",
        port=9,
        is_production=False,
        enabled=True,
        approved_by=admin_id,
    )
    db.add(target)
    db.commit()

    r = api.post(
        f"/apis/{api_id}/debug",
        username=admin,
        json={"environment_name": env_name, "timeout": 2},
    )
    assert r.status_code != 403, r.text  # 白名单已通过
    # 连接 127.0.0.1:9 被拒 → bad_request 400。
    assert r.status_code == 400, r.text


def test_debug_requires_platform_admin(api, admin):
    """非平台管理员调用调试应被拒（403）。"""
    project_id, _ = _create_project(api, admin)
    r = api.post(
        f"/projects/{project_id}/apis",
        username=admin,
        json={"name": "ping", "method": "GET", "path": "/ping"},
    )
    api_id = r.json()["id"]

    # 注册一个 test 角色用户，加入项目为 member。
    member_name = unique("member")
    member_id = _register_and_login(api, member_name)
    _add_project_member(api, admin, project_id, member_id, role="member")

    r = api.post(
        f"/apis/{api_id}/debug",
        username=member_name,
        json={"environment_name": "dev", "timeout": 2},
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------- 权限：viewer 不可写 / 越权 404

def test_api_viewer_cannot_write_and_invisible_project_404(api, admin):
    """viewer 只读；越权项目按 404 隐藏存在性。"""
    viewer_name = unique("viewer")
    viewer_id = _register_and_login(api, viewer_name)
    project_id, _ = _create_project(api, admin)
    _add_project_member(api, admin, project_id, viewer_id, role="viewer")

    # viewer 建模块被拒 403。
    r = api.post(
        f"/projects/{project_id}/api-modules",
        username=viewer_name,
        json={"name": "越权"},
    )
    assert r.status_code == 403

    # admin 建接口后 viewer 可读（项目可见）。
    r = api.post(
        f"/projects/{project_id}/apis",
        username=admin,
        json={"name": "可见接口", "method": "GET", "path": "/ok"},
    )
    assert r.status_code == 201
    api_id = r.json()["id"]
    r = api.get(f"/apis/{api_id}", username=viewer_name)
    assert r.status_code == 200

    # 越权项目对观察者不可见：列表与详情都按 404 隐藏存在性（spec：不可见→404）。
    observer_name = unique("observer")
    _register_and_login(api, observer_name)
    r = api.get(
        f"/projects/{project_id}/apis",
        username=observer_name,
        params={"page": 1, "page_size": 50},
    )
    assert r.status_code == 404

    # 越权访问具体接口 → 404（隐藏存在性）。
    r = api.get(f"/apis/{api_id}", username=observer_name)
    assert r.status_code == 404


def test_structural_hash_tracks_schema_only_edits(api, admin):
    """Schema changes under existing parameters and status codes must update the hash."""
    project_id, _ = _create_project(api, admin)
    created = api.post(f"/projects/{project_id}/apis", username=admin, json={
        "name": "schema tracking", "method": "POST", "path": "/schema-tracking",
        "parameters": [{"name": "id", "location": "QUERY", "type": "string"}],
        "body": {"body_type": "json", "content_type": "application/json", "schema_json": {"type": "object"}},
        "responses": [{"status_code": 200, "schema_json": {"type": "object"}}],
    })
    assert created.status_code == 201, created.text
    api_id = created.json()["id"]
    initial_hash = created.json()["source_hash"]
    changed_request = api.put(f"/apis/{api_id}/request", username=admin, json={
        "parameters": [{"name": "id", "location": "HEADER", "type": "string"}],
        "body": {"body_type": "json", "content_type": "application/json", "schema_json": {"type": "array"}},
    })
    assert changed_request.status_code == 200, changed_request.text
    request_hash = api.get(f"/apis/{api_id}", username=admin).json()["source_hash"]
    assert request_hash != initial_hash
    changed_response = api.put(f"/apis/{api_id}/responses", username=admin, json={
        "responses": [{"status_code": 200, "schema_json": {"type": "array"}}],
    })
    assert changed_response.status_code == 200, changed_response.text
    response_hash = api.get(f"/apis/{api_id}", username=admin).json()["source_hash"]
    assert response_hash != request_hash


def test_import_preview_uses_current_structure_when_stored_hash_is_stale(api, admin, db):
    from app.features.api_catalog.models.api_request_body import ApiRequestBody

    project_id, _ = _create_project(api, admin)
    body = {"source_type": "CURL", "content": CURL_SIMPLE}
    created = api.post(f"/projects/{project_id}/apis/import/confirm", username=admin, json=body)
    assert created.status_code == 201, created.text
    iface = _find_api(api, admin, project_id, "POST", "/v1/tasks")
    request_body = db.query(ApiRequestBody).filter_by(interface_id=iface["id"]).one()
    request_body.raw_text = '{"changed":true}'
    db.commit()
    preview = api.post(f"/projects/{project_id}/apis/import/preview", username=admin, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["changed_count"] == 1
