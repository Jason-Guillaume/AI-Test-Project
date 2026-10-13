"""验收项 3：注册 / 登录 / 当前用户 / 退出链路，含个人组织自动创建。

统一的错误信封约定（code / message / request_id）与「登录失效，请重新登录」
的统一文案，都是本文件重点验收的对外契约。
"""

from __future__ import annotations

import jwt

from app.shared.auth import ALGORITHM
from app.shared.config import ACCESS_TOKEN_EXPIRE_MINUTES, settings

from tests.conftest import API, DEFAULT_PASSWORD, unique


def test_register_creates_user_and_personal_organization(api):
    """不变量：注册即建号并自动建个人组织，且响应里绝不回传密码哈希。

    验收点：
    - 注册返回 201，用户默认角色是 test、状态启用；
    - 响应体中不存在 hashed_password 字段（密钥/口令不外泄）；
    - 登录后 /me/organizations 恰好只有 1 条个人组织，自己是 owner，
      且 owner_id 指向刚创建的账号 id。
    """
    username = unique("alice")
    response = api.register(username)
    assert response.status_code == 201, response.text
    body = response.json()
    # 注册接口已从 UserResponse 升级为 TokenResponse：注册即自动登录，
    # access_token / token_type / expires_in 直接返回给调用方。
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    user = body["user"]
    assert user["username"] == username
    assert user["role"] == "test"
    assert user["is_active"] is True
    assert "hashed_password" not in user
    assert user["created_at"]

    # 注册返回的 token 立即可用：不用额外登录就能调 /me。
    token = body["access_token"]
    me = api.get("/me", token=token)
    assert me.status_code == 200
    assert me.json()["username"] == username
    assert me.json()["role"] == "test"

    orgs = api.get("/me/organizations", token=token)
    assert orgs.status_code == 200, orgs.text
    payload = orgs.json()
    # 个人组织只有一条：不允许注册时多建或漏建。
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["items"][0]["my_role"] == "owner"
    assert payload["items"][0]["owner_id"] == user["id"]


def test_login_responds_with_token_contract(api):
    """不变量：登录响应的字段形状与 JWT 内部声明都符合契约。

    验收点：token_type 为 bearer、expires_in 与配置分钟数一致、user 子对象
    不含哈希口令；access_token 是标准三段式 JWT；且声明里带 ver=0 撤销位
    ——这是后续「改密即失效」能够生效的前提。
    """
    username = unique("bob")
    assert api.register(username).status_code == 201
    response = api.client.post(
        f"{API}/login", json={"username": username, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["token_type"] == "bearer"
    # expires_in 用秒，等于配置的分钟数乘以 60：契约必须与配置联动。
    assert payload["expires_in"] == ACCESS_TOKEN_EXPIRE_MINUTES * 60
    user = payload["user"]
    assert user["username"] == username
    assert user["role"] == "test"
    assert user["is_active"] is True
    assert "hashed_password" not in user
    # JWT 结构：header.payload.signature
    assert payload["access_token"].count(".") == 2
    # 令牌确实带上了撤销位，改密后才会立刻失效。
    claims = jwt.decode(
        payload["access_token"], settings.SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": True}
    )
    assert claims["sub"] == str(user["id"])
    assert claims["ver"] == 0


def test_logout_returns_204_without_server_session(api):
    """服务端不维护会话表：退出仅返回 204，令牌在撤销前仍有效。

    前端必须在退出时删除本地令牌；服务端侧的失效只发生在
    改密 / 禁用 / 角色变更（token_version 递增）。
    """
    username = unique("carol")
    assert api.register(username).status_code == 201
    token = api.login(username)
    assert api.post("/logout", token=token).status_code == 204
    assert api.get("/me", token=token).status_code == 200


def test_unauthenticated_request_returns_401_envelope(api):
    """不变量：未携带令牌时返回的是统一错误信封，而不是 FastAPI 的默认体。

    验收点：401、code 为 ERR_TOKEN_EXPIRED、中文提示、带 request_id 便于
    排查、并且设置 WWW-Authenticate: Bearer 头。
    """
    response = api.get("/me")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "ERR_TOKEN_EXPIRED"
    assert body["message"] == "登录失效，请重新登录"
    assert body["request_id"]
    assert response.headers.get("www-authenticate") == "Bearer"


def test_invalid_token_shapes_are_rejected(api):
    """不变量：任何形状的垃圾令牌都被当作「登录失效」处理，不泄漏内部异常。

    覆盖三类伪造：非 JWT 文本、形似三段式但无效的字符串、带 Bearer 前缀的
    随机串——三者都必须返回 401 与同一句中文提示。
    """
    for garbage in ("not-a-jwt", "x.y.z", "Bearer " + "a" * 40):
        response = api.get("/me", token=garbage)
        assert response.status_code == 401, garbage
        assert response.json()["message"] == "登录失效，请重新登录"


def test_non_bearer_scheme_gets_the_same_unified_message(api):
    """Authorization 头不是 Bearer 前缀时同样返回统一文案，而不是英文默认值。"""
    response = api.client.get(f"{API}/me", headers={"Authorization": "Basic abc"})
    body = response.json()
    # 实现上允许 401 或 403，但文案必须统一。
    assert response.status_code in (401, 403)
    assert body["message"] == "登录失效，请重新登录"
    assert body["code"] in {"ERR_TOKEN_EXPIRED", "ERR_FORBIDDEN"}
    assert body["request_id"]


def test_login_rejects_wrong_password_and_missing_user(api):
    """不变量：用户名不存在与密码错误返回同一文案，避免账号枚举。"""
    username = unique("dave")
    assert api.register(username).status_code == 201

    wrong = api.client.post(
        f"{API}/login", json={"username": username, "password": "Wrong-Password-1"}
    )
    assert wrong.status_code == 400
    assert wrong.json()["message"] == "用户名或密码错误"

    missing = api.client.post(
        f"{API}/login", json={"username": "nobody-here-xyz", "password": "Wrong-Password-1"}
    )
    assert missing.status_code == 400
    # 用户名不存在与密码错误返回同一文案，避免账号枚举。
    assert missing.json()["message"] == "用户名或密码错误"


def test_registration_validation(api):
    """不变量：入参校验失败返回 422 信封且不落库，重复注册返回 409 冲突。

    验收点：弱密码被请求校验拦下（ERR_VALIDATION），之后用同一用户名
    注册成功，再次注册才被唯一约束拒绝（ERR_CONFLICT）。
    """
    username = unique("eve")
    # 密码低于 6 位：请求校验失败统一返回 422 信封，且不落库。
    weak = api.register(username, password="Ab1")
    assert weak.status_code == 422, weak.text
    assert weak.json()["code"] == "ERR_VALIDATION"

    first = api.register(username)
    assert first.status_code == 201
    second = api.register(username)
    assert second.status_code == 409
    assert second.json()["code"] == "ERR_CONFLICT"
