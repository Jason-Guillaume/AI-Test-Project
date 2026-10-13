"""验收项 4：token_version 撤销链路。

修改密码 / 停用 / 平台角色变更 / 用户名变更都会递增 token_version，
旧令牌随即失效（401「登录失效，请重新登录」）；停用账户返回 403「该账户已被禁用」。
"""

from __future__ import annotations

import jwt
from sqlalchemy import select

from app.models.identity import User
from app.shared.auth import ALGORITHM
from app.shared.config import settings

from tests.conftest import API, DEFAULT_NEW_PASSWORD, DEFAULT_PASSWORD, unique


def _version(db, username: str) -> int:
    """读出指定用户当前的 token_version，用于断言「递增了几次」。

    Args:
        db: 测试会话，直接读库而不是信 API 响应，避免被测代码自己说谎。
        username: 用户名（注意改用户名后用新名查）。
    Returns:
        int: 当前版本号。
    """
    return int(db.scalar(select(User.token_version).where(User.username == username)))


def test_change_password_invalidates_all_previous_tokens(api, admin, db):
    """不变量：改密使 token_version +1，旧令牌立即 401，而不是等自然过期。

    验收点：
    - 改密成功 -> 版本号 +1，旧令牌 401 且带 WWW-Authenticate 头；
    - 新密码可登录，旧密码不再可登录；
    - 连续两次改密版本号单调递增（+2），两段旧令牌都失效；
    - 旧密码写错时只返回 400，绝不推进版本号（撤销是幂等且有条件的）。
    """
    username = unique("pwdchg")
    assert api.register(username).status_code == 201
    token_a = api.login(username)

    before = _version(db, username)
    response = api.patch(
        "/me",
        token=token_a,
        json={"old_password": DEFAULT_PASSWORD, "new_password": DEFAULT_NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert _version(db, username) == before + 1

    # 改密后旧令牌立即失效，而不是等到自然过期。
    old = api.get("/me", token=token_a)
    assert old.status_code == 401, old.text
    assert old.json()["message"] == "登录失效，请重新登录"
    assert old.headers.get("www-authenticate") == "Bearer"

    token_b = api.login(username, DEFAULT_NEW_PASSWORD)
    assert api.get("/me", token=token_b).status_code == 200

    # 旧密码不可再登录。
    rejected = api.client.post(
        f"{API}/login", json={"username": username, "password": DEFAULT_PASSWORD}
    )
    assert rejected.status_code == 400

    # 连续两次改密：token_version 单调递增，前两次令牌都失效。
    assert api.patch(
        "/me",
        token=token_b,
        json={"old_password": DEFAULT_NEW_PASSWORD, "new_password": DEFAULT_PASSWORD},
    ).status_code == 200
    assert _version(db, username) == before + 2
    assert api.get("/me", token=token_b).status_code == 401

    # 错误旧密码不会提升版本号。
    wrong = api.client.patch(
        f"{API}/me",
        headers={"Authorization": f"Bearer {api.login(username, DEFAULT_PASSWORD)}"},
        json={"old_password": "Wrong-Old-Pass", "new_password": DEFAULT_NEW_PASSWORD},
    )
    assert wrong.status_code == 400
    assert _version(db, username) == before + 2


def test_admin_deactivating_user_revokes_tokens_with_403(api, admin, db):
    """不变量：停用账户是「有权限但不可用」，走 403，与令牌失效的 401 区分开。

    验收点：停用后版本号 +1 且旧令牌拿到 403「该账户已被禁用」；停用账号
    连登录都被拒；重新启用只再 +1，不回退版本号，所以旧令牌仍然 401。
    """
    username = unique("deact")
    assert api.register(username).status_code == 201

    token = api.login(username)
    assert api.get("/me", token=token).status_code == 200
    uid = db.scalar(select(User.id).where(User.username == username))
    before = _version(db, username)

    assert api.patch(f"/users/{uid}", username=admin, json={"is_active": False}).status_code == 200
    assert _version(db, username) == before + 1

    # 停用是「有权限但账户不可用」，与令牌失效区分开。
    denied = api.get("/me", token=token)
    assert denied.status_code == 403, denied.text
    assert denied.json()["message"] == "该账户已被禁用"

    # 停用账户无法登录。
    login = api.client.post(
        f"{API}/login", json={"username": username, "password": DEFAULT_PASSWORD}
    )
    assert login.status_code == 403
    assert login.json()["message"] == "该账户已被禁用"

    # 重新启用后，之前的旧令牌依然失效（版本号未回退），需重新登录。
    assert api.patch(f"/users/{uid}", username=admin, json={"is_active": True}).status_code == 200
    assert _version(db, username) == before + 2
    assert api.get("/me", token=token).status_code == 401
    fresh = api.login(username)
    assert api.get("/me", token=fresh).json()["is_active"] is True


def test_admin_role_change_revokes_tokens(api, admin, db):
    """不变量：平台角色变更也递增 token_version，被降级者无法自我提权。

    验收点：管理员把用户改成 dev -> 版本 +1、旧令牌 401；用户重新登录后
    身份为 dev；再试图把 role 改成 admin 会被 403 拒绝（角色是管理员字段）。
    """
    username = unique("rolechg")
    assert api.register(username).status_code == 201
    token = api.login(username)
    uid = db.scalar(select(User.id).where(User.username == username))
    before = _version(db, username)

    assert api.patch(f"/users/{uid}", username=admin, json={"role": "dev"}).status_code == 200
    assert _version(db, username) == before + 1
    assert api.get("/me", token=token).status_code == 401

    fresh = api.login(username)
    assert api.get("/me", token=fresh).json()["role"] == "dev"

    # 仅管理员可以改角色：被降级用户无法再提升自身。
    assert api.patch(f"/users/{uid}", token=fresh, json={"role": "admin"}).status_code == 403


def test_username_change_revokes_tokens(api, admin, db):
    """不变量：改用户名同样撤销旧令牌，且旧用户名立即不可查（不留别名）。"""
    username = unique("rename")
    assert api.register(username).status_code == 201
    token = api.login(username)
    uid = db.scalar(select(User.id).where(User.username == username))
    before = _version(db, username)

    assert api.patch(f"/users/{uid}", username=admin, json={"username": username + "-new"}).status_code == 200
    # 用户名变更后旧名不再可查，版本号仍然提升。
    assert db.scalar(select(User.id).where(User.username == username)) is None
    after = _version(db, username + "-new")
    assert after == before + 1
    assert api.get("/me", token=token).status_code == 401


def test_self_update_limits(api, admin, db):
    """不变量：用户只允许改自己的非管理字段，角色与状态必须 403。

    验收点：自我提权 403 且 code 为 ERR_FORBIDDEN；自我停用 403；
    自我改名 200（用户名是允许自管的字段）。
    """
    username = unique("selfupd")
    assert api.register(username).status_code == 201
    token = api.login(username)
    uid = db.scalar(select(User.id).where(User.username == username))

    # 普通用户不能提升自己的角色，也不能停用自己（角色/状态是管理员字段，403）。
    escalate = api.patch(f"/users/{uid}", token=token, json={"role": "admin"})
    assert escalate.status_code == 403
    assert escalate.json()["code"] == "ERR_FORBIDDEN"
    self_disable = api.patch(f"/users/{uid}", token=token, json={"is_active": False})
    assert self_disable.status_code == 403

    # 普通用户可以改自己的用户名。
    assert api.patch(f"/users/{uid}", token=token, json={"username": username + "-me"}).status_code == 200


def test_admin_cannot_lock_themselves_out(api, admin, db):
    """不变量：管理员既不能停用自己，也不能删除自己。

    这是平台可用性底线：一旦所有管理员都被停用/删除，就再没有入口恢复平台。
    停用自己返回 400（自相矛盾的操作），删除自己返回 403（禁止删除）。
    """
    admin_uid = db.scalar(select(User.id).where(User.username == admin))

    # 不能停用自己的账户，避免整个平台失去管理员。
    denied = api.patch(f"/users/{admin_uid}", username=admin, json={"is_active": False})
    assert denied.status_code == 400
    # 也不能删除自己。
    assert api.delete(f"/users/{admin_uid}", username=admin).status_code == 403


def test_non_admin_cannot_touch_other_accounts(api, admin, db):
    """不变量：普通用户对他人账号既不能读也不能写；管理员可以全局检索。

    验收点：alice 改/查 bob 都 403，查自己是 200；管理员按 keyword 过滤
    时返回结果全部命中前缀，不会泄漏无关账号。
    """
    alice = unique("alice")
    bob = unique("bob")
    for name in (alice, bob):
        assert api.register(name).status_code == 201
        api.login(name)

    bob_id = db.scalar(select(User.id).where(User.username == bob))

    # 普通用户改不了别人，也查不了别人。
    assert api.patch(f"/users/{bob_id}", username=alice, json={"username": bob + "-hijack"}).status_code == 403
    assert api.get(f"/users/{bob_id}", username=alice).status_code == 403
    # 但可以自己查自己。
    alice_id = db.scalar(select(User.id).where(User.username == alice))
    assert api.get(f"/users/{alice_id}", username=alice).status_code == 200
    # 管理员可以列出全部用户，并能按关键字过滤。
    listing = api.get("/users", username=admin, params={"keyword": bob}).json()
    assert listing["total"] >= 1
    assert all(item["username"].startswith("bob-") for item in listing["items"])


def test_expired_token_is_rejected(api, db):
    """不变量：过期、篡改版本号、错密钥、幽灵用户四类令牌全部 401。

    验收点：exp=0 判定过期；ver=999 与库内版本不符被拒；用错误密钥签发
    的令牌验签失败；sub 指向不存在用户时不泄漏用户名，只返回统一文案。
    """
    username = unique("expired")
    assert api.register(username).status_code == 201
    token = api.login(username)
    uid = db.scalar(select(User.id).where(User.username == username))
    version = _version(db, username)

    # exp=0：已过期。
    expired = jwt.encode(
        {"sub": str(uid), "ver": version, "exp": 0},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    response = api.get("/me", token=expired)
    assert response.status_code == 401, response.text
    assert response.json()["message"] == "登录失效，请重新登录"

    # 版本号对不上的令牌同样拒绝（伪造 ver=999）。
    tampered = jwt.encode(
        {"sub": str(uid), "ver": 999, "exp": 2 ** 31},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    assert api.get("/me", token=tampered).status_code == 401

    # 用错误密钥签发的令牌无法通过。
    foreign = jwt.encode(
        {"sub": str(uid), "ver": version, "exp": 2 ** 31},
        "wrong-secret",
        algorithm=ALGORITHM,
    )
    assert api.get("/me", token=foreign).status_code == 401

    # 令牌指向不存在的用户：不泄露用户名，返回统一文案。
    ghost = jwt.encode(
        {"sub": "999999", "ver": 0, "exp": 2 ** 31},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    ghost_resp = api.get("/me", token=ghost)
    assert ghost_resp.status_code == 401
    assert ghost_resp.json()["message"] == "登录失效，请重新登录"
