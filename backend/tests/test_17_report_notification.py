"""验收项 17：测试报告 + 飞书通知（Phase 2）。

覆盖需求红线：
- 报告统计全部由代码计算（total/passed/failed/error/skipped/pass_rate/duration_ms），
  AI 只做总结 / 风险解释 / 失败聚类，不参与统计（§五/§六/§三十）；
- 幂等：同一 test_run_id 已有 COMPLETED 报告时返回已有；regenerate 仅重生成 AI 总结；
- AI 总结失败不影响报告 COMPLETED（§九）；
- 报告删除只删报告记录，不删 TestRun / CaseExecution（§二十六）；
- 报告访问走登录 + 项目权限，越权统一 404（§二十六）；
- Webhook URL / Secret 只写不读：响应只有 webhook_configured + 脱敏 webhook_masked，
  绝不进入 Agent brief / 报告 / 通知记录（§十五/§二十一/§三十一）；
- 飞书发送失败只记 NotificationRecord(FAILED)，不改 TestRun / Report 状态（§二十八）；
- 通知条件 ALWAYS / ONLY_FAILED / ONLY_HIGH_RISK（§十七）；
- POTENTIAL_BUG 只表示「疑似产品问题，需人工确认」，不写「已发现 Bug」（§十八）。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from tests.conftest import unique

from app.features.notifications.models.channel import NotificationChannel
from app.features.notifications.models.notification_record import NotificationRecord
from app.features.notifications.services import FeishuNotificationService
from app.features.reports.models.report import TestReport
from app.features.reports.services import ReportService
from app.features.reports.services.ai_summary import generate_summary
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.models.identity import User

API = "/api/v1"

_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/deadbeef-0000-1111-2222-333344445555"
_SECRET = "test-Feishu-Signing-Secret-42"


# --------------------------------------------------------------------------- 辅助函数


def _register_and_login(api, username) -> int:
    r = api.register(username)
    assert r.status_code == 201, r.text
    api.login(username, "Init-Password-123")
    return r.json()["user"]["id"]


def _create_project(api, actor) -> int:
    r = api.post("/projects", username=actor, json={"name": unique("report-proj")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_member(api, actor, project_id, user_id, role="member"):
    r = api.put(
        f"/projects/{project_id}/members/{user_id}", username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert r.status_code == 200, r.text


def _user_obj(db, username) -> User:
    user = db.query(User).filter(User.username == username).first()
    assert user is not None, username
    return user


def _make_case(db, project_id, *, priority="P1", case_type="FUNCTIONAL"):
    case = TestCase(
        project_id=project_id, name=unique("case"), priority=priority,
        case_type=case_type, target_type="API", enabled=True, revision=1,
        source_type="MANUAL",
    )
    db.add(case)
    db.flush()
    return case


def _make_run(db, project_id, specs) -> TestRun:
    """直接落库一次执行记录 + 逐用例执行，避免依赖真实 HTTP 打桩。

    Args:
        specs: [{"status": "PASSED", "duration_ms": 100, "error_code": ...,
                 "error_message": ..., "assertion_results": [...], "case": TestCase}]
    """
    run = TestRun(
        project_id=project_id,
        status="SUCCESS" if not any(s["status"] in ("FAILED", "ERROR") for s in specs) else "FAILED",
        total=len(specs),
        passed=sum(1 for s in specs if s["status"] == "PASSED"),
        failed=sum(1 for s in specs if s["status"] == "FAILED"),
        error=sum(1 for s in specs if s["status"] == "ERROR"),
        skipped=sum(1 for s in specs if s["status"] == "SKIPPED"),
        started_at=datetime.now(),
        finished_at=datetime.now(),
    )
    db.add(run)
    db.flush()
    for spec in specs:
        db.add(
            CaseExecution(
                test_run_id=run.id,
                test_case_id=spec["case"].id if spec.get("case") else None,
                status=spec["status"],
                executor_type="API",
                duration_ms=spec.get("duration_ms"),
                error_code=spec.get("error_code"),
                error_message=spec.get("error_message"),
                assertion_results=spec.get("assertion_results"),
                started_at=datetime.now(),
                finished_at=datetime.now(),
            )
        )
    db.commit()
    db.refresh(run)
    return run


class _FailingProvider:
    """始终抛错的 LLM Provider：用于验证 AI 总结失败不影响报告状态。"""

    def generate_structured(self, *args, **kwargs):
        raise RuntimeError("模拟 LLM 不可用")


class _EchoingProvider:
    """原样回显给定 dict 的 LLM Provider：用于验证入库前的值形态脱敏（§三十一）。"""

    def __init__(self, raw: dict) -> None:
        self.raw = raw

    def generate_structured(self, *args, **kwargs):
        return self.raw


@pytest.fixture()
def owner(db, api, admin):
    """项目创建者（owner，member+ 权限）。"""
    pid = _create_project(api, admin)
    return pid, _user_obj(db, admin)


# --------------------------------------------------------------------------- 报告统计


class TestReportStats:
    """统计字段全部由代码计算，AI 不参与。"""

    def test_stats_computed_by_code(self, db, owner):
        pid, actor = owner
        run = _make_run(
            db, pid,
            [
                {"status": "PASSED", "duration_ms": 100},
                {"status": "PASSED", "duration_ms": 200},
                {"status": "FAILED", "duration_ms": 300,
                 "assertion_results": [{"path": "$.code", "passed": False, "expected": 0, "actual": 500}]},
                {"status": "ERROR", "duration_ms": 50, "error_code": "TIMEOUT",
                 "error_message": "connection timeout"},
                {"status": "SKIPPED", "duration_ms": 0},
            ],
        )
        res = ReportService().build_report(
            db, run.id, actor=actor, generate_ai_summary=False,
        )
        assert res.status == "COMPLETED"
        report = db.get(TestReport, res.report_id)
        # 通过率 = passed / (total - skipped) * 100 = 2/4 = 50.0
        assert (report.total_cases, report.passed_cases, report.failed_cases,
                report.error_cases, report.skipped_cases) == (5, 2, 1, 1, 1)
        assert float(report.pass_rate) == 50.0
        # 总耗时 = 逐用例 duration_ms 求和（SKIPPED 也计入 0）
        assert report.duration_ms == 650
        # 报告编号可稳定解析
        assert report.report_no.startswith("RPT-") and report.report_no.count("-") == 2

    def test_pass_rate_zero_when_only_skipped(self, db, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "SKIPPED"}, {"status": "SKIPPED"}])
        res = ReportService().build_report(db, run.id, actor=actor, generate_ai_summary=False)
        report = db.get(TestReport, res.report_id)
        assert float(report.pass_rate) == 0.0
        assert report.status == "COMPLETED"
        assert report.risk_level == "LOW"

    def test_ai_failure_does_not_fail_report(self, db, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 10},
                                  {"status": "FAILED", "duration_ms": 20}])
        res = ReportService().build_report(
            db, run.id, actor=actor, generate_ai_summary=True,
            provider=_FailingProvider(),
        )
        report = db.get(TestReport, res.report_id)
        # AI 总结失败：报告仍 COMPLETED，ai_summary 为空，风险等级仍由代码规则给出。
        assert report.status == "COMPLETED"
        assert report.ai_summary is None
        assert report.ai_summary_version is None
        assert report.risk_level == "MEDIUM"

    def test_risk_level_rules(self, db, owner):
        pid, actor = owner
        # P0 + PERMISSION 失败 → CRITICAL
        csec = _make_case(db, pid, priority="P0", case_type="PERMISSION")
        run = _make_run(db, pid, [{"status": "FAILED", "duration_ms": 10, "case": csec}])
        r = db.get(TestReport, ReportService().build_report(
            db, run.id, actor=actor, generate_ai_summary=False,
        ).report_id)
        assert r.risk_level == "CRITICAL"

        # P0 普通失败 → HIGH
        cp0 = _make_case(db, pid, priority="P0", case_type="FUNCTIONAL")
        run2 = _make_run(db, pid, [{"status": "FAILED", "duration_ms": 10, "case": cp0}])
        r2 = db.get(TestReport, ReportService().build_report(
            db, run2.id, actor=actor, generate_ai_summary=False,
        ).report_id)
        assert r2.risk_level == "HIGH"

    def test_failure_classification(self, db, owner):
        pid, actor = owner
        cperm = _make_case(db, pid, priority="P0", case_type="PERMISSION")
        run = _make_run(db, pid, [
            {"status": "FAILED", "duration_ms": 1, "case": cperm},                    # POTENTIAL_BUG
            {"status": "FAILED", "duration_ms": 1,
             "assertion_results": [{"path": "$.code", "passed": False}]},              # ASSERTION_FAILURE
            {"status": "ERROR", "duration_ms": 1, "error_message": "unexpected null"}, # EXECUTION_ERROR
            {"status": "ERROR", "duration_ms": 1, "error_message": "connection refused"},  # ENVIRONMENT_ERROR
            {"status": "FAILED", "duration_ms": 1, "error_message": "fixture data missing"},  # TEST_DATA_ISSUE
        ])
        detail = ReportService().get_report(db, ReportService().build_report(
            db, run.id, actor=actor, generate_ai_summary=False,
        ).report_id, actor)
        types = sorted(item["failure_type"] for item in detail.failure_clusters)
        assert types == ["ASSERTION_FAILURE", "ENVIRONMENT_ERROR", "EXECUTION_ERROR",
                         "POTENTIAL_BUG", "TEST_DATA_ISSUE"]

    def test_idempotent_and_regenerate(self, db, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 10}])
        svc = ReportService()
        first = svc.build_report(db, run.id, actor=actor, generate_ai_summary=False)
        second = svc.build_report(db, run.id, actor=actor, generate_ai_summary=False)
        # 幂等：不新建第二份报告。
        assert first.report_id == second.report_id
        assert db.query(TestReport).filter(TestReport.test_run_id == run.id).count() == 1
        # regenerate 走已有报告，统计字段不变。
        before = (first.report_id, db.get(TestReport, first.report_id).pass_rate)
        third = svc.build_report(db, run.id, actor=actor, regenerate=True, generate_ai_summary=False)
        assert third.report_id == before[0]
        assert float(db.get(TestReport, third.report_id).pass_rate) == float(before[1])

    def test_stats_immutable_after_regeneration(self, db, owner):
        """§三十：报告统计不可变——重新生成 AI 总结不改变任何统计字段。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 10},
                                  {"status": "FAILED", "duration_ms": 20}])
        svc = ReportService()
        rid = svc.build_report(db, run.id, actor=actor, generate_ai_summary=False).report_id
        snapshot = (db.get(TestReport, rid).total_cases, db.get(TestReport, rid).passed_cases,
                    db.get(TestReport, rid).failed_cases, db.get(TestReport, rid).pass_rate,
                    db.get(TestReport, rid).duration_ms, db.get(TestReport, rid).risk_level)
        svc.regenerate_ai_summary(db, rid, actor, provider=_FailingProvider())
        report = db.get(TestReport, rid)
        assert (report.total_cases, report.passed_cases, report.failed_cases,
                float(report.pass_rate), report.duration_ms, report.risk_level) == snapshot


