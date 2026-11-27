"""缺陷模块加固回归：草稿隔离、并发编辑/动作、凭证脱敏与提醒去重。"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect

from app.core.database.session import SessionLocal
from app.core.models.identity import User
from app.core.models.notification import Notification
from app.features.defects.models.activity import BugActivity
from app.features.defects.models.bug import Bug
from app.features.defects.models.project_setting import DefectProjectSetting
from app.features.defects.models.reminder_dispatch import DefectReminderDispatch
from app.features.defects.models.share import DefectShareLink
from app.features.defects.schemas import BugActionRequest, BugUpdate
from app.features.defects.services import reminder_worker
from app.features.defects.services.defect_service import DefectService
from app.features.defects.services.reminder_worker import business_date_for, send_stale_reminders
from tests.conftest import unique

SERVICE = DefectService()
BEIJING = timezone(timedelta(hours=8))


def _create_project(api, actor):
    response = api.post("/projects", username=actor, json={"name": unique("hardening-proj"), "description": "hardening"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _register(api, username):
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username, "Init-Password-123")
    return response.json()["user"]["id"]


def _add_member(api, actor, project_id, user_id, role="member"):
    response = api.put(
        f"/projects/{project_id}/members/{user_id}", username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text


def _bug(api, actor, project_id, title="加固缺陷", **extra):
    body = {"project_id": project_id, "title": title}
    body.update(extra)
    response = api.post("/bugs", username=actor, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _user_id(db, username):
    db.expire_all()
    return db.query(User).filter(User.username == username).one().id


def _set_stale(db, bug_id, *, reference: datetime, days=5):
    """相对给定扫描时刻回拨缺陷更新时间，使其超过提醒阈值。"""
    db.expire_all()
    row = db.get(Bug, bug_id)
    row.updated_at = reference.replace(tzinfo=None) - timedelta(days=days)
    db.commit()


@pytest.fixture(autouse=True)
def _isolate_reminder_subscriptions(db):
    """提醒扫描覆盖全库项目；先关闭其他用例残留的订阅，避免跨文件计数污染。"""
    db.query(DefectProjectSetting).update(
        {DefectProjectSetting.reminder_enabled: False}, synchronize_session=False
    )
    db.commit()


# ---------------------------------------------------------------- 草稿隔离

def test_draft_is_creator_only_for_read_write_share_and_submit(api, admin):
    """同项目两个可写账号：B 读不到/改不了/分享不了 A 的草稿；A 提交后 B 可跟进。"""
    project_id = _create_project(api, admin)
    user_a = unique("draft-a")
    user_b = unique("draft-b")
    a_id = _register(api, user_a)
    b_id = _register(api, user_b)
    _add_member(api, admin, project_id, a_id, "member")
    _add_member(api, admin, project_id, b_id, "member")

    draft = _bug(api, user_a, project_id, "A 的草稿", is_draft=True)
    draft_id = draft["id"]
    assert draft["is_draft"] is True

    # 创建者可以读取和编辑自己的草稿。
    assert api.get(f"/bugs/{draft_id}", username=user_a).status_code == 200
    edited = api.put(
        f"/bugs/{draft_id}", username=user_a,
        json={"title": "A 的草稿（已修改）", "expected_version": draft["record_version"]},
    )
    assert edited.status_code == 200, edited.text

    # B 对所有按 ID 的入口都按不可见资源处理。
    denied = [
        api.get(f"/bugs/{draft_id}", username=user_b),
        api.get(f"/bugs/{draft_id}/attachments", username=user_b),
        api.get(f"/bugs/{draft_id}/activities", username=user_b),
        api.get(f"/bugs/{draft_id}/sources", username=user_b),
        api.get(f"/bugs/{draft_id}/shares", username=user_b),
        api.put(f"/bugs/{draft_id}", username=user_b, json={"title": "越权编辑"}),
        api.post(f"/bugs/{draft_id}/submit-draft", username=user_b),
        api.post(f"/bugs/{draft_id}/actions", username=user_b, json={"action": "confirm"}),
        api.post(f"/bugs/{draft_id}/archive", username=user_b, json={"reason": "越权归档"}),
        api.delete(f"/bugs/{draft_id}", username=user_b),
        api.post(f"/bugs/{draft_id}/shares", username=user_b, json={"channel_id": 1}),
        api.post("/bugs/shares/preview", username=user_b, json={"bug_ids": [draft_id], "channel_id": 1}),
        api.post("/bugs/shares/batch", username=user_b, json={"bug_ids": [draft_id], "channel_id": 1}),
    ]
    assert {response.status_code for response in denied} == {404}

    # 列表：包含草稿时也只放行自己的草稿。
    b_list = api.get("/bugs", username=user_b, params={"project_id": project_id, "include_drafts": "true"})
    assert b_list.status_code == 200
    assert draft_id not in {item["id"] for item in b_list.json()["items"]}
    a_list = api.get("/bugs", username=user_a, params={"project_id": project_id, "include_drafts": "true"})
    assert draft_id in {item["id"] for item in a_list.json()["items"]}
    b_drafts = api.get("/bugs", username=user_b, params={"project_id": project_id, "view": "drafts"})
    assert draft_id not in {item["id"] for item in b_drafts.json()["items"]}

    # 创建者也不能把未提交草稿公开分享。
    own_share = api.post(f"/bugs/{draft_id}/shares", username=user_a, json={"channel_id": 1})
    assert own_share.status_code == 400

    # 提交后进入项目队列，B 可以正常读取并执行无指派人动作。
    submitted = api.post(f"/bugs/{draft_id}/submit-draft", username=user_a)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["is_draft"] is False
    assert api.get(f"/bugs/{draft_id}", username=user_b).status_code == 200
    confirmed = api.post(f"/bugs/{draft_id}/actions", username=user_b, json={"action": "confirm"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["bug"]["status"] == "处理中"


# ---------------------------------------------------------------- 并发

def _admin_id(db, admin):
    return _user_id(db, admin)


def test_concurrent_edit_only_one_wins_and_activity_once(api, admin, db):
    """两个独立会话基于同一版本编辑：一成一 409，版本与活动各只增加一次。"""
    project_id = _create_project(api, admin)
    bug = _bug(api, admin, project_id, "并发编辑")
    bug_id = bug["id"]
    admin_id = _admin_id(db, admin)
    barrier = threading.Barrier(2)

    def attempt(title):
        with SessionLocal() as session:
            user = session.get(User, admin_id)
            row = session.get(Bug, bug_id)
            barrier.wait(timeout=10)
            try:
                result = SERVICE.update_bug(
                    session, row, BugUpdate(title=title, expected_version=0), actor=user,
                )
                return ("ok", result.title, result.record_version)
            except HTTPException as exc:
                session.rollback()
                return ("conflict", exc.status_code, exc.detail.get("meta"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["并发标题甲", "并发标题乙"]))

    successes = [item for item in outcomes if item[0] == "ok"]
    conflicts = [item for item in outcomes if item[0] == "conflict"]
    assert len(successes) == 1, outcomes
    assert len(conflicts) == 1, outcomes
    assert conflicts[0][1] == 409
    assert conflicts[0][2]["record_version"] == 1

    db.expire_all()
    final = db.get(Bug, bug_id)
    assert final.record_version == 1
    assert final.title == successes[0][1]
    assert db.query(BugActivity).filter_by(bug_id=bug_id, action="updated").count() == 1


def test_concurrent_regression_pass_and_fail_only_one_wins(api, admin, db):
    """同一待验证缺陷并发回归通过/失败：一成一 409，状态与活动保持单次一致。"""
    project_id = _create_project(api, admin)
    bug = _bug(api, admin, project_id, "并发回归")
    bug_id = bug["id"]
    assert api.post(f"/bugs/{bug_id}/actions", username=admin, json={"action": "confirm"}).status_code == 200
    assert api.post(
        f"/bugs/{bug_id}/actions", username=admin,
        json={"action": "ready_for_regression", "fix_version": "build-1"},
    ).status_code == 200
    admin_id = _admin_id(db, admin)
    barrier = threading.Barrier(2)

    def attempt(action, note):
        with SessionLocal() as session:
            user = session.get(User, admin_id)
            row = session.get(Bug, bug_id)
            barrier.wait(timeout=10)
            try:
                result, activity = SERVICE.perform_action(
                    session, row,
                    BugActionRequest(action=action, note=note, expected_version=2),
                    actor=user,
                )
                return ("ok", result.status, activity.note)
            except HTTPException as exc:
                session.rollback()
                return ("conflict", exc.status_code, exc.detail.get("meta"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda pair: attempt(*pair), [("regression_pass", "通过"), ("regression_fail", "仍复现")]))

    successes = [item for item in outcomes if item[0] == "ok"]
    conflicts = [item for item in outcomes if item[0] == "conflict"]
    assert len(successes) == 1, outcomes
    assert len(conflicts) == 1, outcomes
    assert conflicts[0][1] == 409
    assert conflicts[0][2]["record_version"] == 3

    db.expire_all()
    final = db.get(Bug, bug_id)
    actions = (
        db.query(BugActivity)
        .filter(BugActivity.bug_id == bug_id, BugActivity.action.in_(("regression_pass", "regression_fail")))
        .all()
    )
    assert final.record_version == 3
    assert len(actions) == 1
    assert actions[0].note == successes[0][2]
    assert final.status == successes[0][1]


# ---------------------------------------------------------------- 凭证脱敏

def _assert_no_secret(text: str, secrets: list[str]) -> None:
    for secret in secrets:
        assert secret not in text


def test_request_headers_are_masked_on_create_batch_edit_and_outputs(api, admin, db):
    """单条/批量/编辑写入与详情、活动、分享快照输出均不出现原始凭证。"""
    project_id = _create_project(api, admin)
    raw_headers = (
        "Authorization: Bearer fake-bearer-7c1d\n"
        "X-API-Key: fake-api-key-9a2b\n"
        "Cookie: session=fake-cookie-5e3f\n"
        "Content-Type: application/json\n"
        "X-Trace-Id: trace-123"
    )
    secrets = ["fake-bearer-7c1d", "fake-api-key-9a2b", "fake-cookie-5e3f"]
    bug = _bug(
        api, admin, project_id, "凭证脱敏单", category="接口",
        api_method="POST", api_url="/v1/login", api_request_headers=raw_headers,
    )
    assert bug["api_request_headers"] == (
        "Authorization: ******\n"
        "X-API-Key: ******\n"
        "Cookie: ******\n"
        "Content-Type: application/json\n"
        "X-Trace-Id: trace-123"
    )

    detail = api.get(f"/bugs/{bug['id']}", username=admin).json()
    _assert_no_secret(detail["api_request_headers"], secrets)
    assert "Content-Type: application/json" in detail["api_request_headers"]
    assert "X-Trace-Id: trace-123" in detail["api_request_headers"]

    db.expire_all()
    row = db.get(Bug, bug["id"])
    _assert_no_secret(row.api_request_headers or "", secrets)

    # 批量创建同样在落库前脱敏。
    batch = api.post("/bugs/batch", username=admin, json={
        "project_id": project_id,
        "items": [{
            "title": "批量凭证单", "category": "接口",
            "api_request_headers": '{"Authorization": "Bearer fake-batch-token", "X-API-Key": "fake-batch-key", "Accept": "application/json"}',
        }],
    })
    assert batch.status_code == 201, batch.text
    batch_headers = batch.json()["items"][0]["api_request_headers"]
    _assert_no_secret(batch_headers, ["fake-batch-token", "fake-batch-key"])
    assert "Accept" in batch_headers

    # 编辑也复用同一个脱敏入口。
    edited = api.put(f"/bugs/{bug['id']}", username=admin, json={
        "expected_version": bug["record_version"],
        "api_request_headers": "x-api-key: fake-edit-key-333\nContent-Length: 12",
    })
    assert edited.status_code == 200, edited.text
    assert "fake-edit-key-333" not in edited.json()["api_request_headers"]
    assert "Content-Length: 12" in edited.json()["api_request_headers"]

    # 历史活动记录在出口脱敏，普通文本保留。
    admin_id = _admin_id(db, admin)
    legacy = BugActivity(
        bug_id=bug["id"], project_id=project_id, actor_id=admin_id, action="updated",
        note="Authorization: Bearer legacy-bearer-111",
        detail={"api_request_headers": "X-API-Key: legacy-api-key-222\nAccept: application/json"},
    )
    db.add(legacy)
    db.commit()
    activities = api.get(f"/bugs/{bug['id']}/activities", username=admin).json()
    legacy_item = next(item for item in activities if item["id"] == legacy.id)
    _assert_no_secret(json.dumps(legacy_item, ensure_ascii=False), ["legacy-bearer-111", "legacy-api-key-222"])
    assert "Accept: application/json" in legacy_item["detail"]["api_request_headers"]

    # 历史分享快照在内部详情与公开页都再次脱敏。
    token = "fake-share-token-123456"
    share = DefectShareLink(
        share_id=unique("legacy-share")[:64], bug_id=bug["id"], project_id=project_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        visible_fields=["title", "api_request_headers"],
        content_snapshot={
            "title": "旧快照",
            "api_request_headers": "X-API-Key: legacy-share-key-444\nAccept: application/json",
        },
        pushed_by=admin_id,
    )
    db.add(share)
    db.commit()

    internal = api.get(f"/bugs/{bug['id']}/shares/{share.share_id}", username=admin)
    assert internal.status_code == 200, internal.text
    _assert_no_secret(json.dumps(internal.json(), ensure_ascii=False), ["legacy-share-key-444"])
    assert "Accept: application/json" in internal.json()["content_snapshot"]["api_request_headers"]

    public = api.client.get(
        f"/api/v1/public/defect-shares/{share.share_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert public.status_code == 200, public.text
    _assert_no_secret(json.dumps(public.json(), ensure_ascii=False), ["legacy-share-key-444"])


# ---------------------------------------------------------------- 提醒去重

def test_reminder_dedup_consecutive_concurrent_and_cross_day(api, admin, db):
    """同日连续/并发扫描每个收件人只提醒一次；跨业务日可再次提醒。"""
    project_id = _create_project(api, admin)
    member_name = unique("reminder-member")
    member_id = _register(api, member_name)
    _add_member(api, admin, project_id, member_id, "member")
    api.put("/bugs/project-setting", username=admin, params={"project_id": project_id}, json={
        "reminder_enabled": True, "stale_reminder_days": 3,
    })
    stale = _bug(api, admin, project_id, "长期待确认")
    day1 = datetime(2026, 11, 26, 9, 30, tzinfo=BEIJING)
    day2 = day1 + timedelta(days=1)
    _set_stale(db, stale["id"], reference=day1, days=5)
    admin_id = _admin_id(db, admin)
    recipients = {admin_id, member_id}

    barrier = threading.Barrier(2)

    def scan(moment):
        with SessionLocal() as session:
            barrier.wait(timeout=10)
            sent = send_stale_reminders(session, now=moment)
            session.commit()
            return sent

    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(scan, [day1, day1]))
    assert sum(concurrent) == 1, concurrent

    def counts():
        db.expire_all()
        rows = db.query(Notification).filter_by(project_id=project_id, event_type="defect.reminder").all()
        return {recipient: sum(1 for row in rows if row.user_id == recipient) for recipient in recipients}

    assert counts() == {admin_id: 1, member_id: 1}
    assert send_stale_reminders(db, now=day1 + timedelta(hours=2)) == 0
    db.commit()
    assert counts() == {admin_id: 1, member_id: 1}

    assert send_stale_reminders(db, now=day2) == 1
    db.commit()
    assert counts() == {admin_id: 2, member_id: 2}

    db.expire_all()
    dispatch = db.query(DefectReminderDispatch).filter_by(project_id=project_id).all()
    assert len(dispatch) == 4
    assert {row.business_date.isoformat() for row in dispatch} == {"2026-11-26", "2026-11-27"}
    # 北京时间切日：UTC 23:30 已属于次日业务日。
    assert business_date_for(datetime(2026, 11, 26, 23, 30, tzinfo=timezone.utc)).isoformat() == "2026-11-27"


def test_reminder_failure_rolls_back_dedup_and_retries(api, admin, db, monkeypatch):
    """通知写入失败时去重记录一并回滚，下一次扫描可以重新发送。"""
    project_id = _create_project(api, admin)
    api.put("/bugs/project-setting", username=admin, params={"project_id": project_id}, json={
        "reminder_enabled": True, "stale_reminder_days": 3,
    })
    stale = _bug(api, admin, project_id, "失败重试")
    moment = datetime(2026, 11, 26, 10, 0, tzinfo=BEIJING)
    _set_stale(db, stale["id"], reference=moment, days=5)
    real_notify = reminder_worker.notify
    calls = {"count": 0}

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated notification failure")
        return real_notify(*args, **kwargs)

    monkeypatch.setattr(reminder_worker, "notify", flaky)
    with pytest.raises(RuntimeError):
        send_stale_reminders(db, now=moment)
    db.rollback()
    assert db.query(DefectReminderDispatch).filter_by(project_id=project_id).count() == 0
    assert db.query(Notification).filter_by(project_id=project_id, event_type="defect.reminder").count() == 0

    assert send_stale_reminders(db, now=moment) == 1
    db.commit()
    assert db.query(Notification).filter_by(project_id=project_id, event_type="defect.reminder").count() == 1
    assert db.query(DefectReminderDispatch).filter_by(project_id=project_id).count() == 1


def test_reminder_dispatch_migration_schema(db):
    """迁移后存在去重表与「项目+收件人+类型+业务日」唯一索引。"""
    inspector = inspect(db.get_bind())
    assert "defect_reminder_dispatch" in inspector.get_table_names()
    indexes = {item["name"]: item for item in inspector.get_indexes("defect_reminder_dispatch")}
    unique = indexes["uq_defect_reminder_dispatch_day"]
    assert unique["unique"] is True
    assert unique["column_names"] == ["project_id", "recipient_id", "reminder_type", "business_date"]