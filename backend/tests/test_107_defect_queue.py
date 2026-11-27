"""缺陷队列工作流（无指派人模型）回归：动作闭环、并发、幂等、草稿、归档、批量、模板、开关与提醒。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import settings
from app.core.models.notification import Notification
from app.features.defects.models.bug import Bug
from app.features.defects.services.reminder_worker import send_stale_reminders
from tests.conftest import unique

_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _create_project(api, actor):
    response = api.post("/projects", username=actor, json={"name": unique("queue-proj"), "description": "queue"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _register(api, username):
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username, "Init-Password-123")
    return response.json()["user"]["id"]


def _add_member(api, actor, project_id, user_id, role):
    response = api.put(
        f"/projects/{project_id}/members/{user_id}", username=actor, json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text


def _bug(api, actor, project_id, title="队列缺陷", **extra):
    body = {"project_id": project_id, "title": title}
    body.update(extra)
    response = api.post("/bugs", username=actor, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _action(api, actor, bug_id, action, **extra):
    return api.post(f"/bugs/{bug_id}/actions", username=actor, json={"action": action, **extra})


# ---------------------------------------------------------------- 动作闭环

def test_full_regression_loop_with_activities(api, admin):
    """确认→登记可回归→回归失败→再登记→回归通过；活动事件与状态同事务落库。"""
    project_id = _create_project(api, admin)
    bug = _bug(api, admin, project_id, severity=2)
    bug_id = bug["id"]
    assert bug["status"] == "待确认"
    assert bug["record_version"] == 0

    # 确认问题并补齐事实字段
    r = _action(api, admin, bug_id, "confirm", severity=4, environment="staging")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bug"]["status"] == "处理中"
    assert body["bug"]["severity"] == 4
    assert body["bug"]["environment"] == "staging"
    assert body["bug"]["record_version"] == 1
    assert body["activity"]["action"] == "confirm"
    assert body["activity"]["old_status"] == "待确认"
    assert body["activity"]["new_status"] == "处理中"

    # 登记可回归必须携带版本/构建/环境
    missing = _action(api, admin, bug_id, "ready_for_regression")
    assert missing.status_code == 400
    r = _action(api, admin, bug_id, "ready_for_regression", fix_version="build-1024", feedback_source="飞书群反馈")
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "已修复"
    assert r.json()["bug"]["status_display"] == "待验证"
    assert r.json()["bug"]["fix_version"] == "build-1024"

    # 回归失败必须写原因，回到处理中
    no_note = _action(api, admin, bug_id, "regression_fail")
    assert no_note.status_code == 400
    r = _action(api, admin, bug_id, "regression_fail", note="build-1024 仍复现 500", verification_environment="staging")
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "处理中"

    # 第二个构建登记后回归通过关闭
    r = _action(api, admin, bug_id, "ready_for_regression", fix_version="build-1025")
    assert r.status_code == 200, r.text
    no_conclusion = _action(api, admin, bug_id, "regression_pass")
    assert no_conclusion.status_code == 400
    r = _action(api, admin, bug_id, "regression_pass", note="build-1025 验证通过", verification_environment="staging")
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "已关闭"

    activities = api.get(f"/bugs/{bug_id}/activities", username=admin)
    assert activities.status_code == 200
    actions = [item["action"] for item in activities.json()]
    assert actions == [
        "regression_pass", "ready_for_regression", "regression_fail",
        "ready_for_regression", "confirm", "created",
    ]
    labels = {item["action"]: item["action_label"] for item in activities.json()}
    assert labels["regression_pass"] == "回归通过"


def test_reject_duplicate_and_reopen(api, admin):
    """拒绝/判重进入已拒绝；重开回到待确认；判重主单必须同项目。"""
    project_id = _create_project(api, admin)
    other_project = _create_project(api, admin)
    main_bug = _bug(api, admin, project_id, "主单")
    dup = _bug(api, admin, project_id, "重复单")
    foreign = _bug(api, admin, other_project, "外项目单")
    rejected = _bug(api, admin, project_id, "非缺陷")

    assert _action(api, admin, rejected["id"], "reject").status_code == 400
    r = _action(api, admin, rejected["id"], "reject", note="按需求属预期行为")
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "已拒绝"

    assert _action(api, admin, dup["id"], "mark_duplicate").status_code == 400
    assert _action(api, admin, dup["id"], "mark_duplicate", duplicate_of_bug_id=dup["id"]).status_code == 400
    assert _action(api, admin, dup["id"], "mark_duplicate", duplicate_of_bug_id=foreign["id"]).status_code == 400
    r = _action(api, admin, dup["id"], "mark_duplicate", duplicate_of_bug_id=main_bug["id"])
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "已拒绝"
    assert r.json()["bug"]["duplicate_of_bug_id"] == main_bug["id"]

    assert _action(api, admin, rejected["id"], "reopen").status_code == 400
    r = _action(api, admin, rejected["id"], "reopen", note="新版本复现，重新跟进")
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "待确认"


def test_action_concurrency_and_invalid_transition(api, admin):
    """版本不一致返回 409 与最新状态；非法流转返回 409 提示当前展示状态。"""
    project_id = _create_project(api, admin)
    bug = _bug(api, admin, project_id)
    bug_id = bug["id"]

    # 甲基于版本 0 确认成功
    r = _action(api, admin, bug_id, "confirm", expected_version=0)
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["record_version"] == 1

    # 乙仍拿版本 0 提交：409 携带最新记录版本与状态
    stale = _action(api, admin, bug_id, "ready_for_regression", expected_version=0, fix_version="b1")
    assert stale.status_code == 409
    meta = stale.json()["meta"]
    assert meta["record_version"] == 1
    assert meta["status"] == "处理中"

    # 乙刷新后按最新版本重试成功
    r = _action(api, admin, bug_id, "ready_for_regression", expected_version=1, fix_version="b1")
    assert r.status_code == 200, r.text

    # 已修复（待验证）不能再次确认
    wrong = _action(api, admin, bug_id, "confirm")
    assert wrong.status_code == 409
    assert "待验证" in wrong.text


def test_external_resolved_enters_pending_verify(api, admin, db, monkeypatch):
    """外部已解决反馈进入待验证并记录外部活动；关闭只能走内部回归。"""
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")

    def fake_post(url, json=None, **kwargs):
        class Response:
            status_code = 200
            text = "ok"

            def json(self):
                return {"code": 0, "msg": "success"}

        return Response()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", fake_post)
    project_id = _create_project(api, admin)
    channel = api.post(
        f"/projects/{project_id}/notification-channels", username=admin,
        json={"name": "群", "webhook_url": _WEBHOOK, "secret": "s", "enabled": True},
    ).json()["id"]
    bug = _bug(api, admin, project_id)
    share = api.post(
        f"/bugs/{bug['id']}/shares", username=admin,
        json={"channel_id": channel, "expires_in_days": 7, "allow_resolve": True},
    ).json()
    token = share["share_url"].split("#token=", 1)[1]
    resolved = api.client.post(
        f"/api/v1/public/defect-shares/{share['share_id']}/resolve",
        headers={"Authorization": f"Bearer {token}"},
        json={"repair_description": "外部已修复", "fix_version": "v9", "reporter_name": "王开发"},
    )
    assert resolved.status_code == 200, resolved.text
    db.expire_all()
    stored = db.get(Bug, bug["id"])
    assert stored.status == "已修复"
    activities = api.get(f"/bugs/{bug['id']}/activities", username=admin).json()
    external = [item for item in activities if item["action"] == "external_resolved"]
    assert external and external[0]["actor_type"] == "EXTERNAL_SHARE"
    # 内部回归通过后才关闭
    r = _action(api, admin, bug["id"], "regression_pass", note="内部回归通过")
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "已关闭"


# ---------------------------------------------------------------- 幂等与草稿

def test_create_request_key_idempotency(api, admin):
    """同键同内容重试返回同一缺陷；同键不同内容 409。"""
    project_id = _create_project(api, admin)
    body = {"project_id": project_id, "title": "超时重试单", "request_key": unique("rk")}
    first = api.post("/bugs", username=admin, json=body)
    assert first.status_code == 201, first.text
    replay = api.post("/bugs", username=admin, json=body)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert api.get("/bugs", username=admin, params={"project_id": project_id}).json()["total"] == 1

    changed = dict(body, title="换了内容")
    conflict = api.post("/bugs", username=admin, json=changed)
    assert conflict.status_code == 409


def test_draft_lifecycle(api, admin):
    """草稿不进队列；提交后进入待确认并补发创建通知。"""
    project_id = _create_project(api, admin)
    draft = _bug(api, admin, project_id, "草稿单", is_draft=True)
    assert draft["is_draft"] is True

    default_list = api.get("/bugs", username=admin, params={"project_id": project_id}).json()
    assert default_list["total"] == 0
    with_drafts = api.get("/bugs", username=admin, params={"project_id": project_id, "include_drafts": True}).json()
    assert with_drafts["total"] == 1

    assert _action(api, admin, draft["id"], "confirm").status_code == 409
    submitted = api.post(f"/bugs/{draft['id']}/submit-draft", username=admin)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["is_draft"] is False
    assert submitted.json()["status"] == "待确认"

    notifs = api.get("/notifications", username=admin, params={"page_size": 20}).json()["items"]
    assert any(
        item["event_type"] == "defect.created" and item["payload"]["detail"]["bug_id"] == draft["id"]
        for item in notifs
    )


# ---------------------------------------------------------------- 队列与统计

def test_queue_counts_match_list_totals(api, admin):
    """快捷队列计数与同条件列表 total 一致。"""
    project_id = _create_project(api, admin)
    pending = _bug(api, admin, project_id, "待确认单")
    progress = _bug(api, admin, project_id, "处理中单")
    verify = _bug(api, admin, project_id, "待验证单")
    closed = _bug(api, admin, project_id, "已关闭单")
    rejected = _bug(api, admin, project_id, "已拒绝单")
    _bug(api, admin, project_id, "归档单")
    _bug(api, admin, project_id, "草稿单", is_draft=True)
    _action(api, admin, progress["id"], "confirm")
    _action(api, admin, verify["id"], "confirm")
    _action(api, admin, verify["id"], "ready_for_regression", fix_version="b1")
    _action(api, admin, closed["id"], "confirm")
    _action(api, admin, closed["id"], "ready_for_regression", fix_version="b1")
    _action(api, admin, closed["id"], "regression_pass", note="通过")
    _action(api, admin, rejected["id"], "reject", note="拒绝")
    archived = api.get("/bugs", username=admin, params={"project_id": project_id, "keyword": "归档单"}).json()["items"][0]
    api.post(f"/bugs/{archived['id']}/archive", username=admin, json={"reason": "过期归档"})

    queues = api.get("/bugs/queues", username=admin, params={"project_id": project_id}).json()
    assert queues["pending_confirm"] == 1
    assert queues["in_progress"] == 1
    assert queues["pending_verify"] == 1
    assert queues["closed"] == 1
    assert queues["rejected"] == 1
    assert queues["unclosed"] == 3
    assert queues["archived"] == 1
    assert queues["drafts"] == 1
    assert queues["reported_by_me"] == 5

    def total(**params):
        return api.get("/bugs", username=admin, params={"project_id": project_id, **params}).json()["total"]

    assert total(status="待确认") == queues["pending_confirm"]
    assert total(status="处理中") == queues["in_progress"]
    assert total(status="已修复") == queues["pending_verify"]
    assert total(status="已关闭") == queues["closed"]
    assert total(status="已拒绝") == queues["rejected"]
    assert total(status_group="unclosed") == queues["unclosed"]
    assert total(mine=True) == queues["reported_by_me"]
    assert total(view="archived") == queues["archived"]
    assert total(view="drafts") == queues["drafts"]
    assert total(include_archived=True) == 6
    assert api.get("/bugs", username=admin, params={"view": "bogus"}).status_code == 422
    assert pending["id"]


def test_stats_regression_failure_rate_and_backlog(api, admin):
    """回归失败率 = 期内失败验证 / 全部验证，附样本量；积压按状态统计。"""
    project_id = _create_project(api, admin)
    a = _bug(api, admin, project_id, "失败样本")
    b = _bug(api, admin, project_id, "通过样本")
    for bug in (a, b):
        _action(api, admin, bug["id"], "confirm")
        _action(api, admin, bug["id"], "ready_for_regression", fix_version="b1")
    _action(api, admin, a["id"], "regression_fail", note="仍复现")
    _action(api, admin, b["id"], "regression_pass", note="通过")

    stats = api.get("/bugs/stats", username=admin, params={"project_id": project_id}).json()
    assert stats["regression_total"] == 2
    assert stats["regression_failed"] == 1
    assert stats["regression_failure_rate"] == 0.5
    assert stats["first_confirm_sample"] == 2
    assert stats["first_confirm_hours_avg"] is not None
    assert stats["backlog"]["处理中"] == 1
    assert stats["backlog"]["已关闭"] == 1

    empty = api.get("/bugs/stats", username=admin, params={"project_id": _create_project(api, admin)}).json()
    assert empty["regression_total"] == 0
    assert empty["regression_failure_rate"] is None


def test_list_returns_summary_without_heavy_fields(api, admin):
    """列表只返回摘要；请求体/响应正文等重字段仅在详情返回。"""
    project_id = _create_project(api, admin)
    bug = _bug(
        api, admin, project_id, "接口摘要单", category="接口",
        api_method="POST", api_url="/v1/login",
        api_request_headers='{"Authorization": "Bearer x"}',
        api_request_body='{"password": "***"}', api_response='{"code": 500}',
    )
    item = api.get("/bugs", username=admin, params={"project_id": project_id}).json()["items"][0]
    assert item["id"] == bug["id"]
    assert item["api_request_headers"] is None
    assert item["api_request_body"] is None
    assert item["api_response"] is None
    detail = api.get(f"/bugs/{bug['id']}", username=admin).json()
    assert detail["api_request_body"] == '{"password": "***"}'
    assert detail["api_response"] == '{"code": 500}'


# ---------------------------------------------------------------- 归档与批量

def test_archive_permissions_revocation_and_restore(api, admin, monkeypatch):
    """归档需 editor+；归档撤销全部有效分享；撤销归档后恢复列表可见。"""
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")

    def fake_post(url, json=None, **kwargs):
        class Response:
            status_code = 200
            text = "ok"

            def json(self):
                return {"code": 0, "msg": "success"}

        return Response()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", fake_post)
    project_id = _create_project(api, admin)
    member_name = unique("member")
    member_id = _register(api, member_name)
    _add_member(api, admin, project_id, member_id, "member")
    bug = _bug(api, admin, project_id)
    channel = api.post(
        f"/projects/{project_id}/notification-channels", username=admin,
        json={"name": "群", "webhook_url": _WEBHOOK, "secret": "s", "enabled": True},
    ).json()["id"]
    share = api.post(
        f"/bugs/{bug['id']}/shares", username=admin,
        json={"channel_id": channel, "expires_in_days": 7, "allow_resolve": True},
    ).json()
    token = share["share_url"].split("#token=", 1)[1]

    def public_get():
        return api.client.get(
            f"/api/v1/public/defect-shares/{share['share_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert public_get().status_code == 200
    assert api.post(f"/bugs/{bug['id']}/archive", username=member_name, json={"reason": "x"}).status_code == 403
    assert api.post(f"/bugs/{bug['id']}/archive", username=admin, json={"reason": "  "}).status_code == 400
    archived = api.post(f"/bugs/{bug['id']}/archive", username=admin, json={"reason": "长期挂起，归档留存"})
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"]
    assert archived.json()["archive_reason"] == "长期挂起，归档留存"

    assert public_get().json()["message"] == "分享链接已撤销"
    assert api.get("/bugs", username=admin, params={"project_id": project_id}).json()["total"] == 0
    assert api.get("/bugs", username=admin, params={"project_id": project_id, "include_archived": True}).json()["total"] == 1
    assert _action(api, admin, bug["id"], "confirm").status_code == 409
    assert api.post(f"/bugs/{bug['id']}/archive", username=admin, json={"reason": "重复归档"}).status_code == 409

    assert api.post(f"/bugs/{bug['id']}/restore", username=member_name).status_code == 403
    restored = api.post(f"/bugs/{bug['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    assert api.get("/bugs", username=admin, params={"project_id": project_id}).json()["total"] == 1


def test_batch_actions_partial_failure_receipt(api, admin):
    """批量调优先级/归档/撤销归档返回逐项结果；不可操作项单独失败。"""
    project_id = _create_project(api, admin)
    a = _bug(api, admin, project_id, "批量甲")
    b = _bug(api, admin, project_id, "批量乙")
    api.post(f"/bugs/{b['id']}/archive", username=admin, json={"reason": "先归档"})

    r = api.post("/bugs/batch-actions", username=admin, json={
        "project_id": project_id, "ids": [a["id"], b["id"], 999999999], "action": "set_priority", "priority": 4,
    })
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert receipt["succeeded"] == 1
    assert receipt["failed"] == 2
    by_id = {item["id"]: item for item in receipt["items"]}
    assert by_id[a["id"]]["succeeded"] is True
    assert by_id[b["id"]]["succeeded"] is False
    assert "归档" in by_id[b["id"]]["error"]
    assert api.get(f"/bugs/{a['id']}", username=admin).json()["priority"] == 4

    # 归档缺原因整批 400；带原因批量归档 + 撤销归档
    assert api.post("/bugs/batch-actions", username=admin, json={
        "project_id": project_id, "ids": [a["id"]], "action": "archive",
    }).status_code == 400
    r = api.post("/bugs/batch-actions", username=admin, json={
        "project_id": project_id, "ids": [a["id"]], "action": "archive", "reason": "季度清理",
    })
    assert r.status_code == 200 and r.json()["succeeded"] == 1
    r = api.post("/bugs/batch-actions", username=admin, json={
        "project_id": project_id, "ids": [a["id"], b["id"]], "action": "restore",
    })
    assert r.status_code == 200 and r.json()["succeeded"] == 2
    assert api.get("/bugs", username=admin, params={"project_id": project_id}).json()["total"] == 2


# ---------------------------------------------------------------- 模板与开关

def test_template_draft_preview_publish_and_enforcement(api, admin):
    """模板草稿→预览→发布；旧版本退役；创建/确认必填与默认值生效。"""
    project_id = _create_project(api, admin)
    config = {
        "hidden_fields": ["api_request_headers"],
        "defaults": {"category": "接口", "environment": "test", "priority": 3},
        "required_on_create": ["steps_to_reproduce"],
        "required_on_confirm": ["expected_result"],
    }
    preview = api.post("/bugs/templates/preview", username=admin, json={"config": config})
    assert preview.status_code == 200, preview.text
    assert preview.json()["sample"]["category"] == "接口"
    assert "api_request_headers" not in preview.json()["sample"]
    assert "assignee_id" not in preview.json()["sample"]

    draft = api.post("/bugs/templates", username=admin, params={"project_id": project_id}, json={"config": config})
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"
    assert draft.json()["version"] == 1

    # 未发布不生效
    ok = api.post("/bugs", username=admin, json={"project_id": project_id, "title": "发布前"})
    assert ok.status_code == 201

    published = api.post(f"/bugs/templates/{draft.json()['id']}/publish", username=admin)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["published_at"]

    # 必填拦截 + 默认值应用
    missing = api.post("/bugs", username=admin, json={"project_id": project_id, "title": "缺步骤"})
    assert missing.status_code == 400
    assert "steps_to_reproduce" in missing.text
    created = api.post("/bugs", username=admin, json={
        "project_id": project_id, "title": "模板单", "steps_to_reproduce": "1. 打开页面",
    })
    assert created.status_code == 201, created.text
    assert created.json()["category"] == "接口"
    assert created.json()["environment"] == "test"
    assert created.json()["priority"] == 3

    # 确认阶段必填
    bug_id = created.json()["id"]
    assert _action(api, admin, bug_id, "confirm").status_code == 400
    r = _action(api, admin, bug_id, "confirm", expected_result="应正常返回")
    assert r.status_code == 200, r.text

    # 第二版发布后第一版退役
    draft2 = api.post("/bugs/templates", username=admin, params={"project_id": project_id}, json={"config": {}})
    assert draft2.json()["version"] == 2
    api.post(f"/bugs/templates/{draft2.json()['id']}/publish", username=admin)
    templates = api.get("/bugs/templates", username=admin, params={"project_id": project_id}).json()
    statuses = {item["version"]: item["status"] for item in templates}
    assert statuses[1] == "retired"
    assert statuses[2] == "published"


def test_template_validation_and_permissions(api, admin):
    """模板字段清单排除人员指派；隐藏与必填冲突拒绝；member 无管理权限。"""
    project_id = _create_project(api, admin)
    member_name = unique("member")
    member_id = _register(api, member_name)
    _add_member(api, admin, project_id, member_id, "member")

    assert api.post("/bugs/templates", username=admin, params={"project_id": project_id}, json={
        "config": {"hidden_fields": ["assignee_id"]},
    }).status_code == 400
    assert api.post("/bugs/templates", username=admin, params={"project_id": project_id}, json={
        "config": {"hidden_fields": ["environment"], "required_on_create": ["environment"]},
    }).status_code == 400
    assert api.post("/bugs/templates", username=admin, params={"project_id": project_id}, json={
        "config": {"defaults": {"severity": 9}},
    }).status_code == 400
    assert api.post("/bugs/templates", username=member_name, params={"project_id": project_id}, json={
        "config": {},
    }).status_code == 403


def test_project_setting_gray_switch_and_permissions(api, admin):
    """项目开关默认值、editor+ 修改、member 拒绝。"""
    project_id = _create_project(api, admin)
    member_name = unique("member")
    member_id = _register(api, member_name)
    _add_member(api, admin, project_id, member_id, "member")

    default = api.get("/bugs/project-setting", username=admin, params={"project_id": project_id}).json()
    assert default["queue_enabled"] is True
    assert default["reminder_enabled"] is False
    assert default["stale_reminder_days"] == 7

    assert api.put("/bugs/project-setting", username=member_name, params={"project_id": project_id}, json={
        "queue_enabled": False,
    }).status_code == 403
    updated = api.put("/bugs/project-setting", username=admin, params={"project_id": project_id}, json={
        "queue_enabled": False, "reminder_enabled": True, "stale_reminder_days": 3,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["queue_enabled"] is False
    assert updated.json()["reminder_enabled"] is True
    assert updated.json()["stale_reminder_days"] == 3


def test_stale_reminder_digest(api, admin, db):
    """订阅项目扫描滞留待确认/待验证缺陷并发送积压提醒。"""
    project_id = _create_project(api, admin)
    api.put("/bugs/project-setting", username=admin, params={"project_id": project_id}, json={
        "reminder_enabled": True, "stale_reminder_days": 3,
    })
    stale = _bug(api, admin, project_id, "滞留待确认")
    fresh = _bug(api, admin, project_id, "新缺陷")
    verify = _bug(api, admin, project_id, "滞留待验证")
    _action(api, admin, verify["id"], "confirm")
    _action(api, admin, verify["id"], "ready_for_regression", fix_version="b1")
    db.expire_all()
    cutoff = datetime.now() - timedelta(days=5)
    for bug_id in (stale["id"], verify["id"]):
        row = db.get(Bug, bug_id)
        row.updated_at = cutoff
    db.commit()

    sent = send_stale_reminders(db, now=datetime.now())
    db.commit()
    assert sent >= 1
    notes = db.query(Notification).filter_by(event_type="defect.reminder").all()
    assert notes
    detail = notes[0].payload["detail"]
    assert detail["project_id"] == project_id
    assert detail["pending_confirm"] >= 1
    assert detail["pending_verify"] >= 1
    assert fresh["id"]