"""权限模型边界、跨组织隔离、退出组织可见性与注册事务原子性专项验收。"""
from __future__ import annotations

import pytest

from app.core.models.identity import User
from app.platform.users.services import user_service
from tests.conftest import unique


def _register_and_login(api, prefix: str) -> tuple[str, int]:
    username = unique(prefix)
    res = api.register(username)
    assert res.status_code == 201, res.text
    api.login(username)
    me = api.get("/me", username=username)
    assert me.status_code == 200, me.text
    return username, me.json()["id"]


def test_org_admin_manages_only_authorized_org_and_respects_boundaries(api):
    alice, _ = _register_and_login(api, "alice_owner")
    bob, bob_id = _register_and_login(api, "bob_org_admin")
    carol, carol_id = _register_and_login(api, "carol_org_mem")
    dave, dave_id = _register_and_login(api, "dave_outsider")

    org_a_resp = api.post("/organizations", username=alice, json={"name": unique("org-a")})
    assert org_a_resp.status_code == 201, org_a_resp.text
    org_a_id = org_a_resp.json()["id"]

    org_b_resp = api.post("/organizations", username=dave, json={"name": unique("org-b")})
    assert org_b_resp.status_code == 201, org_b_resp.text
    org_b_id = org_b_resp.json()["id"]

    # Bob becomes admin of Org A; Carol becomes plain member of Org A.
    assert (
        api.put(
            f"/organizations/{org_a_id}/members/{bob_id}",
            username=alice,
            json={"user_id": bob_id, "role": "admin"},
        ).status_code
        == 200
    )
    assert (
        api.put(
            f"/organizations/{org_a_id}/members/{carol_id}",
            username=alice,
            json={"user_id": carol_id, "role": "member"},
        ).status_code
        == 200
    )

    # Org admin Bob can update Org A, manage Org A members, and create a project in Org A.
    assert (
        api.patch(
            f"/organizations/{org_a_id}",
            username=bob,
            json={"name": unique("org-a-renamed")},
        ).status_code
        == 200
    )
    project_resp = api.post(
        "/projects",
        username=bob,
        json={"name": unique("org-a-proj"), "organization_id": org_a_id},
    )
    assert project_resp.status_code == 201, project_resp.text
    assert api.get(f"/organizations/{org_a_id}/members", username=bob).status_code == 200

    # Org admin Bob is NOT platform admin: cannot delete Org A or access platform statistics/org B.
    assert api.delete(f"/organizations/{org_a_id}", username=bob).status_code == 403
    assert api.get("/dashboard/platform", username=bob).status_code == 403
    assert api.get("/users", username=bob).status_code == 403

    # Cross-org boundary: Bob gets 404 on Org B (does not leak existence).
    assert api.get(f"/organizations/{org_b_id}/members", username=bob).status_code == 404
    assert (
        api.patch(
            f"/organizations/{org_b_id}",
            username=bob,
            json={"name": unique("hijack")},
        ).status_code
        == 404
    )
    assert (
        api.put(
            f"/organizations/{org_b_id}/members/{carol_id}",
            username=bob,
            json={"user_id": carol_id, "role": "member"},
        ).status_code
        == 404
    )
    assert (
        api.post(
            "/projects",
            username=bob,
            json={"name": unique("cross-org-proj"), "organization_id": org_b_id},
        ).status_code
        == 404
    )

    # Plain Org member Carol gets 403 for Org A admin operations.
    assert (
        api.patch(
            f"/organizations/{org_a_id}",
            username=carol,
            json={"name": unique("carol-rename")},
        ).status_code
        == 403
    )
    assert (
        api.put(
            f"/organizations/{org_a_id}/members/{dave_id}",
            username=carol,
            json={"user_id": dave_id, "role": "member"},
        ).status_code
        == 403
    )
    assert (
        api.post(
            "/projects",
            username=carol,
            json={"name": unique("carol-proj"), "organization_id": org_a_id},
        ).status_code
        == 403
    )

    # Outsider Dave gets 404 on Org A.
    assert api.get(f"/organizations/{org_a_id}/members", username=dave).status_code == 404
    assert api.get(f"/projects/{project_resp.json()['id']}", username=dave).status_code == 404


