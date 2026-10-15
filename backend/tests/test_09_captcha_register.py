"""验收项 9：图形验证码与注册自动登录。

覆盖：
- GET /captcha 返回 challenge_id / image_base64 / expires_in
- POST /register 缺 captcha 字段 → 422
- 错误验证码 → 400，且 challenge 被删除（一次性使用）
- 过期验证码 → 400
- 正确验证码 → 201，返回 access_token 与 user
- 重复提交同一 captcha_id → 400
- captcha 签发限流：同一 IP 短时间超过阈值 → 429
- 注册用户自动登录：/register 直接返回 token，登录态即刻生效
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app.features.captcha.services.captcha_service import _STORAGE, _reset_storage

from tests.conftest import unique


@pytest.fixture(autouse=True)
def _clean_captcha_storage():
    """每个测试前后清空 challenge 存储，避免用例间相互污染。"""
    _reset_storage()
    yield
    _reset_storage()


def _seed_challenge(code="TEST12", ttl_seconds=300, expired=False):
    """直接在内存里种一个 challenge，返回 (challenge_id, code)。"""
    cid = f"test-{uuid4().hex[:8]}"
    expires_at = datetime.now() + timedelta(seconds=-1 if expired else ttl_seconds)
    _STORAGE[cid] = {"code": code, "expires_at": expires_at}
    return cid, code


# ---------------------------------------------------------------- 签发

def test_captcha_issue_returns_valid_payload(api):
    """GET /captcha 返回 challenge_id、data URI 与有效期。"""
    r = api.client.get("/api/v1/captcha")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["challenge_id"]
    assert body["image_base64"].startswith("data:image/png;base64,")
    assert body["expires_in"] > 0


def test_captcha_issue_stores_challenge_in_memory(api):
    """签发后 challenge 应写入内存存储。"""
    _reset_storage()
    r = api.client.get("/api/v1/captcha")
    assert r.status_code == 200
    cid = r.json()["challenge_id"]
    assert cid in _STORAGE


def test_captcha_issue_multiple_calls_yield_distinct_ids(api):
    """连续签发多次应得到互不相同的 challenge_id。"""
    _reset_storage()
    ids = set()
    for _ in range(5):
        r = api.client.get("/api/v1/captcha")
        assert r.status_code == 200
        ids.add(r.json()["challenge_id"])
    assert len(ids) == 5


def test_captcha_rate_limit_ip_bucket(api):
    """同一 IP 短时间超过阈值应返回 429。"""
    # 限流阈值由 conftest 里设为 1000000，这里为了验证 429 需要临时下调。
    # 前置重置限流器内存：其它用例可能已经消耗过 captcha 桶的计数，若不重置本用例
    # 会在第一条 /captcha 请求上就命中阈值，测试顺序变成隐式依赖。
    import app.shared.rate_limit as rl
    from app.shared.config import settings

    original = settings.AUTH_CAPTCHA_IP_LIMIT_PER_MINUTE
    settings.AUTH_CAPTCHA_IP_LIMIT_PER_MINUTE = 3
    rl.reset_rate_limits()
    try:
        for _ in range(3):
            r = api.client.get("/api/v1/captcha")
            assert r.status_code == 200, r.text
        r = api.client.get("/api/v1/captcha")
        assert r.status_code == 429, r.text
    finally:
        settings.AUTH_CAPTCHA_IP_LIMIT_PER_MINUTE = original
        rl.reset_rate_limits()


# ---------------------------------------------------------------- 注册接入

def test_register_without_captcha_fields_returns_422(api):
    """POST /register 缺 captcha 字段应被 Pydantic 校验拦截（422）。"""
    r = api.client.post(
        "/api/v1/register",
        json={"username": unique("no-captcha"), "password": "Init-Password-123"},
    )
    assert r.status_code == 422, r.text


def test_register_with_wrong_captcha_returns_400(api):
    """错误验证码 → 400，且 challenge 被删除（不可复用）。"""
    cid, code = _seed_challenge("TEST12")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("wrong-code"),
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": "WRONG",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["message"] == "验证码错误或已过期"
    # challenge 必须已被删除，一次 verify 无论成败都清除。
    assert cid not in _STORAGE


def test_register_with_unknown_captcha_returns_400(api):
    """不存在的 challenge_id → 400（与错误验证码同码，不泄露是否存在）。"""
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("unknown-cid"),
            "password": "Init-Password-123",
            "captcha_id": "nonexistent-id",
            "captcha_code": "TEST12",
        },
    )
    assert r.status_code == 400


def test_register_with_expired_captcha_returns_400(api):
    """过期验证码 → 400。"""
    cid, _ = _seed_challenge("TEST12", expired=True)
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("expired"),
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": "TEST12",
        },
    )
    assert r.status_code == 400
    assert cid not in _STORAGE


def test_register_with_valid_captcha_returns_token(api):
    """正确验证码 → 201，返回 access_token 与 user；challenge 被消费。"""
    cid, code = _seed_challenge("TEST12")
    username = unique("valid")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": username,
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["username"] == username
    assert body["user"]["id"] is not None
    # 一次性：challenge 已删除。
    assert cid not in _STORAGE


def test_register_rejects_reuse_of_same_challenge(api):
    """同一 challenge_id 用第二次应返回 400（一次性使用）。"""
    cid, code = _seed_challenge("TEST12")
    first = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("reuse-a"),
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    assert first.status_code == 201
    # 第二次尝试用同一个 challenge_id（即使校验码正确）也应被拒。
    second = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("reuse-b"),
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    assert second.status_code == 400


def test_register_captcha_case_insensitive(api):
    """验证码校验大小写不敏感：全小写输入也应当通过。"""
    cid, code = _seed_challenge("TEST12")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("case"),
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code.lower(),
        },
    )
    assert r.status_code == 201, r.text


def test_register_auto_login_returns_usable_token(api):
    """注册返回的 token 立即可用：调 /auth/me 应返回同一用户。"""
    cid, code = _seed_challenge("TEST12")
    username = unique("autologin")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": username,
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]

    # 拿这个 token 直接调 /me，应返回同一用户。
    r = api.client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["username"] == username
    assert me["role"] == "test"  # 自助注册默认 test 角色


def test_register_personal_organization_created_on_auto_login(api):
    """注册后应立即拥有个人组织，可通过 /auth/me/organizations 查到。"""
    cid, code = _seed_challenge("TEST12")
    username = unique("personal-org")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": username,
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    assert r.status_code == 201
    token = r.json()["access_token"]

    r = api.client.get(
        "/api/v1/me/organizations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    orgs = r.json()["items"]
    assert len(orgs) >= 1
    # 新注册用户的个人组织里，用户自己应该是 owner。
    assert any(org["my_role"] == "owner" for org in orgs)


def test_register_validation_still_applied_after_captcha_pass(api):
    """验证码通过后，用户名重复、密码过短等业务校验仍生效。"""
    cid, code = _seed_challenge("TEST12")
    username = unique("still-validated")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": username,
            "password": "Init-Password-123",
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    assert r.status_code == 201

    # 同一用户名再次注册（新 challenge）：应返回 409。
    cid2, code2 = _seed_challenge("TEST12")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": username,
            "password": "Init-Password-123",
            "captcha_id": cid2,
            "captcha_code": code2,
        },
    )
    assert r.status_code == 409
    assert r.json()["message"] == "用户名已存在"


def test_register_short_password_after_valid_captcha_returns_400(api):
    """验证码通过后，短密码仍被业务校验拒绝（6 位以下 400）。"""
    cid, code = _seed_challenge("TEST12")
    r = api.client.post(
        "/api/v1/register",
        json={
            "username": unique("short-pw"),
            "password": "abc",  # 少于 6 位
            "captcha_id": cid,
            "captcha_code": code,
        },
    )
    # 短密码既会触发 Pydantic 422，也可能触发 service 400；
    # 具体取决于 UserCreate.password 的 min_length=6 是否先命中。
    assert r.status_code in (400, 422)


def test_admin_user_create_still_works_without_captcha(api, admin):
    """管理员创建用户接口 /users 不要求 captcha（保持原状）。"""
    new_user = unique("admin-create")
    r = api.post(
        "/users",
        username=admin,
        json={"username": new_user, "password": "Init-Password-123", "role": "test"},
    )
    assert r.status_code == 201, r.text