# --------------------------------------------------------------------------- 报告接口


class TestReportAPI:
    def test_generate_list_detail_and_delete(self, db, api, admin, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 5},
                                  {"status": "FAILED", "duration_ms": 5}])
        r = api.post(f"/test-runs/{run.id}/report", username=admin,
                     json={"generate_ai_summary": False})
        assert r.status_code == 200, r.text
        rid = r.json()["report_id"]

        listed = api.get(f"/projects/{pid}/reports", username=admin).json()
        assert listed["total"] >= 1
        assert any(item["id"] == rid for item in listed["items"])

        detail = api.get(f"/reports/{rid}", username=admin).json()
        assert detail["report"]["id"] == rid
        assert len(detail["case_executions"]) == 2
        assert detail["test_run"] is not None and detail["test_run"]["id"] == run.id

        assert api.delete(f"/reports/{rid}", username=admin).status_code == 204
        assert api.get(f"/reports/{rid}", username=admin).status_code == 404
        # 删除报告不影响执行记录与逐用例执行。
        assert db.get(TestRun, run.id) is not None
        assert db.query(CaseExecution).filter(CaseExecution.test_run_id == run.id).count() == 2

    def test_delete_keeps_case_execution_after_hard_check(self, db, api, admin, owner):
        """§二十六：只删报告记录，不删 TestRun / CaseExecution。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        assert api.delete(f"/reports/{rid}", username=admin).status_code == 204
        assert db.get(TestReport, rid) is None
        assert db.get(TestRun, run.id) is not None
        ce = db.query(CaseExecution).filter(CaseExecution.test_run_id == run.id).first()
        assert ce is not None

    def test_unauthenticated_and_cross_project(self, db, api, admin, owner):
        """未登录 401；已登录但无项目权限统一 404（隐藏存在性）。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        assert api.get(f"/reports/{rid}").status_code == 401
        outsider = unique("report-outside")
        _register_and_login(api, outsider)
        assert api.get(f"/reports/{rid}", username=outsider).status_code == 404
        assert api.delete(f"/reports/{rid}", username=outsider).status_code == 404

    def test_cross_project_member_gets_404(self, db, api, admin, owner):
        """报告访问必须走登录 + 项目权限；viewer 可读、不可删（member+）。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        # viewer：可读，不可删。
        viewer_name = unique("report-viewer")
        _register_and_login(api, viewer_name)
        _add_member(api, admin, pid, _user_obj(db, viewer_name).id, role="viewer")
        assert api.get(f"/reports/{rid}", username=viewer_name).status_code == 200
        assert api.delete(f"/reports/{rid}", username=viewer_name).status_code == 403
        # 非成员访问别的项目列表也不泄漏该报告。
        outsider = unique("report-outside")
        _register_and_login(api, outsider)
        other = _create_project(api, outsider)
        listed = api.get(f"/projects/{other}/reports", username=outsider).json()
        assert all(item["id"] != rid for item in listed["items"])

    def test_list_filters(self, db, api, admin, owner):
        pid, actor = owner
        svc = ReportService()
        for i in range(3):
            run = _make_run(
                db, pid,
                [{"status": "PASSED", "duration_ms": 1}] * i
                + [{"status": "FAILED", "duration_ms": 1, "error_message": "boom"}],
            )
            svc.build_report(db, run.id, actor=actor, generate_ai_summary=False)
        all_items = api.get(f"/projects/{pid}/reports", username=admin).json()["items"]
        assert len(all_items) >= 3
        risky = api.get(f"/projects/{pid}/reports", username=admin,
                        params={"risk_level": "MEDIUM"}).json()["items"]
        assert all(item["risk_level"] == "MEDIUM" for item in risky)
        completed = api.get(f"/projects/{pid}/reports", username=admin,
                            params={"status": "COMPLETED"}).json()["items"]
        assert all(item["status"] == "COMPLETED" for item in completed)


# --------------------------------------------------------------------------- 通知渠道


class TestNotificationChannel:
    def test_create_masked_and_never_leaks_secret(self, db, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK, "secret": _SECRET,
                  "notify_condition": "ALWAYS", "enabled": True},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        blob = str(body)
        assert body["webhook_configured"] is True
        assert body["webhook_masked"].startswith("https://open.feishu.cn/")
        assert "****" in body["webhook_masked"]
        # 响应里绝不能出现明文 URL 路径或签名密钥。
        assert _WEBHOOK.split("/hook/")[-1] not in blob
        assert _SECRET not in blob
        # 明文也绝不能落库。
        db.expire_all()
        row = db.get(NotificationChannel, body["id"])
        stored = str(row.config_json)
        assert _WEBHOOK not in stored and _SECRET not in stored
        assert "webhook_url_encrypted" in row.config_json
        assert row.config_json["webhook_url_encrypted"] != _WEBHOOK

    def test_update_without_secret_keeps_old_value(self, db, api, admin):
        pid = _create_project(api, admin)
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK, "secret": _SECRET},
        ).json()["id"]
        db.expire_all()
        old_enc = db.get(NotificationChannel, cid).config_json["secret_encrypted"]
        r = api.patch(f"/notification-channels/{cid}", username=admin, json={"name": "改名"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "改名"
        db.expire_all()
        assert db.get(NotificationChannel, cid).config_json["secret_encrypted"] == old_enc

    def test_update_empty_webhook_is_rejected_not_wiped(self, db, api, admin):
        """空串 webhook 必须被拒绝，而不是静默覆盖。

        前端表单把未填写的字段序列化成 ""，一旦 PATCH 把它当作「清空」，
        改个名字就会抹掉已保存的凭据、却仍返回 200 与 webhook_configured=true，
        之后每次通知都失败。这里把它钉成显式 400。
        """
        pid = _create_project(api, admin)
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK, "secret": _SECRET},
        ).json()["id"]
        old_enc = db.get(NotificationChannel, cid).config_json["webhook_url_encrypted"]

        for payload in ({"webhook_url": ""}, {"webhook_url": "ftp://not-http"},
                        {"name": "改名", "webhook_url": ""}):
            r = api.patch(f"/notification-channels/{cid}", username=admin, json=payload)
            assert r.status_code == 400, (payload, r.text)
        db.expire_all()
        ch = db.get(NotificationChannel, cid)
        assert ch.config_json["webhook_url_encrypted"] == old_enc
        assert api.get(f"/notification-channels/{cid}", username=admin).json()["webhook_configured"] is True

        # secret 允许用空串显式清除（与 webhook 语义不同），清除后仍可发送失败而非崩溃。
        r = api.patch(f"/notification-channels/{cid}", username=admin, json={"secret": ""})
        assert r.status_code == 200, r.text
        db.expire_all()
        assert db.get(NotificationChannel, cid).config_json["secret_encrypted"] == ""

    def test_masked_url_drops_userinfo(self, db, api, admin):
        """脱敏地址不能把 URL userinfo（user:pass@）回显给前端。"""
        pid = _create_project(api, admin)
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"),
                  "webhook_url": "https://user:pass@open.feishu.cn/open-apis/bot/v2/hook/deadbeef-0000"},
        ).json()["id"]
        body = api.get(f"/notification-channels/{cid}", username=admin).json()
        assert body["webhook_masked"] == "https://open.feishu.cn/...****"
        assert "user" not in body["webhook_masked"] and "pass@" not in body["webhook_masked"]

    def test_list_and_get_and_delete(self, api, admin):
        pid = _create_project(api, admin)
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK},
        ).json()["id"]
        listed = api.get(f"/projects/{pid}/notification-channels", username=admin).json()
        assert any(c["id"] == cid for c in listed["items"])
        assert api.get(f"/notification-channels/{cid}", username=admin).json()["id"] == cid
        assert api.delete(f"/notification-channels/{cid}", username=admin).status_code == 204
        assert api.get(f"/notification-channels/{cid}", username=admin).status_code == 404

    def test_delete_removes_records_but_not_report(self, db, api, admin, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": "http://127.0.0.1:9/dead-hook"},
        ).json()["id"]
        assert api.post(f"/reports/{rid}/notify", username=admin, json={"channel_id": cid}).status_code == 200
        assert db.query(NotificationRecord).filter(NotificationRecord.channel_id == cid).count() == 1
        assert api.delete(f"/notification-channels/{cid}", username=admin).status_code == 204
        assert db.query(NotificationRecord).filter(NotificationRecord.channel_id == cid).count() == 0
        assert db.get(TestReport, rid) is not None

    def test_cross_project_channel_is_404(self, api, admin):
        pid = _create_project(api, admin)
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK},
        ).json()["id"]
        name = unique("channel-outsider")
        _register_and_login(api, name)
        assert api.get(f"/notification-channels/{cid}", username=name).status_code == 404
        assert api.post(f"/projects/999999/notification-channels", username=name,
                        json={"name": "x", "webhook_url": _WEBHOOK}).status_code == 404

    def test_viewer_cannot_create_or_send(self, db, api, admin):
        pid = _create_project(api, admin)
        name = unique("channel-viewer")
        viewer = _register_and_login(api, name)
        _add_member(api, admin, pid, viewer, role="viewer")
        # 读可以
        assert api.get(f"/projects/{pid}/notification-channels", username=name).status_code == 200
        # 写（含触发外发）不可以
        assert api.post(f"/projects/{pid}/notification-channels", username=name,
                        json={"name": "x", "webhook_url": _WEBHOOK}).status_code == 403

        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK},
        ).json()["id"]
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]

        # 读侧仍然放开（viewer+）：渠道详情 / 发送记录 / 报告详情与记录。
        assert api.get(f"/notification-channels/{cid}", username=name).status_code == 200
        assert api.get(f"/notification-channels/{cid}/records", username=name).status_code == 200
        assert api.get(f"/reports/{rid}", username=name).status_code == 200
        assert api.get(f"/reports/{rid}/notifications", username=name).status_code == 200

        # 所有「写」与「触发外发」都必须拒绝（member+）——不只覆盖创建渠道这一条。
        assert api.patch(f"/notification-channels/{cid}", username=name,
                         json={"name": "改名"}).status_code == 403
        assert api.delete(f"/notification-channels/{cid}", username=name).status_code == 403
        assert api.post(f"/notification-channels/{cid}/test", username=name).status_code == 403
        assert api.post(f"/reports/{rid}/notify", username=name,
                        json={"channel_id": cid}).status_code == 403
        assert api.post(f"/reports/{rid}/regenerate-ai-summary", username=name).status_code == 403


# --------------------------------------------------------------------------- 飞书发送


class TestFeishuSend:
    def test_send_failure_records_failed_without_touching_report_or_run(self, db, api, admin, owner):
        """§二十八：通知失败独立记录，三个状态互不牵连。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            # 指向本机被拒端口：确定性网络异常 → 记 FAILED，不外抛，也不依赖外网。
            json={"name": unique("channel"), "webhook_url": "http://127.0.0.1:9/dead-hook"},
        ).json()["id"]
        r = api.post(f"/reports/{rid}/notify", username=admin, json={"channel_id": cid})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "FAILED"
        assert body["record_id"] is not None
        # 报告与执行记录状态不变。
        assert db.get(TestReport, rid).status == "COMPLETED"
        assert db.get(TestRun, run.id).status == "SUCCESS"
        # 通知记录的 request_snapshot 存的是卡片内容，绝不包含本渠道的 webhook URL。
        # 注意断言的是**本测试实际使用**的地址片段（127.0.0.1 / dead-hook），
        # 而不是 _WEBHOOK / _SECRET——那两个常量本测试从未配置，断言它们等价于无断言。
        rec = db.get(NotificationRecord, body["record_id"])
        blob = str(rec.request_snapshot) + str(rec.response_snapshot) + str(rec.error_message)
        assert "dead-hook" not in blob
        assert "127.0.0.1" not in blob

    def test_record_list_by_report(self, db, api, admin, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": "http://127.0.0.1:9/dead-hook"},
        ).json()["id"]
        api.post(f"/reports/{rid}/notify", username=admin, json={"channel_id": cid})
        api.post(f"/reports/{rid}/notify", username=admin, json={"channel_id": cid})
        records = api.get(f"/reports/{rid}/notifications", username=admin).json()
        assert records["total"] == 2
        by_channel = api.get(f"/notification-channels/{cid}/records", username=admin).json()
        assert by_channel["total"] == 2

    def test_notify_conditions(self, db, owner):
        """§十七：ALWAYS / ONLY_FAILED / ONLY_HIGH_RISK 判定，未知条件宽松处理。"""
        pid, _actor = owner
        feishu = FeishuNotificationService()

        def _report(risk, failed=0, error=0, total=3):
            rep = TestReport(project_id=pid, report_no=unique("rpt"), title="t", status="COMPLETED",
                             total_cases=total, passed_cases=total - failed - error,
                             failed_cases=failed, error_cases=error, skipped_cases=0,
                             pass_rate=50.0, risk_level=risk)
            db.add(rep)
            db.flush()
            return rep

        all_pass = _report("LOW")
        assert feishu._should_send("ALWAYS", all_pass) is True
        assert feishu._should_send("ONLY_FAILED", all_pass) is False
        assert feishu._should_send("ONLY_FAILED", _report("MEDIUM", failed=1)) is True
        assert feishu._should_send("ONLY_FAILED", _report("MEDIUM", error=1)) is True
        assert feishu._should_send("ONLY_HIGH_RISK", all_pass) is False
        assert feishu._should_send("ONLY_HIGH_RISK", _report("HIGH")) is True
        assert feishu._should_send("ONLY_HIGH_RISK", _report("CRITICAL")) is True
        # 未知条件按 ALWAYS 宽松处理，避免漏报。
        assert feishu._should_send("SOMETHING_ELSE", all_pass) is True

    def test_disabled_channel_is_skipped(self, db, api, admin, owner):
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        cid = api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK, "enabled": False},
        ).json()["id"]
        body = api.post(f"/reports/{rid}/notify", username=admin, json={"channel_id": cid}).json()
        assert body["skipped"] is True
        assert body["record_id"] is None
        assert db.get(TestReport, rid).status == "COMPLETED"

    def test_no_channel_skips_silently(self, db, api, admin, owner):
        """无启用渠道时跳过而不是失败（安全默认）。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        body = api.post(f"/reports/{rid}/notify", username=admin, json={}).json()
        assert body["skipped"] is True and body["record_id"] is None
        # 按报告过滤：会话内其它测试会留下自己的发送记录，不能统计全表。
        assert db.query(NotificationRecord).filter(
            NotificationRecord.report_id == rid,
        ).count() == 0


# --------------------------------------------------------------------------- 密钥与 Agent brief


class TestSecretBoundary:
    def test_report_brief_never_contains_webhook_or_secret(self, db, api, admin, owner):
        """§十五/§三十一：Webhook URL / Secret 不能进入 Agent Prompt 与 Report。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK, "secret": _SECRET},
        )
        from app.features.agent.tools.report_tool import get_report_brief

        brief = get_report_brief(db, rid, actor)
        blob = str(brief)
        assert _WEBHOOK not in blob and _SECRET not in blob
        assert "secret" not in blob.lower() and "webhook" not in blob.lower()
        # brief 只带脱敏统计与摘要字段，供 Agent 查看。
        assert "report_no" in brief and "pass_rate" in brief and "totals" in brief

    def test_report_body_never_contains_webhook_or_secret(self, db, api, admin, owner):
        """报告本体不含渠道配置。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        api.post(
            f"/projects/{pid}/notification-channels", username=admin,
            json={"name": unique("channel"), "webhook_url": _WEBHOOK, "secret": _SECRET},
        )
        detail = api.get(f"/reports/{rid}", username=admin).json()
        blob = str(detail)
        assert _WEBHOOK not in blob and _SECRET not in blob

    def test_execution_free_text_never_leaks_webhook_into_report_or_prompt(self, db, api, admin, owner):
        """§十五/§三十一：webhook / 签名密钥出现在用例执行的**自由文本**里时，
        报告详情与 LLM 入参 payload 都必须脱敏。

        这是本平台的常态场景：SECURITY 类用例的断言就是「响应体不得包含 webhook」，
        断言消息与 error_message 会回显被抓到的原文。字段名脱敏拦不住它——
        字段名是 error_message / message，不在敏感键集合里——所以必须按「值的形态」识别。
        """
        pid, actor = owner
        case = _make_case(db, pid, priority="P0", case_type="SECURITY")
        run = _make_run(db, pid, [{
            "status": "FAILED", "duration_ms": 1, "case": case,
            "error_message": f"响应体意外包含 webhook {_WEBHOOK}（secret {_SECRET}）",
            "assertion_results": [
                {"assertion_type": "not_contains", "path": "$.webhook", "passed": False,
                 "expected": "不含 webhook", "actual": "含 webhook",
                 "message": f"响应体包含明文 webhook {_WEBHOOK} 与 secret {_SECRET}"},
            ],
        }])
        rid = api.post(f"/test-runs/{run.id}/report", username=admin,
                       json={"generate_ai_summary": False}).json()["report_id"]
        hook_id = _WEBHOOK.split("/hook/")[-1]

        # 1) 报告详情接口不得回显原文（§三十一：不能进入前端普通接口响应）。
        blob = json.dumps(api.get(f"/reports/{rid}", username=admin).json(), ensure_ascii=False)
        assert _WEBHOOK not in blob and hook_id not in blob and _SECRET not in blob

        # 2) 送给 LLM 的 payload 同样不得含原文，否则凭证会进 Prompt 与 AI 总结（§34）。
        svc = ReportService()
        rows = [(ce, db.get(TestCase, ce.test_case_id))
                for ce in db.query(CaseExecution).filter_by(test_run_id=run.id).all()]
        payload_blob = json.dumps(
            svc._build_ai_payload(db.get(TestReport, rid), rows), ensure_ascii=False,
        )
        assert _WEBHOOK not in payload_blob and hook_id not in payload_blob
        assert _SECRET not in payload_blob

    def test_llm_echoed_webhook_is_scrubbed_before_persist(self, db, owner):
        """LLM 把凭证回显进 AI 总结时，入库前必须按值形态掩掉（否则它会经
        GET /reports 与飞书卡片二次扩散）。"""
        pid, actor = owner
        run = _make_run(db, pid, [{"status": "PASSED", "duration_ms": 1}])
        svc = ReportService()
        rid = svc.build_report(db, run.id, actor=actor, generate_ai_summary=False).report_id

        report = db.get(TestReport, rid)
        rows = [(ce, db.get(TestCase, ce.test_case_id))
                for ce in db.query(CaseExecution).filter_by(test_run_id=run.id).all()]
        payload = svc._build_ai_payload(report, rows)
        echoed = {
            "overview": f"失败用例的回显包含 webhook {_WEBHOOK}，建议排查 secret {_SECRET}",
            "key_findings": [f"断言消息中出现 {_WEBHOOK}"],
            "recommendations": ["检查接口返回体"],
            "risk_summary": "无高风险",
        }
        hook_id = _WEBHOOK.split("/hook/")[-1]
        summary_blob = json.dumps(generate_summary(_EchoingProvider(echoed), payload),
                                  ensure_ascii=False)
        assert _WEBHOOK not in summary_blob and hook_id not in summary_blob
        assert _SECRET not in summary_blob
        # 正文仍可正常阅读，只是凭证被替换。
        assert "建议排查" in summary_blob and "检查接口返回体" in summary_blob

    def test_potential_bug_wording_is_soft(self, db, owner):
        """§十八：POTENTIAL_BUG 只表示疑似产品问题，不写「已发现 Bug」。"""
        pid, actor = owner
        cperm = _make_case(db, pid, priority="P0", case_type="PERMISSION")
        run = _make_run(db, pid, [{"status": "FAILED", "duration_ms": 1, "case": cperm}])
        svc = ReportService()
        rid = svc.build_report(db, run.id, actor=actor, generate_ai_summary=False).report_id
        detail = svc.get_report(db, rid, actor)
        summary_blob = str(detail.report.summary)
        assert "POTENTIAL_BUG" in summary_blob
        for bad in ("已发现Bug", "已发现缺陷", "确认是Bug", "bug已确认"):
            assert bad not in summary_blob