def test_leaving_org_revokes_project_and_dashboard_visibility_without_duplicates(api):
    owner, _ = _register_and_login(api, "org_owner")
    member, member_id = _register_and_login(api, "org_leaver")

    org = api.post("/organizations", username=owner, json={"name": unique("team-org")}).json()
    proj = api.post(
        "/projects",
        username=owner,
        json={"name": unique("team-proj"), "organization_id": org["id"]},
    ).json()

    assert (
        api.put(
            f"/organizations/{org['id']}/members/{member_id}",
            username=owner,
            json={"user_id": member_id, "role": "member"},
        ).status_code
        == 200
    )
    assert (
        api.put(
            f"/projects/{proj['id']}/members/{member_id}",
            username=owner,
            json={"user_id": member_id, "role": "editor"},
        ).status_code
        == 200
    )

    # Project appears once in both /projects and /dashboard/projects even with dual membership.
    proj_list = api.get("/projects", username=member, params={"page": 1, "page_size": 100}).json()["items"]
    assert [item["id"] for item in proj_list].count(proj["id"]) == 1

    dash_projects = api.get("/dashboard/projects", username=member, params={"page": 1, "page_size": 100}).json()["items"]
    assert [item["id"] for item in dash_projects].count(proj["id"]) == 1

    # Remove user from organization -> historical project membership no longer exposes org data.
    assert api.delete(f"/organizations/{org['id']}/members/{member_id}", username=owner).status_code == 204
    assert api.get(f"/organizations/{org['id']}/members", username=member).status_code == 404
    assert api.get(f"/projects/{proj['id']}", username=member).status_code == 404

    proj_after = api.get("/projects", username=member, params={"page": 1, "page_size": 100}).json()["items"]
    assert all(item["id"] != proj["id"] for item in proj_after)

    dash_after = api.get("/dashboard/projects", username=member, params={"page": 1, "page_size": 100}).json()["items"]
    assert all(item["id"] != proj["id"] for item in dash_after)


def test_project_viewer_member_editor_boundaries(api):
    owner, _ = _register_and_login(api, "proj_owner")
    editor, editor_id = _register_and_login(api, "proj_editor")
    member, member_id = _register_and_login(api, "proj_member")
    viewer, viewer_id = _register_and_login(api, "proj_viewer")
    outsider, _ = _register_and_login(api, "proj_outsider")

    org = api.post("/organizations", username=owner, json={"name": unique("role-org")}).json()
    p1 = api.post(
        "/projects",
        username=owner,
        json={"name": unique("p1"), "organization_id": org["id"]},
    ).json()
    p2 = api.post(
        "/projects",
        username=owner,
        json={"name": unique("p2"), "organization_id": org["id"]},
    ).json()

    for uid in (editor_id, member_id, viewer_id):
        assert (
            api.put(
                f"/organizations/{org['id']}/members/{uid}",
                username=owner,
                json={"user_id": uid, "role": "member"},
            ).status_code
            == 200
        )
    assert (
        api.put(
            f"/projects/{p1['id']}/members/{editor_id}",
            username=owner,
            json={"user_id": editor_id, "role": "editor"},
        ).status_code
        == 200
    )
    assert (
        api.put(
            f"/projects/{p1['id']}/members/{member_id}",
            username=owner,
            json={"user_id": member_id, "role": "member"},
        ).status_code
        == 200
    )
    assert (
        api.put(
            f"/projects/{p1['id']}/members/{viewer_id}",
            username=owner,
            json={"user_id": viewer_id, "role": "viewer"},
        ).status_code
        == 200
    )

    # Viewer can read project & list defects, but cannot create/modify project data.
    assert api.get(f"/projects/{p1['id']}", username=viewer).status_code == 200
    assert api.get("/bugs", username=viewer, params={"project_id": p1["id"]}).status_code == 200
    assert (
        api.post(
            "/bugs",
            username=viewer,
            json={"project_id": p1["id"], "title": "viewer bug", "severity": 2},
        ).status_code
        == 403
    )

    # Member & Editor can read/write P1, cannot access P2 (cross-project returns 404), Outsider gets 404 on P1.
    assert (
        api.post(
            "/bugs",
            username=member,
            json={"project_id": p1["id"], "title": "member bug", "severity": 2},
        ).status_code
        == 201
    )
    assert (
        api.post(
            "/bugs",
            username=editor,
            json={"project_id": p1["id"], "title": "editor bug", "severity": 2},
        ).status_code
        == 201
    )
    assert api.get(f"/projects/{p2['id']}", username=editor).status_code == 404
    assert (
        api.post(
            "/bugs",
            username=editor,
            json={"project_id": p2["id"], "title": "cross project bug", "severity": 2},
        ).status_code
        == 404
    )
    assert api.get(f"/projects/{p1['id']}", username=outsider).status_code == 404


def test_registration_rolls_back_user_when_personal_org_fails(api, db, monkeypatch):
    username = unique("rollback_user")

    def boom(_db, _user):
        raise RuntimeError("personal org init failed")

    monkeypatch.setattr(user_service, "ensure_personal_organization", boom)
    with pytest.raises(RuntimeError, match="personal org init failed"):
        api.register(username)

    db.expire_all()
    assert db.query(User).filter(User.username == username).first() is None
