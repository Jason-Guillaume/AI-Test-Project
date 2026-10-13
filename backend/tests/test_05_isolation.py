"""验收项 7：组织与项目边界隔离。

- 跨组织、跨项目不可见（按 404 隐藏存在性，而不是 403 泄漏）
- viewer 只能读，不能改
- 平台管理员也不能绕开「成员必须是项目所属组织成员」的约束
- 历史遗留的跨组织成员关系行仍然不可见（组织边界优先于项目成员关系）

组织与项目名在每次夹具构建时取唯一值，避免同一测试会话内重复创建冲突。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.project import ProjectMember

from tests.conftest import unique

# 用户名 -> 用户 ID 的进程内缓存：同一测试会话里同一用户的 ID 不会变，
# 复用可省掉重复的 /me 请求（不会跨会话共享，session 作用域结束即失效）。
USER_ID_CACHE: dict[str, int] = {}


def user_id(api, username: str) -> int:
    """取用户 ID（测试内缓存，避免重复请求）。"""
    if username not in USER_ID_CACHE:
        USER_ID_CACHE[username] = api.get("/me", username=username).json()["id"]
    return USER_ID_CACHE[username]


def _create_org(api, actor: str, name: str) -> dict:
    """以 actor 身份创建一个组织，并断言创建成功（失败直接让用例红掉）。

    Args:
        actor: 用于发起请求的登录用户名（组织负责人）。
        name: 组织名，约定由调用方加唯一 tag，避免同会话内重复创建。
    Returns:
        dict: 创建后的组织对象，含 id 供后续挂项目与加成员。
    """
    response = api.post("/organizations", username=actor, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _create_project(api, actor: str, name: str, organization_id: int | None = None) -> dict:
    """以 actor 身份在项目所属组织下建项目，并断言创建成功。

    Args:
        actor: 发起请求的登录用户名（项目创建人）。
        name: 项目名，约定由调用方加唯一 tag。
        organization_id: 归属组织 ID；省略时使用默认组织。
    Returns:
        dict: 创建后的项目对象，含 id 供后续加成员与做可见性断言。
    """
    response = api.post(
        "/projects",
        username=actor,
        json={"name": name, "organization_id": organization_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def orgs(api):
    """两个互不相干的组织：alice 的 A 组与 bob 的 B 组；carol 是 A 组成员、A 项目只读。"""
    tag = unique("隔离")
    org_a_name = f"org-a-{tag}-隔离组"
    org_b_name = f"org-b-{tag}-隔离组"
    project_a_name = f"proj-a-{tag}-项目甲"
    project_b_name = f"proj-b-{tag}-项目乙"

    alice, bob, carol = (unique(n) for n in ("alice", "bob", "carol"))
    for name in (alice, bob, carol):
        response = api.register(name)
        assert response.status_code == 201, response.text
        api.login(name)

    org_a = _create_org(api, alice, org_a_name)
    org_b = _create_org(api, bob, org_b_name)
    project_a = _create_project(api, alice, project_a_name, org_a["id"])
    project_b = _create_project(api, bob, project_b_name, org_b["id"])

    carol_db_id = user_id(api, carol)
    # 成员授权是幂等 upsert，无论新建还是更新都返回 200。
    added = api.put(
        f"/organizations/{org_a['id']}/members/{carol_db_id}",
        username=alice,
        json={"user_id": carol_db_id, "role": "member", "agent_enabled": False},
    )
    assert added.status_code == 200, added.text
    assert added.json()["role"] == "member"

    viewer = api.put(
        f"/projects/{project_a['id']}/members/{carol_db_id}",
        username=alice,
        json={"user_id": carol_db_id, "role": "viewer"},
    )
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["role"] == "viewer"

    return {
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "org_a": org_a,
        "org_b": org_b,
        "project_a": project_a,
        "project_b": project_b,
        "org_a_name": org_a_name,
        "org_b_name": org_b_name,
        "project_a_name": project_a_name,
        "project_b_name": project_b_name,
    }


def test_owner_can_see_only_own_projects(api, orgs):
    """不变量：项目列表按可见性过滤，负责人只看到本组织的项目，且不泄漏他人项目名。

    验收点：alice 的列表恰好只有 A 组项目乙之外的那一条（project_a），bob 只看到
    project_b，两边 total 都是 1。
    """
    alice_projects = api.get("/projects", username=orgs["alice"]).json()
    assert [item["name"] for item in alice_projects["items"]] == [orgs["project_a_name"]]
    assert alice_projects["total"] == 1

    bob_projects = api.get("/projects", username=orgs["bob"]).json()
    assert [item["name"] for item in bob_projects["items"]] == [orgs["project_b_name"]]
    assert bob_projects["total"] == 1


def test_cross_organization_access_returns_404(api, orgs):
    """不变量：跨组织访问一律按 404 处理，而不是 403——避免泄漏资源是否存在的信息。

    覆盖读（详情 / 成员表 / 外部目标）、写（改名）、组织侧（改名 / 看成员表 /
    自行加入）与不存在的项目 ID：全部返回 404，ERR_NOT_FOUND 只对组织侧暴露。
    """
    project_a_id = orgs["project_a"]["id"]
    org_a_id = orgs["org_a"]["id"]
    bob = orgs["bob"]

    detail = api.get(f"/projects/{project_a_id}", username=bob)
    assert detail.status_code == 404, detail.text
    assert detail.json()["code"] == "ERR_NOT_FOUND"

    write = api.patch(
        f"/projects/{project_a_id}", username=bob, json={"description": "跨组织写入"}
    )
    assert write.status_code == 404

    members = api.get(f"/projects/{project_a_id}/members", username=bob)
    assert members.status_code == 404

    targets = api.get(f"/projects/{project_a_id}/targets", username=bob)
    assert targets.status_code == 404

    # 组织侧统一按 404 隐藏存在性：改名、看成员表、自行加入都不放行。
    rename_org = api.patch(
        f"/organizations/{org_a_id}", username=bob, json={"name": "被劫持的组织"}
    )
    assert rename_org.status_code == 404
    assert rename_org.json()["code"] == "ERR_NOT_FOUND"

    org_members = api.get(f"/organizations/{org_a_id}/members", username=bob)
    assert org_members.status_code == 404
    assert org_members.json()["code"] == "ERR_NOT_FOUND"

    own_id = api.get("/me", username=bob).json()["id"]
    assert (
        api.put(
            f"/organizations/{org_a_id}/members/{own_id}",
            username=bob,
            json={"user_id": own_id, "role": "member"},
        ).status_code
        == 404
    )

    # 即使传上不存在的项目 ID，也拿不到数据。
    assert api.get("/projects/99999999", username=bob).status_code == 404


def test_viewer_can_read_but_not_write(api, orgs):
    """不变量：viewer 角色只有读权限，任何写操作都 403，且错误码统一为 ERR_FORBIDDEN。

    验收点：详情 / 成员表可读且 my_role 为 viewer；改项目、删项目、加成员、
    抢 owner、改组织名全部 403。组织成员能读成员表但不能改组织。
    """
    project_id = orgs["project_a"]["id"]
    carol = orgs["carol"]

    detail = api.get(f"/projects/{project_id}", username=carol)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["name"] == orgs["project_a_name"]
    assert body["organization_id"] == orgs["org_a"]["id"]
    assert body["my_role"] == "viewer"

    assert api.get(f"/projects/{project_id}/members", username=carol).status_code == 200

    carol_id_value = user_id(api, carol)
    for method, path, kwargs in (
        ("patch", f"/projects/{project_id}", {"json": {"description": "只读用户修改"}}),
        ("delete", f"/projects/{project_id}", {}),
        (
            "put",
            f"/projects/{project_id}/members/{carol_id_value}",
            {"json": {"user_id": carol_id_value, "role": "editor"}},
        ),
        ("post", f"/projects/{project_id}/owner", {"json": {"user_id": carol_id_value}}),
    ):
        response = getattr(api, method)(path, username=carol, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["code"] == "ERR_FORBIDDEN"

    # 组织成员可以读成员表，但不能改组织。
    member_list = api.get(f"/organizations/{orgs['org_a']['id']}/members", username=carol)
    assert member_list.status_code == 200
    roles = {item["role"] for item in member_list.json()["items"]}
    assert "owner" in roles
    assert "member" in roles

    assert api.patch(
        f"/organizations/{orgs['org_a']['id']}",
        username=carol,
        json={"name": "只读用户改组织"},
    ).status_code == 403

    # carol 自己的个人组织 + A 组都在可见范围内。
    my_orgs = api.get("/organizations", username=carol).json()
    assert my_orgs["total"] == 2
    assert orgs["org_a_name"] in [item["name"] for item in my_orgs["items"]]


def test_org_member_sees_org_projects_but_not_others(api, orgs):
    """不变量：项目可见性由组织成员身份推导，只看得到自己所属组织的项目。

    验收点：carol 是 A 组成员，所以能看到 A 组项目；B 组项目名绝不出现，
    即使她的账号存在。
    """
    carol = orgs["carol"]
    carol_projects = api.get("/projects", username=carol).json()
    # A 组成员能看到 A 组全部项目，但看不到 B 组项目。
    names = [item["name"] for item in carol_projects["items"]]
    assert orgs["project_a_name"] in names
    assert orgs["project_b_name"] not in names


def test_cross_org_member_addition_is_forbidden_even_for_platform_admin(api, admin, orgs):
    """平台管理员也不能把「非项目所属组织成员」加为项目成员。"""
    project_b_id = orgs["project_b"]["id"]
    carol = orgs["carol"]
    carol_id_value = user_id(api, carol)

    response = api.put(
        f"/projects/{project_b_id}/members/{carol_id_value}",
        username=admin,
        json={"user_id": carol_id_value, "role": "viewer"},
    )
    assert response.status_code == 403, response.text
    assert "组织" in response.json()["message"]

    # 反过来：非管理员把非本组织用户加进来同样被拒绝。
    alice_project = orgs["project_a"]["id"]
    bob_id = api.get("/me", username=orgs["bob"]).json()["id"]
    assert (
        api.put(
            f"/projects/{alice_project}/members/{bob_id}",
            username=orgs["alice"],
            json={"user_id": bob_id, "role": "viewer"},
        ).status_code
        == 403
    )


def test_leftover_cross_org_member_row_stays_invisible(api, admin, orgs, db):
    """即使数据库里残留了跨组织的项目成员行（历史迁移数据），也不可见。"""
    carol = orgs["carol"]
    carol_id_value = user_id(api, carol)
    project_b_id = orgs["project_b"]["id"]

    inserted = db.execute(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_b_id,
            ProjectMember.user_id == carol_id_value,
        )
    )
    assert inserted.first() is None

    # 用 ORM 直接插一条跨组织成员行并提交，绕过 API 层的组织边界校验，
    # 模拟「历史迁移数据里已经残留这种脏行」的场景。
    db.add(
        ProjectMember(
            project_id=project_b_id,
            user_id=carol_id_value,
            role="editor",
            created_by=carol_id_value,
        )
    )
    db.commit()

    role = db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_b_id,
            ProjectMember.user_id == carol_id_value,
        )
    )
    assert role == "editor"

    # 仍然看不到 B 组项目：组织边界优先于项目成员关系。
    assert api.get(f"/projects/{project_b_id}", username=carol).status_code == 404
    names = [
        item["name"] for item in api.get("/projects", username=carol).json()["items"]
    ]
    assert orgs["project_b_name"] not in names

    # 可见项目集合里没有 B 组项目 ID。
    dashboard = api.get("/dashboard/overview", username=carol).json()
    assert project_b_id not in dashboard["scope"]["project_ids"]
    assert dashboard["scope"]["is_platform_admin"] is False

    # 平台管理员视图不做项目过滤：同一项目对管理员可见，统计口径也标记为全平台。
    platform_detail = api.get(f"/projects/{project_b_id}", username=admin)
    assert platform_detail.status_code == 200, platform_detail.text
    assert platform_detail.json()["name"] == orgs["project_b_name"]

    platform = api.get("/dashboard/platform", username=admin).json()
    assert platform["scope"]["is_platform_admin"] is True
    assert platform["scope"]["project_ids"] == []
