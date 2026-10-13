"""验收项 8、9：

- 数据真实落库：新连接、新会话都能看到 API 写入的数据（不是内存态）
- 通知真实写入并可读
- 未接入的能力明确标记「未接入」，查询失败降级而不是伪装成 0
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.features.dashboard.service import readiness
from app.models.identity import Organization, User
from app.models.notification import Notification
from app.models.project import Project
from app.shared.database import SessionLocal

from tests.conftest import DEFAULT_PASSWORD, unique


def test_api_writes_are_persisted_across_sessions(api, admin, db):
    """不变量：API 写入真实落库，同会话与全新会话都能看到，不是内存态或请求内缓存。

    验收点：新建组织 / 项目后，用测试 Session 与第二个 SessionLocal 都能查到同一条
    记录（含 owner 外键关系）；再改一次描述，更新同样在新会话里可见。
    """
    org_name = unique("persist-org")
    project_name = unique("persist-proj")

    org = api.post("/organizations", username=admin, json={"name": org_name}).json()
    project = api.post(
        "/projects",
        username=admin,
        json={"name": project_name, "organization_id": org["id"]},
    ).json()

    # 用同一个会话直接查库：数据确实落到了表里。
    row = db.scalar(select(Organization).where(Organization.name == org_name))
    assert row is not None
    assert row.id == org["id"]

    project_row = db.scalar(select(Project).where(Project.name == project_name))
    assert project_row is not None
    assert project_row.organization_id == org["id"]
    assert project_row.description is None

    # 换一个全新的会话再查，仍然能看到：不是请求内的缓存或内存对象。
    with SessionLocal() as fresh:
        assert fresh.scalar(select(Organization).where(Organization.id == org["id"])).id == org["id"]
        assert fresh.scalar(select(Project).where(Project.id == project["id"])).name == project_name

    # 改一下描述，确认更新同样落库。
    renamed = api.patch(
        f"/projects/{project['id']}",
        username=admin,
        json={"description": "已更新的描述"},
    )
    assert renamed.status_code == 200
    with SessionLocal() as fresh:
        assert fresh.scalar(select(Project).where(Project.id == project["id"])).description == "已更新的描述"


def test_users_and_members_are_persisted(api, admin, db):
    """不变量：管理员建号与删号都真实落库，建号时同步创建个人组织。

    验收点：库里能看到新账号（role / is_active / hashed_password / token_version=0
    全对），并且 owner_id 指向它的个人组织存在；删除后再查用户与成员表都为空。
    """
    username = unique("persist-user")
    created = api.post(
        "/users",
        username=admin,
        json={"username": username, "password": DEFAULT_PASSWORD, "role": "test"},
    ).json()
    assert created["role"] == "test"

    with SessionLocal() as fresh:
        row = fresh.scalar(select(User).where(User.username == username))
        assert row is not None
        assert row.role == "test"
        assert row.is_active is True
        assert row.hashed_password
        assert row.token_version == 0
        # 创建账号的同时创建个人组织。
        personal = fresh.scalar(
            select(Organization).where(Organization.owner_id == row.id)
        )
        assert personal is not None

    # 删除后确实从库里消失。
    assert api.delete(f"/users/{created['id']}", username=admin).status_code == 204
    with SessionLocal() as fresh:
        assert fresh.scalar(select(User).where(User.username == username)) is None


def _count(db, table: str, column: str, value: int) -> int:
    """数「某表某列等于 value」的行数，用于断言删除后库里不再有指向旧用户的行。

    用原生 SQL 而不是 ORM：这样测的是数据库真实状态，而不是被 Session 缓存过的对象。

    Args:
        db: 测试会话，只读使用。
        table: 表名（不含 schema 前缀）。
        column: 列名。
        value: 目标取值（通常是被删用户的 id）。
    Returns:
        int: 匹配行数。
    """
    return int(
        db.execute(
            text(f"select count(*) from {table} where {column} = :v"), {"v": value}
        ).scalar()
    )


def test_deleting_user_hands_over_owned_data(api, admin, db):
    """删除用户时把其拥有的组织与项目转交给下一个成员，不留下无主数据，也不 500。"""
    owner_name = unique("删户-owner")
    keeper_name = unique("删户-keeper")
    for name in (owner_name, keeper_name):
        assert api.register(name).status_code == 201, name
        api.login(name)

    org = api.post(
        "/organizations", username=owner_name, json={"name": unique("删户-组织")}
    ).json()
    keeper_id = api.get("/me", username=keeper_name).json()["id"]
    # 成员授权是幂等 upsert，固定返回 200。
    assert (
        api.put(
            f"/organizations/{org['id']}/members/{keeper_id}",
            username=owner_name,
            json={"user_id": keeper_id, "role": "member"},
        ).status_code
        == 200
    )

    shared = api.post(
        "/projects",
        username=owner_name,
        json={"name": unique("删户-共享项目"), "organization_id": org["id"]},
    ).json()
    assert (
        api.put(
            f"/projects/{shared['id']}/members/{keeper_id}",
            username=owner_name,
            json={"user_id": keeper_id, "role": "member"},
        ).status_code
        == 200
    )
    # 这个项目的成员只有被删用户自己：账号删除后应连带清理。
    orphan = api.post(
        "/projects",
        username=owner_name,
        json={"name": unique("删户-孤立项目"), "organization_id": org["id"]},
    ).json()

    owner_id = api.get("/me", username=owner_name).json()["id"]
    assert api.delete(f"/users/{owner_id}", username=admin).status_code == 204

    # 账号删除后，旧的令牌同样失效。
    assert api.get("/me", token=api.tokens[owner_name]).status_code == 401

    # 数据库里不再有任何一行指向被删用户。
    for table, column in (
        ("organization", "owner_id"),
        ("project", "owner_id"),
        ("organization_member", "user_id"),
        ("project_member", "user_id"),
    ):
        assert _count(db, table, column, owner_id) == 0, (table, column)

    # 有成员的组织被转交：库里 owner 指向接手人，成员表里也标为组织负责人。
    assert (
        db.scalar(select(Organization.owner_id).where(Organization.id == org["id"]))
        == keeper_id
    )
    members_after = api.get(f"/organizations/{org['id']}/members", username=keeper_name)
    assert members_after.status_code == 200, members_after.text
    keeper_row = next(
        item for item in members_after.json()["items"] if item["user_id"] == keeper_id
    )
    assert keeper_row["is_org_owner"] is True
    assert keeper_row["role"] == "owner"

    project_after = api.get(f"/projects/{shared['id']}", username=keeper_name)
    assert project_after.status_code == 200, project_after.text
    assert project_after.json()["owner_id"] == keeper_id

    # 没有其它成员的项目被清理掉，不再是「幽灵项目」。
    assert api.get(f"/projects/{orphan['id']}", username=keeper_name).status_code == 404
    assert db.scalar(select(Project.id).where(Project.id == orphan["id"])) is None


def test_deleting_user_without_successor_cleans_private_data(api, admin, db):
    """没有其它成员的个人组织会被连带清理，而不是留下无人可管理的组织。"""
    name = unique("删户-独行")
    assert api.register(name).status_code == 201
    api.login(name)
    user_id_value = api.get("/me", username=name).json()["id"]

    assert api.delete(f"/users/{user_id_value}", username=admin).status_code == 204
    assert db.scalar(select(User.id).where(User.id == user_id_value)) is None
    assert _count(db, "organization", "owner_id", user_id_value) == 0
    assert _count(db, "organization_member", "user_id", user_id_value) == 0


def test_cannot_delete_admin_or_self(api, admin, db):
    """管理员账户与当前登录账号都不能被删除，避免平台失去管理入口。"""
    admin_id = db.scalar(select(User.id).where(User.username == admin))
    assert api.delete(f"/users/{admin_id}", username=admin).status_code == 403

    lonely = unique("删户-自删")
    assert api.register(lonely).status_code == 201
    token = api.login(lonely)
    lonely_id = api.get("/me", token=token).json()["id"]
    assert api.delete(f"/users/{lonely_id}", token=token).status_code == 403

    # 管理员试图删除其他管理员同样被拒绝。
    second_admin = api.post(
        "/users",
        username=admin,
        json={"username": unique("删户-第二管理员"), "password": DEFAULT_PASSWORD, "role": "admin"},
    ).json()
    assert api.delete(f"/users/{second_admin['id']}", username=admin).status_code == 400


def test_notifications_are_persisted_and_scoped(api, admin, db):
    """不变量：通知真实落库且按用户隔离，标记已读后统计口径随之变化。

    验收点：改名产生 user.updated 通知且初始全为未读；用户本人能读到自己的通知，
    其它人 total 为 0；标记已读落库后 summary 的 unread_total 小于 total。
    """
    username = unique("persist-notif")
    assert api.register(username).status_code == 201
    uid = db.scalar(select(User.id).where(User.username == username))

    # 修改用户名会产生一条 user.updated 通知。
    assert (
        api.patch(f"/users/{uid}", username=admin, json={"username": username + "-renamed"}).status_code
        == 200
    )

    rows = db.scalars(
        select(Notification).where(Notification.user_id == uid)
    ).all()
    assert len(rows) >= 1
    event_types = {row.event_type for row in rows}
    assert "user.updated" in event_types
    assert all(row.is_read is False for row in rows)

    # 用户本人可以读到，且不能读到别人的通知。
    token = api.login(username + "-renamed")
    listing = api.get("/notifications", token=token).json()
    assert listing["total"] >= 1
    assert {"items", "page", "page_size"} <= set(listing)

    other = unique("someone-else")
    assert api.register(other).status_code == 201
    other_token = api.login(other)
    assert api.get("/notifications", token=other_token).json()["total"] == 0

    # 标记已读落库，统计口径随之变化。
    target_id = rows[-1].id
    assert api.post(f"/notifications/{target_id}/read", token=token).status_code == 200
    with SessionLocal() as fresh:
        assert (
            fresh.scalar(
                select(Notification.is_read).where(Notification.id == target_id)
            )
            is True
        )
    summary = api.get("/notifications/summary", token=token).json()
    assert summary["total"] >= 1
    assert summary["unread_total"] < summary["total"]


def test_dashboard_my_projects_is_deduplicated(api, admin):
    """my_projects 按项目去重，不随成员行数放大（防笛卡尔积回归）。"""
    owner_name = unique("看板-owner")
    assert api.register(owner_name).status_code == 201
    api.login(owner_name)
    org = api.post(
        "/organizations", username=owner_name, json={"name": unique("看板-组织")}
    ).json()

    project_ids: list[int] = []
    for _ in range(2):
        created = api.post(
            "/projects",
            username=owner_name,
            json={"name": unique("看板-项目"), "organization_id": org["id"]},
        ).json()
        project_ids.append(created["id"])

    # 每个项目再加三名成员，制造多条 project_member 行。
    for index in range(3):
        member = unique(f"看板-成员{index}")
        assert api.register(member).status_code == 201
        api.login(member)
        member_id = api.get("/me", username=member).json()["id"]
        assert (
            api.put(
                f"/organizations/{org['id']}/members/{member_id}",
                username=owner_name,
                json={"user_id": member_id, "role": "member"},
            ).status_code
            == 200
        )
        for project_id in project_ids:
            assert (
                api.put(
                    f"/projects/{project_id}/members/{member_id}",
                    username=owner_name,
                    json={"user_id": member_id, "role": "member"},
                ).status_code
                == 200
            )

    overview = api.get("/dashboard/overview", username=owner_name).json()
    by_key = {card["key"]: card for card in overview["stats"]}
    assert by_key["my_projects"]["value"] == 2
    assert by_key["projects"]["value"] == 2


def test_unconnected_modules_are_marked_not_connected(api, admin):
    """看板对未接入模块返回「未接入」标记，而不是伪造的 0 统计。

    缺陷已在 Phase-1 接入（bug 表 + CRUD），因此不再出现在未接入集合里，
    而是和 projects/organizations 等一并作为真实计数参与统计。
    """
    overview = api.get("/dashboard/overview", username=admin).json()
    by_key = {card["key"]: card for card in overview["stats"]}

    # 未接入的能力：仍是 Phase-1 明确标记「未接入」的两项。
    for key in ("test_runs", "reports"):
        assert by_key[key]["hint"] == "未接入", (key, by_key[key])
        assert by_key[key]["value"] == 0

    # 已接入的模块返回真实计数，而不是「未接入」占位。
    for key in ("projects", "organizations", "my_projects", "unread_notifications", "defects"):
        assert by_key[key]["hint"] != "未接入"
        assert isinstance(by_key[key]["value"], int)
    assert by_key["organizations"]["value"] >= 1


def test_readiness_reports_real_dependency_state(api, admin):
    """依赖没配置好时如实报 degraded，不谎报 ready。"""
    response = api.get("/dashboard/ready", username=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ready", "degraded", "not_ready"}

    checks = {item["name"]: item for item in body["checks"]}
    assert checks["database"]["status"] == "up"

    # 空库里还没有可用模型，应如实降级。
    if not checks["llm_configs"]["status"] == "up":
        assert body["status"] != "ready"

    # 配好一个可用模型后，数据库项仍然是 up，整体不再因为模型缺失而降级。
    assert (
        api.post(
            "/model-configs",
            username=admin,
            json={
                "domain_id": unique("ready-domain"),
                "label": "就绪检查模型",
                "api_base": "https://api.example.com/v1",
                "model_name": "gpt-4o",
                "api_key": "sk-test-only-readiness-123456",
            },
        ).status_code
        == 201
    )
    after = api.get("/dashboard/ready", username=admin).json()
    after_checks = {item["name"]: item for item in after["checks"]}
    assert after_checks["database"]["status"] == "up"
    assert after_checks["llm_configs"]["status"] == "up"
    assert after["status"] in {"ready", "degraded"}


class _BrokenSession:
    """模拟数据库不可用的会话：任何执行都抛错。"""

    def execute(self, *args, **kwargs):
        """模拟数据库不可用：任何 SQL 执行都抛错。"""
        raise RuntimeError("database unreachable")

    def query(self, *args, **kwargs):
        """同上，覆盖以 query() 访问会话的调用路径。"""
        raise RuntimeError("database unreachable")


def test_readiness_degrades_to_not_ready_when_database_is_unavailable():
    """数据库不可用时整体降级为 not_ready，而不是返回空的 0 统计。"""
    result = readiness(_BrokenSession())  # type: ignore[arg-type]
    assert result.status == "not_ready"
    assert [check.name for check in result.checks] == ["database"]
    assert result.checks[0].status == "down"
    assert result.checks[0].detail == "RuntimeError"
