"""验收项 5、6：

- 非管理员不能调用平台管理端接口（服务端强制，不依赖前端隐藏按钮）
- 分页契约统一（page / page_size / items / total）
- 模型 API Key 永不回传明文，编辑时留空表示保留原密钥
"""

from __future__ import annotations

import pytest

from tests.conftest import DEFAULT_PASSWORD, unique

# 创建模型配置的默认入参：domain_id 每次用 unique() 换值避免撞主键；api_key 是
# 测试专用假密钥，必须始终不出现在任何响应体里（由末尾的掩码用例兜底校验）。
MODEL_CONFIG_PAYLOAD = {
    "domain_id": "test-domain",
    "label": "测试模型",
    "provider": "openai-compatible",
    "api_base": "https://api.example.com/v1",
    "model_name": "gpt-4o",
    "api_key": "sk-test-only-0123456789abcdef",
}


@pytest.fixture()
def plain(api):
    """一个刚注册、已登录的普通测试角色用户。"""
    username = unique("plain")
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username)
    return username


# 平台管理员专属的只读接口清单：这四个入口对非管理员一律不可读。
ADMIN_READ_ENDPOINTS = [
    ("get", "/users"),
    ("get", "/model-configs"),
    ("get", "/environments"),
    ("get", "/dashboard/platform"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_READ_ENDPOINTS)
def test_non_admin_cannot_read_platform_endpoints(api, plain, method, path):
    """不变量：管理端接口由服务端强制鉴权，非管理员一律 403，不靠前端隐藏按钮。

    验收点：四个管理只读接口都返回 ERR_FORBIDDEN 信封，message 非空且带
    request_id，便于前端统一提示与线上排查。
    """
    response = getattr(api, method)(path, username=plain)
    assert response.status_code == 403, (path, response.text)
    body = response.json()
    assert body["code"] == "ERR_FORBIDDEN"
    assert body["message"]
    assert body["request_id"]


@pytest.mark.parametrize(("method", "path"), ADMIN_READ_ENDPOINTS)
def test_platform_endpoints_require_login(api, method, path):
    """不变量：不带令牌的匿名请求一律 401，管理端不允许免登录读取。"""
    response = getattr(api, method)(path)
    assert response.status_code == 401


def test_non_admin_cannot_write_admin_resources(api, plain, admin):
    """不变量：普通角色不能写入管理资源，也不能改自己的管理员字段。

    验收点：建用户 403；自我提权与自我停用 403（role / is_active 是管理员字段）；
    建模型配置与执行环境 403，且错误码统一为 ERR_FORBIDDEN 而不是裸 403。
    """
    # 不能用管理员接口创建账号。
    response = api.post(
        "/users",
        username=plain,
        json={"username": "evil-admin", "password": DEFAULT_PASSWORD, "role": "admin"},
    )
    assert response.status_code == 403

    # 不能给自己改平台角色或停用自己（角色/状态是管理员字段，返回 403）。
    own_id = api.get("/me", username=plain).json()["id"]
    assert api.patch(f"/users/{own_id}", username=plain, json={"role": "admin"}).status_code == 403
    assert api.patch(f"/users/{own_id}", username=plain, json={"is_active": False}).status_code == 403

    # 不能创建模型配置 / 执行环境。
    for path, payload in (("/model-configs", MODEL_CONFIG_PAYLOAD), ("/environments", {"name": "x-env"})):
        response = api.post(path, username=plain, json=payload)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "ERR_FORBIDDEN"


def test_admin_can_use_platform_endpoints(api, admin):
    """不变量：管理员拥有全平台读写权限，四类管理接口都能走通。

    验收点：分页信封字段齐全且 page / page_size 原样回显；建用户时 role 生效；
    平台看板 200；执行环境创建后可按 name 立即回读。
    """
    listing = api.get("/users", username=admin, params={"page": 1, "page_size": 5})
    assert listing.status_code == 200
    payload = listing.json()
    assert {"items", "total", "page", "page_size"} <= set(payload)
    assert payload["page"] == 1
    assert payload["page_size"] == 5
    assert payload["total"] >= 1

    created = api.post(
        "/users",
        username=admin,
        json={"username": unique("byadmin"), "password": DEFAULT_PASSWORD, "role": "dev"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "dev"

    assert api.get("/dashboard/platform", username=admin).status_code == 200
    env_name = unique("admin-env")
    created_env = api.post(
        "/environments",
        username=admin,
        json={"name": env_name, "display_name": "管理员环境"},
    )
    assert created_env.status_code == 201, created_env.text
    assert created_env.json()["name"] == env_name


def test_pagination_contract(api, admin):
    """不变量：分页参数越界返回 422 信封；深翻页返回空 items 而不是报错。

    验收点：page < 1、page_size <= 0、page_size > 200 三种越界都返回 422；
    远页码的 total 与第一页一致，说明 total 不随分页游标漂移。
    """
    for invalid in (
        {"page": 0, "page_size": 20},
        {"page": 1, "page_size": 0},
        {"page": 1, "page_size": 201},
    ):
        response = api.get("/users", username=admin, params=invalid)
        assert response.status_code == 422, invalid

    page_one = api.get("/users", username=admin, params={"page": 1, "page_size": 2}).json()
    assert page_one["total"] >= 1
    assert len(page_one["items"]) <= 2

    # 远页码：items 必须为空列表，但 total 仍等于第一页的 total（翻页不改变总数）。
    far_away = api.get("/users", username=admin, params={"page": 999, "page_size": 20}).json()
    assert far_away["items"] == []
    assert far_away["total"] == page_one["total"]


def test_keyword_filter(api, admin):
    """不变量：关键字只缩小 items，命中与未命中都必须返回同样的分页信封。"""
    username = unique("kwfilter")
    assert api.register(username).status_code == 201
    hit = api.get("/users", username=admin, params={"keyword": username}).json()
    assert hit["total"] == 1
    assert hit["items"][0]["username"] == username

    miss = api.get("/users", username=admin, params={"keyword": username + "-none"}).json()
    assert miss["total"] == 0
    assert miss["items"] == []


def test_model_api_key_is_never_returned_in_clear(api, admin):
    """不变量：模型 API Key 在任何出口都不回传明文，脱敏串也不含密钥尾部。

    验收点：创建 / 列表 / 详情三处只给 has_api_key 布尔与 masked_api_key；
    编辑时留空表示保留原密钥，显式传新值才轮换；默认配置必须先切走才能删除。
    """
    secret = MODEL_CONFIG_PAYLOAD["api_key"]
    domain = unique("domain")
    created = api.post(
        "/model-configs",
        username=admin,
        json={**MODEL_CONFIG_PAYLOAD, "domain_id": domain},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_api_key"] is True
    # 整个响应体里都不能出现完整密钥，只允许 masked_api_key 这类脱敏串。
    assert secret not in str(body)
    # 脱敏串不能包含完整密钥，也不应是完整密钥本身。
    assert secret not in body["masked_api_key"]
    assert len(body["masked_api_key"]) < len(secret)
    assert not body["masked_api_key"].endswith(secret[-8:])

    listed = api.get("/model-configs", username=admin).json()
    target = next(item for item in listed["items"] if item["domain_id"] == domain)
    assert secret not in str(listed)
    assert target["has_api_key"] is True

    detail = api.get(f"/model-configs/{body['id']}", username=admin)
    assert detail.status_code == 200
    assert secret not in str(detail.json())

    # 留空（不传）表示保留原密钥。
    kept = api.patch(
        f"/model-configs/{body['id']}",
        username=admin,
        json={"label": "改名后的模型"},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["has_api_key"] is True

    # 显式传入新密钥才覆盖。
    rotated = api.patch(
        f"/model-configs/{body['id']}",
        username=admin,
        json={"api_key": "sk-test-only-rotated-9999"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["has_api_key"] is True
    assert secret not in str(rotated.json())

    # 默认模型不能直接删除：先把默认切到另一条配置。
    if body["is_default"]:
        second = api.post(
            "/model-configs",
            username=admin,
            json={**MODEL_CONFIG_PAYLOAD, "domain_id": unique("second")},
        )
        assert second.status_code == 201, second.text
        switched = api.post(
            f"/model-configs/{second.json()['id']}/set-default", username=admin
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["is_default"] is True

    before = api.get("/model-configs", username=admin).json()["total"]
    assert api.delete(f"/model-configs/{body['id']}", username=admin).status_code == 204
    after = api.get("/model-configs", username=admin).json()["total"]
    assert after == before - 1


def test_model_fallback_route_is_ordered_and_validated(api, admin):
    """管理员可保存有序备用模型；重复、自引用和不存在的配置会被拒绝。"""
    backup = api.post(
        "/model-configs", username=admin,
        json={**MODEL_CONFIG_PAYLOAD, "domain_id": unique("fallback-model"), "label": "备用模型"},
    )
    assert backup.status_code == 201, backup.text
    primary = api.post(
        "/model-configs", username=admin,
        json={**MODEL_CONFIG_PAYLOAD, "domain_id": unique("primary-model"), "label": "主模型"},
    )
    assert primary.status_code == 201, primary.text
    primary_id = primary.json()["id"]
    backup_id = backup.json()["id"]

    saved = api.patch(
        f"/model-configs/{primary_id}", username=admin,
        json={"fallback_model_ids": [backup_id]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["fallback_model_ids"] == [backup_id]
    for invalid in ([primary_id], [backup_id, backup_id], [99999999]):
        response = api.patch(
            f"/model-configs/{primary_id}", username=admin,
            json={"fallback_model_ids": invalid},
        )
        assert response.status_code == 400, response.text



def test_enabled_model_requires_api_key(api, admin):
    """不变量：启用状态的模型配置必须有密钥（缺则 400），停用状态允许留空。"""
    response = api.post(
        "/model-configs",
        username=admin,
        json={**MODEL_CONFIG_PAYLOAD, "domain_id": unique("nokey"), "api_key": "", "is_enabled": True},
    )
    assert response.status_code == 400
    # 停用状态允许没有密钥。
    disabled = api.post(
        "/model-configs",
        username=admin,
        json={
            **MODEL_CONFIG_PAYLOAD,
            "domain_id": unique("nokey"),
            "api_key": "",
            "is_enabled": False,
        },
    )
    assert disabled.status_code == 201, disabled.text
    assert disabled.json()["has_api_key"] is False
    assert disabled.json()["is_default"] is False
