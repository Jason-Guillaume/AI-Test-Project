"""扫描编排器（§七 / §八 / §二十一 / §二十二 / §二十五）。

由 Worker 调用，**绝不在 HTTP 请求里同步执行**（§八 禁止在 FastAPI 请求中同步等待）。

阶段顺序：
    PREPARING → AUTHENTICATING → CRAWLING → PASSIVE_SCANNING → ACTIVE_SCANNING → IMPORTING_RESULTS

每个检查点都会：
- 检查 cancel_requested，置位则停止扫描并置 CANCELLED；
- 检查耗时是否超过策略与全局上限，超过则置 TIMED_OUT；
- 刷新 heartbeat_at / poll_count，供其它进程判断任务是否还活着。

进程重启后本模块不负责恢复中间态：统一由 Worker 的启动扫描判为 TIMED_OUT（§八 任务恢复）。

Finding 落库口径（§二十二 / §十九）：
- 每条 ZAP 告警先归一化，再用 fingerprint 命中 Phase 1 的 ``security_finding``；
- 重复命中只新增 ``security_scan_finding`` 关系行，**不修改** Finding 的 status /
  verified_by / verified_at / note；
- 不伪造 CaseExecution：扫描任务不是普通 API 单用例，只通过报告层聚合。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.features.security_testing.models.finding import SecurityFinding
from app.features.test_management.models.execution import TestRun
from app.features.security_testing.zap import event_log, scope_guard
from app.features.security_testing.zap.auth import build_auth_config, check_credential_live
from app.features.security_testing.zap.connector import (
    ZAP_REASON_PLUGIN_MISSING,
    ZAPConnector,
    ZAPConnectorError,
)
from app.features.security_testing.zap.contracts import (
    AUTH_MODE_MANUAL,
    AUTH_STATUS_LOGGED_IN,
    AUTH_STATUS_UNVERIFIABLE,
    EVENT_TYPE_ALERT,
    EVENT_TYPE_AUTH,
    EVENT_TYPE_ERROR,
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STAGE,
    EVENT_TYPE_WARNING,
    JOB_STATUS_ACTIVE_SCANNING,
    JOB_STATUS_AUTHENTICATING,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_CRAWLING,
    JOB_STATUS_FAILED,
    JOB_STATUS_IMPORTING_RESULTS,
    JOB_STATUS_PASSIVE_SCANNING,
    JOB_STATUS_PREPARING,
    JOB_STATUS_TIMED_OUT,
    ZAPCapabilities,
    WEB_CRAWL_MODES,
    is_active_scan,
)
from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
from app.features.security_testing.zap.models.finding_link import SecurityScanFinding
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.features.security_testing.zap.normalizer import (
    NormalizedZAPAlert,
    ZAPAlertNormalizer,
)
from app.features.security_testing.zap.openapi_export import (
    build_openapi_document,
    count_interfaces,
    render_openapi_json,
)
from app.features.security_testing.zap.services import auth_profile_service
from app.shared.config import settings
from app.shared.database import SessionLocal
from app.shared.errors import AppError

log = logging.getLogger(__name__)


class ScanCancelled(Exception):
    """任务被显式取消，走 CANCELLED 终态而不是 FAILED。"""


class ScanTimedOut(Exception):
    """任务超过时长上限，走 TIMED_OUT 终态。"""


@dataclass(slots=True)
class ScanSnapshot:
    """任务快照：Worker 领取后一次性读出，避免在长等待中持有 Session。"""

    job_id: int
    project_id: int
    target_id: int | None
    profile_id: int
    scan_mode: str
    test_run_id: int | None = None
    environment_id: int | None = None
    target_name: str = ""
    base_url: str = ""
    entry_url: str | None = None
    target_type: str = "API"
    environment_name: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    authorization_status: str = ""
    active_scan_allowed: bool = False
    auth_mode: str | None = None
    profile_name: str = ""
    spider_enabled: bool = True
    client_spider_enabled: bool = False
    passive_enabled: bool = True
    active_enabled: bool = False
    max_duration: int = 30
    max_depth: int = 5
    max_concurrency: int = 4
    request_delay: int = 300
    max_alerts_per_rule: int | None = None
    max_request_budget: int | None = None
    include_paths_profile: list[str] = field(default_factory=list)
    exclude_paths_profile: list[str] = field(default_factory=list)
    selected_rule_ids: list[str] = field(default_factory=list)


class ScanOrchestrator:
    """驱动一个扫描任务走完全部阶段。"""

    def __init__(
        self,
        connector: ZAPConnector,
        *,
        db_factory: Callable[[], Session] = SessionLocal,
        poll_interval_seconds: float = 3.0,
        passive_wait_seconds: float | None = None,
        max_job_duration_seconds: int | None = None,
    ) -> None:
        """初始化编排器。

        Args:
            connector: 已构造好的 ZAP 连接器（Worker 通过 client.build_connector 创建）。
            db_factory: 每个检查点新建一个 Session，长等待不占用事务。
            poll_interval_seconds: 阶段内的轮询间隔，同时是取消 / 超时的检查粒度。
            passive_wait_seconds: 单次等待被动扫描队列清空的超时。
            max_job_duration_seconds: 全局任务时长上限（默认取 ZAP_MAX_JOB_DURATION_SECONDS）。
        """
        self._connector = connector
        self._db_factory = db_factory
        self._poll = max(0.2, float(poll_interval_seconds))
        self._passive_wait = (
            float(passive_wait_seconds)
            if passive_wait_seconds is not None
            else max(5.0, float(settings.ZAP_PASSIVE_WAIT_SECONDS))
        )
        self._max_duration = int(
            max_job_duration_seconds or int(settings.ZAP_MAX_JOB_DURATION_SECONDS)
        )

    # ------------------------------------------------------------------ 入口

    def run(self, job_id: int) -> str:
        """走完一个任务，返回终态字符串。"""
        snap = self._load_snapshot(job_id)
        if snap is None:
            log.warning("ZAP 扫描任务 %s 无法加载快照（任务或目标不存在）", job_id)
            return JOB_STATUS_FAILED
        if snap.target_id is None or not snap.base_url:
            self._fail(snap, "SECURITY_SCAN_TARGET_NOT_FOUND", "扫描目标不存在或未配置扫描根地址")
            return JOB_STATUS_FAILED

        started = time.monotonic()
        normalizer = ZAPAlertNormalizer(project_id=snap.project_id, target_id=snap.target_id)
        scan_refs: list[str] = []
        try:
            self._stage_preparing(snap, started)
            self._stage_authenticating(snap, started)
            self._stage_crawling(snap, started, scan_refs)
            self._stage_passive(snap, started)
            self._stage_active(snap, started, scan_refs)
            self._stage_import(snap, started, normalizer)
            # 成功路径也要落库：只把 status 赋给局部变量会让任务永远停在 IMPORTING_RESULTS。
            self._finalize(snap, JOB_STATUS_COMPLETED)
            status = JOB_STATUS_COMPLETED
        except ScanCancelled as exc:
            status = JOB_STATUS_CANCELLED
            self._emit(snap, EVENT_TYPE_WARNING, exc.stage, "扫描已按请求取消")
            self._finalize(snap, JOB_STATUS_CANCELLED, error_message="扫描已按请求取消")
        except ScanTimedOut as exc:
            status = JOB_STATUS_TIMED_OUT
            self._emit(snap, EVENT_TYPE_WARNING, exc.stage, "扫描超过最长运行时间")
            self._finalize(
                snap, JOB_STATUS_TIMED_OUT, error_code="SECURITY_SCAN_TIMEOUT",
                error_message="扫描超过最长运行时间",
            )
        except ZAPConnectorError as exc:
            status = JOB_STATUS_FAILED
            self._emit(snap, EVENT_TYPE_ERROR, snap.scan_mode, exc.message)
            self._finalize(
                snap, JOB_STATUS_FAILED, error_code=_connector_error_code(exc), error_message=exc.message,
            )
        except AppError as exc:
            status = JOB_STATUS_FAILED
            code = getattr(exc, "code", None) or "SECURITY_SCAN_SCOPE_VIOLATION"
            self._emit(snap, EVENT_TYPE_ERROR, snap.scan_mode, exc.message)
            self._finalize(snap, JOB_STATUS_FAILED, error_code=code, error_message=exc.message)
        except Exception as exc:  # noqa: BLE001 - 兜底：任务必须有终态
            status = JOB_STATUS_FAILED
            log.exception("ZAP 扫描任务 %s 执行出现未预期异常", job_id)
            self._emit(snap, EVENT_TYPE_ERROR, snap.scan_mode, "扫描执行出现未预期异常")
            self._finalize(snap, JOB_STATUS_FAILED, error_message="扫描执行出现未预期异常")
        finally:
            self._stop_scans(scan_refs)
            try:
                self._connector.close()
            except Exception:  # noqa: BLE001
                log.warning("关闭 ZAP 连接器失败", exc_info=True)
        return status

    # ------------------------------------------------------------------ 快照

    def _load_snapshot(self, job_id: int) -> ScanSnapshot | None:
        """一次性读出任务、目标、策略、认证配置与环境。"""
        with self._db_factory() as db:
            job = db.get(SecurityScanJob, job_id)
            if job is None:
                return None
            target = db.get(SecurityScanTarget, job.target_id) if job.target_id else None
            profile = db.get(SecurityScanProfile, job.scan_profile_id)
            if target is None or profile is None:
                return None
            auth: SecurityScanAuthProfile | None = None
            if profile.authentication_profile_id:
                auth = auth_profile_service.get_or_none(db, job.project_id, profile.authentication_profile_id)
            environment_name = ""
            if job.environment_id:
                env_row = db.get(type(self)._environment_model(), job.environment_id)
                environment_name = str(getattr(env_row, "name", "") or "")
            # 兜底防线：创建时的归属校验被绕过（直接改库、历史数据）时，
            # 不把 ZAP Finding 挂到别的项目执行记录上。
            test_run_id = job.test_run_id
            if test_run_id is not None:
                run_row = db.get(TestRun, test_run_id)
                if run_row is None or run_row.project_id != job.project_id:
                    test_run_id = None
            return ScanSnapshot(
                job_id=job.id,
                project_id=job.project_id,
                target_id=target.id,
                profile_id=profile.id,
                scan_mode=job.scan_mode,
                test_run_id=test_run_id,
                environment_id=job.environment_id,
                target_name=target.name,
                base_url=target.base_url,
                entry_url=target.entry_url,
                target_type=target.target_type,
                environment_name=environment_name,
                allowed_hosts=list(target.allowed_hosts or []),
                include_paths=list(target.include_paths or []),
                exclude_paths=list(target.exclude_paths or []),
                authorization_status=str(target.authorization_status or ""),
                active_scan_allowed=bool(target.active_scan_allowed),
                auth_mode=auth.auth_mode if auth else None,
                profile_name=profile.name,
                spider_enabled=bool(profile.spider_enabled),
                client_spider_enabled=bool(profile.client_spider_enabled),
                passive_enabled=bool(profile.passive_enabled),
                active_enabled=bool(profile.active_enabled),
                max_duration=int(profile.max_duration or 30),
                max_depth=int(profile.max_depth or 5),
                max_concurrency=int(profile.max_concurrency or 4),
                request_delay=int(profile.request_delay or 300),
                max_alerts_per_rule=profile.max_alerts_per_rule,
                max_request_budget=profile.max_request_budget,
                include_paths_profile=list(profile.include_paths or []),
                exclude_paths_profile=list(profile.exclude_paths or []),
                selected_rule_ids=list(profile.selected_rule_ids or []),
            )

    @staticmethod
    def _environment_model() -> type:
        """延迟导入环境模型，避免 Worker 在无环境表的项目里循环依赖。"""
        from app.models.configuration import Environment

        return Environment

    # ------------------------------------------------------------------ 阶段 1

    def _stage_preparing(self, snap: ScanSnapshot, started: float) -> None:
        """PREPARING：连通性、能力检测、范围设置、Context 创建、OpenAPI 导入。"""
        self._checkpoint(snap, JOB_STATUS_PREPARING, "准备扫描上下文", progress=1)
        self._emit(snap, EVENT_TYPE_STAGE, JOB_STATUS_PREPARING, "开始准备扫描上下文")

        # 运行期再校验一次范围与授权：创建到执行之间配置可能已经变化（§三十四）。
        scope_guard.validate_target_url(snap.base_url, allowed_hosts=snap.allowed_hosts or None)
        scope_guard.assert_active_scan_authorized(
            environment_name=snap.environment_name,
            scan_mode=snap.scan_mode,
            active_authorized=snap.authorization_status == scope_guard.AUTHORIZATION_STATUS_AUTHORIZED,
            environment_active_allowed=snap.active_scan_allowed,
        )

        about = self._connector.check_health()
        capabilities = self._connector.get_capabilities()
        missing = [
            cap.name for cap in capabilities.capabilities
            if not cap.supported and cap.name in ("spider", "passive", "active", "history")
        ]
        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
            f"ZAP {about.version} 已连接，能力检测完成",
            {"zap_version": about.version, "add_on_count": len(capabilities.about.add_on_names),
             "missing_core_capabilities": missing},
        )
        if missing:
            self._fail(snap, "ZAP_PLUGIN_MISSING", f"ZAP 缺少必需插件：{', '.join(missing)}")

        host_pattern = _host_pattern(snap.base_url)
        self._connector.apply_scope(
            base_url=snap.base_url,
            allowed_hosts=snap.allowed_hosts,
            include_paths=self._merged_paths(snap.include_paths, snap.include_paths_profile),
            exclude_paths=self._merged_paths(snap.exclude_paths, snap.exclude_paths_profile),
        )
        context = self._connector.create_scan_context(host_pattern=host_pattern)
        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
            f"扫描上下文已创建：{context.host_pattern}",
        )

        # 接口契约导入：把平台 API 契约喂给 ZAP 的 OpenAPI Support，
        # 让 ZAP 按契约发起请求而不是只靠爬虫发现（Phase C）。
        self._import_openapi(snap, capabilities)

        # 默认低强度：只在主动扫描时收紧规则集与危险路径排除（§十五）。
        # 这里的值全部会被 connector 再截断到硬上限，策略里的数字不是可信输入。
        if snap.active_enabled and is_active_scan(snap.scan_mode):
            self._connector.set_active_scan_limits(
                max_duration=min(int(snap.max_duration or 20), 60),
                max_concurrency=min(int(snap.max_concurrency or 5), 20),
                request_delay_ms=snap.request_delay,
                max_alerts_per_rule=snap.max_alerts_per_rule or 20,
            )
            self._emit(
                snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
                "已按低强度参数收紧主动扫描限额",
                {"max_duration_minutes": min(int(snap.max_duration or 20), 60),
                 "max_concurrency": min(int(snap.max_concurrency or 5), 20),
                 "request_delay_ms": snap.request_delay},
            )
        self._update_job(snap, stage=JOB_STATUS_PREPARING)

    def _import_openapi(self, snap: ScanSnapshot, capabilities: ZAPCapabilities) -> None:
        """把项目接口契约导入 ZAP 的 OpenAPI Support（Phase C）。

        组件缺失时不失败：如实记录为功能限制并降级为爬虫发现，绝不伪造「已导入」
        （§三：实际 API 不支持时必须给出兼容实现或明确标记功能限制）。
        """
        if not any(
            cap.name == "openapi" and cap.supported for cap in capabilities.capabilities
        ):
            self._emit(
                snap, EVENT_TYPE_WARNING, JOB_STATUS_PREPARING,
                "ZAP 未启用 OpenAPI Support 组件，接口发现将依赖爬虫，覆盖面受限",
                {"limitation": "no_openapi_support"},
            )
            return

        with self._db_factory() as db:
            document = build_openapi_document(
                db,
                snap.project_id,
                base_url=snap.base_url,
                target_name=snap.target_name,
                environment_name=snap.environment_name,
            )
        total = count_interfaces(document)
        if total == 0:
            self._emit(
                snap, EVENT_TYPE_WARNING, JOB_STATUS_PREPARING,
                "项目接口契约为空，接口发现只能依赖爬虫",
                {"limitation": "no_api_contract"},
            )
            return

        try:
            result = self._connector.import_openapi(render_openapi_json(document))
        except ZAPConnectorError as exc:
            if exc.reason != ZAP_REASON_PLUGIN_MISSING:
                raise
            self._emit(
                snap, EVENT_TYPE_WARNING, JOB_STATUS_PREPARING,
                "ZAP 缺少 OpenAPI Support 组件，接口发现将依赖爬虫，覆盖面受限",
                {"limitation": "no_openapi_support", "interfaces": total},
            )
            return

        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
            f"已向 ZAP 导入 {total} 个接口定义",
            {"interfaces": total, "zap_response": result},
        )

    def _stage_authenticating(self, snap: ScanSnapshot, started: float) -> None:
        """AUTHENTICATING：配置认证并验证登录态（不是只看 HTTP 200）。"""
        self._checkpoint(snap, JOB_STATUS_AUTHENTICATING, "配置并验证认证状态", progress=8)
        self._emit(snap, EVENT_TYPE_STAGE, JOB_STATUS_AUTHENTICATING, "开始配置认证")

        auth_profile = self._load_auth_profile(snap)
        auth_mode = auth_profile.auth_mode if auth_profile else "NONE"
        credential = auth_profile_service.decrypt_credential(auth_profile) if auth_profile else ""

        # 扫描前先按用户配置的验证接口确认真实登录态，不以 HTTP 200 为准（§十一）。
        live_ok = False
        live_logged_in = False
        live_detail = ""
        if auth_profile is not None and auth_profile.authentication_check_url and auth_mode != AUTH_MODE_MANUAL:
            live_ok, live_logged_in, live_detail = check_credential_live(
                check_url=auth_profile.authentication_check_url,
                credential=credential,
                auth_mode=auth_mode,
                session_header=auth_profile.session_header or "",
                session_name=auth_profile.session_name or "",
                logged_in_indicator=auth_profile.logged_in_indicator or "",
                logged_out_indicator=auth_profile.logged_out_indicator or "",
                expected_user_id=auth_profile.expected_user_id or "",
                allowed_hosts=snap.allowed_hosts or None,
            )
            self._emit(
                snap, EVENT_TYPE_AUTH, JOB_STATUS_AUTHENTICATING,
                f"登录态预检查：{'可达' if live_ok else '不可达'}，{'已登录' if live_logged_in else '未登录或无法判定'}",
                {"reachable": live_ok, "logged_in": live_logged_in, "detail": live_detail},
            )
            if not live_ok:
                self._fail(snap, "SECURITY_SCAN_AUTH_FAILED", f"登录态验证失败：{live_detail}")
            if live_ok and not live_logged_in:
                self._fail(snap, "SECURITY_SCAN_AUTH_EXPIRED", f"登录态验证未通过：{live_detail}")

        config = build_auth_config(auth_profile)
        result = self._connector.configure_authentication(config)
        browser_ok, browser_reason = self._connector.browser_session_established()

        status = result.status
        if auth_profile is not None:
            # 以验证接口的结论为准：它是我们唯一能真实观测到的登录态。
            status = AUTH_STATUS_LOGGED_IN if live_logged_in else AUTH_STATUS_UNVERIFIABLE
        if snap.scan_mode in WEB_CRAWL_MODES and not browser_ok:
            status = AUTH_STATUS_UNVERIFIABLE
            self._emit(
                snap, EVENT_TYPE_WARNING, JOB_STATUS_AUTHENTICATING,
                f"无法建立浏览器登录态：{browser_reason}",
                {"browser_reason": browser_reason},
            )
        self._emit(
            snap, EVENT_TYPE_AUTH, JOB_STATUS_AUTHENTICATING,
            f"认证验证结果：{status}",
            {"auth_mode": auth_mode, "authenticated": bool(result.authenticated),
             "verified": bool(result.verified), "live_check": live_ok,
             "live_logged_in": live_logged_in, "live_detail": live_detail,
             "browser_session": browser_ok, "browser_reason": browser_reason},
        )
        self._update_job(
            snap,
            authentication_mode=auth_mode,
            authentication_status=status,
            browser_session_established=bool(browser_ok),
            stage=JOB_STATUS_AUTHENTICATING,
            progress=12,
        )
        if status != AUTH_STATUS_LOGGED_IN and auth_profile is not None:
            # 需要登录才能继续爬业务页面，但明确验证为未登录 → 记为失败而不是静默继续。
            if result.verified and not result.authenticated:
                self._fail(snap, "SECURITY_SCAN_AUTH_FAILED", "认证凭据验证失败：当前会话未登录")

    def _stage_crawling(self, snap: ScanSnapshot, started: float, scan_refs: list[str]) -> None:
        """CRAWLING：Client Spider 优先，失败或不可用时退回传统 Spider。"""
        if snap.scan_mode not in WEB_CRAWL_MODES:
            return
        self._checkpoint(snap, JOB_STATUS_CRAWLING, "爬取页面与 API", progress=20)
        self._emit(snap, EVENT_TYPE_STAGE, JOB_STATUS_CRAWLING, "开始爬取")

        entry = snap.entry_url or snap.base_url
        # 入口地址是 ZAP 真正会访问的第一个地址：在发出任何爬虫请求之前再校验一次，
        # 避免创建到执行之间配置变化把范围悄悄扩大（§三十四 第 1 条）。
        scope_guard.assert_redirect_allowed(
            entry, base_url=snap.base_url, allowed_hosts=snap.allowed_hosts or None,
        )
        refs: list[str] = []
        crawler_kind = ""
        if snap.client_spider_enabled:
            try:
                refs.append(self._connector.start_client_spider(entry, max_depth=snap.max_depth)["scan_ref"])
                crawler_kind = "client_spider"
            except ZAPConnectorError as exc:
                if exc.reason in ("ZAP_PLUGIN_MISSING", "ZAP_SPIDER_FAILED"):
                    self._emit(
                        snap, EVENT_TYPE_WARNING, JOB_STATUS_CRAWLING,
                        f"Client Spider 不可用，改用传统 Spider：{exc.message}",
                    )
                else:
                    raise
        if not refs and snap.spider_enabled:
            refs.append(self._connector.start_spider(entry, max_depth=snap.max_depth)["scan_ref"])
            crawler_kind = crawler_kind or "spider"
        if not refs:
            self._fail(snap, "SECURITY_SCAN_SPIDER_FAILED", "策略未启用任何可用爬虫，无法采集扫描对象")

        scan_refs.extend(r for r in refs if r)
        done = self._wait_scans(snap, started, scan_refs, stage=JOB_STATUS_CRAWLING,
                                base_progress=20, span=40)
        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_CRAWLING,
            f"爬取结束（{crawler_kind}），发现 {done.urls} 个 URL",
            {"crawler": crawler_kind, "scan_refs": scan_refs, "urls": done.urls},
        )
        self._update_job(snap, zap_scan_reference=",".join(scan_refs), urls_discovered=done.urls)

    def _stage_passive(self, snap: ScanSnapshot, started: float) -> None:
        """PASSIVE_SCANNING：被动扫描在请求产生时自动运行，这里等待队列清空。"""
        if not snap.passive_enabled:
            return
        self._checkpoint(snap, JOB_STATUS_PASSIVE_SCANNING, "等待被动扫描完成", progress=62)
        self._emit(snap, EVENT_TYPE_STAGE, JOB_STATUS_PASSIVE_SCANNING, "等待被动扫描队列清空")
        self._connector.start_passive_scan()
        deadline_polls = max(1, int(self._passive_wait / self._poll))
        for tick in range(deadline_polls):
            if self._cancel_requested(snap):
                raise ScanCancelled(JOB_STATUS_PASSIVE_SCANNING)
            if time.monotonic() - started > self._effective_duration(snap):
                raise ScanTimedOut(JOB_STATUS_PASSIVE_SCANNING)
            progress = self._connector.wait_passive_scan(
                timeout_seconds=self._poll, poll_interval=self._poll,
            )
            self._heartbeat(snap, JOB_STATUS_PASSIVE_SCANNING, 62 + int(8 * tick / deadline_polls),
                            alerts=progress.alerts)
            if not progress.running:
                self._emit(
                    snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PASSIVE_SCANNING,
                    "被动扫描队列已清空", {"alerts": progress.alerts},
                )
                self._update_job(snap, progress=70, stage=JOB_STATUS_PASSIVE_SCANNING)
                return
        self._emit(
            snap, EVENT_TYPE_WARNING, JOB_STATUS_PASSIVE_SCANNING,
            "被动扫描未在规定时间内完成，继续后续阶段",
            {"passive_wait_seconds": self._passive_wait},
        )
        self._update_job(snap, progress=70, stage=JOB_STATUS_PASSIVE_SCANNING)

    def _stage_active(self, snap: ScanSnapshot, started: float, scan_refs: list[str]) -> None:
        """ACTIVE_SCANNING：受控主动扫描；未授权或非主动模式直接跳过。"""
        if not is_active_scan(snap.scan_mode) or not snap.active_enabled:
            return
        self._checkpoint(snap, JOB_STATUS_ACTIVE_SCANNING, "执行受控主动扫描", progress=74)
        self._emit(snap, EVENT_TYPE_STAGE, JOB_STATUS_ACTIVE_SCANNING, "开始主动扫描（低强度）")

        # 范围与危险路径排除必须在发出任何扫描请求之前生效（§十五）。
        # 排除清单为空时退回到内置高危路径清单，绝不因为「用户没填」就扫 logout / delete / payment。
        exclude = self._merged_paths(snap.exclude_paths, snap.exclude_paths_profile) or list(
            scope_guard.HIGH_RISK_ACTIVE_PATH_PATTERNS,
        )
        scan_id = self._connector.start_active_scan(
            snap.base_url,
            max_duration=min(int(snap.max_duration or 20), 60),
            max_concurrency=min(int(snap.max_concurrency or 5), 20),
            request_delay_ms=snap.request_delay,
            max_alerts_per_rule=snap.max_alerts_per_rule or 20,
            selected_rule_ids=snap.selected_rule_ids,
            excluded_paths=exclude,
        )
        if scan_id:
            scan_refs.append(scan_id)
        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_ACTIVE_SCANNING,
            "主动扫描已启动",
            {"scan_id": scan_id, "excluded_paths": exclude, "selected_rule_ids": snap.selected_rule_ids},
        )
        if self._cancel_requested(snap):
            raise ScanCancelled(JOB_STATUS_ACTIVE_SCANNING)
        done = self._wait_scans(snap, started, scan_refs, stage=JOB_STATUS_ACTIVE_SCANNING,
                                base_progress=74, span=24)
        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_ACTIVE_SCANNING,
            f"主动扫描结束，累计告警 {done.alerts} 条",
            {"alerts": done.alerts, "requests": done.requests},
        )
        self._update_job(snap, progress=98, stage=JOB_STATUS_ACTIVE_SCANNING)

    def _stage_import(self, snap: ScanSnapshot, started: float, normalizer: ZAPAlertNormalizer) -> None:
        """IMPORTING_RESULTS：拉取告警、归一化、去重落库、生成覆盖汇总。"""
        self._checkpoint(snap, JOB_STATUS_IMPORTING_RESULTS, "导入扫描结果", progress=100)
        self._emit(snap, EVENT_TYPE_STAGE, JOB_STATUS_IMPORTING_RESULTS, "开始导入扫描结果")

        alerts = self._connector.get_alerts()
        alert_counts = self._connector.get_alert_counts(alerts)
        pages, counts_from_stats = self._connector.get_scan_statistics()
        urls = self._connector.list_urls()

        new_count = 0
        duplicate_count = 0
        severity_counts: dict[str, int] = {}
        emitted = 0
        with self._db_factory() as db:
            for alert in alerts:
                # 导入是取消请求能生效的最后一站；不检查的话点取消会得到一个已完成的任务。
                self._check_running(snap, started, JOB_STATUS_IMPORTING_RESULTS)
                item = normalizer.normalize(alert, scan_job_id=snap.job_id)
                proposal = normalizer.finding_fields(item)
                finding, is_new = _upsert_zap_finding(
                    db,
                    project_id=snap.project_id,
                    test_run_id=snap.test_run_id,
                    scan_job_id=snap.job_id,
                    item=item,
                    proposal=proposal,
                )
                if finding is None:
                    continue
                link, was_new = _link_scan_finding(
                    db,
                    project_id=snap.project_id,
                    job_id=snap.job_id,
                    finding=finding,
                    item=item,
                )
                if is_new:
                    new_count += 1
                else:
                    duplicate_count += 1
                severity_counts[item.severity] = severity_counts.get(item.severity, 0) + 1
                if link is not None and was_new and emitted < 50:
                    self._emit_db(
                        db, snap, EVENT_TYPE_ALERT, JOB_STATUS_IMPORTING_RESULTS,
                        f"发现潜在问题：{item.name}",
                        {"rule_id": item.rule_id, "url": item.url, "severity": item.severity,
                         "confidence": item.confidence, "finding_id": int(finding.id)},
                    )
                    emitted += 1
                db.commit()

        in_scope, dropped = self._split_scope(urls, snap)
        if dropped:
            # 范围外的地址进不了覆盖统计：报告不能声称扫了未授权的目标（§三十四）。
            self._emit(
                snap, EVENT_TYPE_WARNING, JOB_STATUS_IMPORTING_RESULTS,
                f"发现 {len(dropped)} 个范围外的地址，未计入覆盖统计",
                {"out_of_scope_sample": dropped[:5]},
            )
        coverage = _build_coverage(
            urls=in_scope, pages=pages, alerts=alerts, items=len(alerts),
        )
        self._update_job(
            snap,
            total_alerts=int(alert_counts.total or 0),
            high_count=int(alert_counts.high or 0),
            medium_count=int(alert_counts.medium or 0),
            low_count=int(alert_counts.low or 0),
            info_count=int(alert_counts.info or 0),
            urls_discovered=pages.urls or len(urls),
            requests_made=pages.requests,
            new_findings_count=new_count,
            duplicate_findings_count=duplicate_count,
            coverage_summary=coverage,
            stage=JOB_STATUS_IMPORTING_RESULTS,
        )
        self._emit(
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_IMPORTING_RESULTS,
            f"结果导入完成：新增 {new_count} 条，重复 {duplicate_count} 条",
            {"alerts": len(alerts), "new": new_count, "duplicates": duplicate_count,
             "severity_counts": severity_counts,
             "page_stats": {"pages": pages.pages, "requests": pages.requests, "urls": pages.urls},
             "counts_from_stats": counts_from_stats.as_dict()},
        )

    # ------------------------------------------------------------------ 检查点

    def _wait_scans(
        self,
        snap: ScanSnapshot,
        started: float,
        scan_refs: list[str],
        *,
        stage: str,
        base_progress: int,
        span: int,
    ) -> Any:
        """轮询 ZAP 直到指定 scan id 全部结束；期间检查取消与超时。"""
        tick = 0
        max_ticks = max(1, int(self._max_duration / self._poll))
        while tick < max_ticks:
            if self._cancel_requested(snap):
                raise ScanCancelled(stage)
            if time.monotonic() - started > self._effective_duration(snap):
                raise ScanTimedOut(stage)
            progress = self._connector.get_scan_progress(scan_refs)
            tick += 1
            percent = base_progress + int(span * min(1.0, tick / max(1, max_ticks)))
            self._heartbeat(snap, stage, min(percent, base_progress + span - 1),
                            urls=progress.urls, requests=progress.requests, alerts=progress.alerts)
            if not progress.running:
                return progress
            time.sleep(self._poll)
        self._emit(snap, EVENT_TYPE_WARNING, stage, "轮询达到上限，进入下一阶段")
        return self._connector.get_scan_progress(scan_refs)

    def _checkpoint(self, snap: ScanSnapshot, stage: str, message: str, progress: int = 0) -> None:
        """进入新阶段：写状态 + 心跳 + 阶段事件。"""
        self._heartbeat(snap, stage, progress)
        self._emit(snap, EVENT_TYPE_STAGE, stage, message)

    def _effective_duration(self, snap: ScanSnapshot) -> float:
        return float(min(self._max_duration, int(snap.max_duration or 30) * 60))

    def _cancel_requested(self, snap: ScanSnapshot) -> bool:
        with self._db_factory() as db:
            row = db.get(SecurityScanJob, snap.job_id)
            return bool(row.cancel_requested) if row is not None else False

    def _check_running(self, snap: ScanSnapshot, started: float, stage: str) -> None:
        """检查取消位与总时长：每个阶段都要守，否则取消会被静默忽略（§八）。"""
        if self._cancel_requested(snap):
            raise ScanCancelled(stage)
        if time.monotonic() - started > self._effective_duration(snap):
            raise ScanTimedOut(stage)

    def _split_scope(self, urls: list[str], snap: ScanSnapshot) -> tuple[list[str], list[str]]:
        """把发现到的地址分成「范围内」与「范围外」两组。

        只做主机与端口的字符串比较，不发起 DNS 查询：发现地址可能有上千条，
        逐条解析会把导入阶段拖死。范围外不等于违规（爬虫可能只是看到了链接），
        但它们不能出现在覆盖统计里。
        """
        allowed = scope_guard._normalize_host_port_set(snap.allowed_hosts or None)
        base_netloc = (urlsplit(snap.base_url or "").netloc or "").lower()
        in_scope: list[str] = []
        dropped: list[str] = []
        for raw in urls or []:
            url = str(raw or "").strip()
            if not url:
                continue
            netloc = (urlsplit(url).netloc or "").lower()
            if netloc and (
                (allowed and netloc not in allowed)
                or (not allowed and netloc != base_netloc)
            ):
                dropped.append(url)
            else:
                in_scope.append(url)
        return in_scope, dropped

    def _heartbeat(
        self,
        snap: ScanSnapshot,
        stage: str,
        progress: int,
        *,
        urls: int = 0,
        requests: int = 0,
        alerts: int = 0,
    ) -> None:
        """刷新心跳与进度；不写事件，保持调用频率可控。"""
        with self._db_factory() as db:
            row = db.get(SecurityScanJob, snap.job_id)
            if row is None:
                return
            row.status = stage
            row.stage = stage
            row.progress = int(progress)
            row.heartbeat_at = _now()
            row.poll_count = int(row.poll_count or 0) + 1
            if urls:
                row.urls_discovered = int(urls)
            if requests:
                row.requests_made = int(requests)
            if alerts:
                row.total_alerts = int(alerts)
            db.commit()

    def _update_job(self, snap: ScanSnapshot, **fields: Any) -> None:
        """更新任务字段的通用入口。"""
        with self._db_factory() as db:
            row = db.get(SecurityScanJob, snap.job_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()

    def _load_auth_profile(self, snap: ScanSnapshot) -> SecurityScanAuthProfile | None:
        with self._db_factory() as db:
            row = db.get(SecurityScanProfile, snap.profile_id)
            if row is None or not row.authentication_profile_id:
                return None
            return auth_profile_service.get_or_none(db, snap.project_id, row.authentication_profile_id)

    def _emit(self, snap: ScanSnapshot, event_type: str, stage: str, message: str,
              payload: dict[str, Any] | None = None) -> None:
        with self._db_factory() as db:
            self._emit_db(db, snap, event_type, stage, message, payload)

    @staticmethod
    def _emit_db(
        db: Session, snap: ScanSnapshot, event_type: str, stage: str, message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """写一条过程事件；payload 必须先脱敏，seq 分配与并发重试统一在 event_log。"""
        event_log.add_event(
            db,
            job_id=snap.job_id,
            project_id=snap.project_id,
            event_type=event_type,
            stage=stage,
            message=str(message or ""),
            payload=payload,
        )

    def _finalize(
        self,
        snap: ScanSnapshot,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """写终态与耗时。"""
        with self._db_factory() as db:
            row = db.get(SecurityScanJob, snap.job_id)
            if row is None:
                return
            row.status = status
            row.finished_at = _now()
            if row.started_at is not None:
                row.duration_ms = int((_now() - row.started_at).total_seconds() * 1000)
            if error_code:
                row.error_code = error_code
            if error_message:
                row.error_message = str(error_message)[:500]
            db.commit()
        self._emit(snap, EVENT_TYPE_STAGE, status, f"任务结束：{status}")

    def _fail(self, snap: ScanSnapshot, code: str, message: str) -> None:
        """以失败终态结束任务（异常形式向上抛，由 run() 统一收尾）。"""
        raise AppError(message, status_code=400, code=code)

    @staticmethod
    def _merged_paths(*groups: list[str]) -> list[str]:
        """合并目标与策略上的路径清单，去重保序。"""
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for item in group or []:
                text = str(item).strip()
                if text and text not in seen:
                    seen.add(text)
                    merged.append(text)
        return merged

    def _stop_scans(self, scan_refs: list[str]) -> None:
        """尽力停止仍在跑的 ZAP 扫描；失败只记日志，不影响终态写入。"""
        refs = [r for r in scan_refs if r]
        if not refs:
            return
        try:
            self._connector.stop_scan(refs)
        except Exception as exc:  # noqa: BLE001
            log.warning("停止 ZAP 扫描失败：%s", exc)


def _now():
    """任务时间戳：统一用 UTC 感知不到的 naive 本地时间，与仓库其它表保持一致。"""
    from datetime import datetime

    return datetime.now()


def _host_pattern(base_url: str) -> str:
    """从扫描根地址提取 ZAP Context 用的 host 模式。"""
    from urllib.parse import urlsplit

    parts = urlsplit(base_url or "")
    netloc = parts.netloc or ""
    host = netloc.split("@")[-1].split(":")[0]
    port = ""
    if ":" in netloc and not netloc.startswith("["):
        host, _, port = netloc.partition(":")
    elif netloc.startswith("["):
        end = netloc.find("]")
        host = netloc[1:end]
        rest = netloc[end + 1:]
        if rest.startswith(":"):
            port = rest[1:]
    if port:
        return f"{host}:{port}"
    return host


def _connector_error_code(exc: ZAPConnectorError) -> str:
    """ZAP 连接器原因码 → 平台错误码。"""
    mapping = {
        "ZAP_SERVICE_UNAVAILABLE": "ZAP_SERVICE_UNAVAILABLE",
        "ZAP_API_AUTH_FAILED": "ZAP_API_AUTH_FAILED",
        "ZAP_PLUGIN_MISSING": "ZAP_PLUGIN_MISSING",
        "ZAP_VERSION_UNSUPPORTED": "ZAP_VERSION_UNSUPPORTED",
        "ZAP_CONTEXT_FAILED": "SECURITY_SCAN_CONTEXT_FAILED",
        "ZAP_SPIDER_FAILED": "SECURITY_SCAN_SPIDER_FAILED",
        "ZAP_ACTIVE_FAILED": "SECURITY_SCAN_ACTIVE_FAILED",
        "ZAP_BAD_RESPONSE": "SECURITY_SCAN_RESULT_IMPORT_FAILED",
        "SECURITY_SCAN_SCOPE_VIOLATION": "SECURITY_SCAN_SCOPE_VIOLATION",
    }
    return mapping.get(exc.reason, "SECURITY_SCAN_FAILED")


def _build_coverage(
    *,
    urls: list[str],
    pages: Any,
    alerts: Any,
    items: int,
) -> dict[str, Any]:
    """覆盖率汇总（§三十一）。

    ``coverage_summary`` 存 {"summary": {...}, "rows": [...]} 两部分：
    summary 给列表页聚合，rows 给覆盖率明细接口逐条展示。
    不新增表——覆盖信息是该次扫描的派生结果，不是需要独立生命周期的一等实体。
    """
    from app.features.security_testing.zap.contracts import (
        COVERAGE_ACTIVE_SCANNED,
        COVERAGE_PASSIVE_ANALYZED,
    )

    alert_urls = {getattr(a, "url", "") or "" for a in (alerts or [])}
    unique_urls = sorted({str(u) for u in (urls or []) if u})[:2000]
    pages_count = int(getattr(pages, "urls", 0) or 0) or len(unique_urls)
    requests_count = int(getattr(pages, "requests", 0) or 0)
    responded = min(pages_count, requests_count) if requests_count else pages_count

    rows: list[dict[str, Any]] = []
    for url in unique_urls[:500]:
        covered = url in alert_urls
        rows.append({
            "identifier": url,
            "stage": COVERAGE_ACTIVE_SCANNED if covered else COVERAGE_PASSIVE_ANALYZED,
            "passive_analyzed": True,
            "active_scanned": bool(covered),
        })
    summary = {
        "discovered": len(unique_urls),
        "responded": int(responded),
        "passive_analyzed": int(pages_count),
        "active_scanned": int(len(alert_urls)),
        "not_covered": int(max(0, len(unique_urls) - pages_count)),
    }
    return {"summary": summary, "rows": rows}


def _upsert_zap_finding(
    db: Session,
    *,
    project_id: int,
    test_run_id: int | None,
    scan_job_id: int,
    item: NormalizedZAPAlert,
    proposal: Any,
) -> tuple[Any | None, bool]:
    """按 fingerprint 命中 Phase 1 的 Finding 表；只新增关系，不动人工确认状态。

    Returns:
        (finding, is_new)；fingerprint 或 project_id 缺失时返回 (None, False)。
    """
    from sqlalchemy.exc import IntegrityError

    fingerprint = item.fingerprint
    if not fingerprint or not project_id:
        return None, False

    open_row = (
        db.query(SecurityFinding)
        .filter(
            SecurityFinding.project_id == project_id,
            SecurityFinding.fingerprint == fingerprint,
            SecurityFinding.status.in_(("OPEN", "CONFIRMED")),
        )
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    if open_row is not None:
        evidence = dict(open_row.evidence or {})
        evidence["repeat_count"] = int(evidence.get("repeat_count") or 0) + 1
        evidence["last_scan_job_id"] = scan_job_id
        open_row.evidence = evidence
        if test_run_id:
            open_row.test_run_id = test_run_id
        open_row.updated_at = _now()
        db.add(open_row)
        db.flush()
        return open_row, False

    prior = (
        db.query(SecurityFinding)
        .filter(SecurityFinding.project_id == project_id, SecurityFinding.fingerprint == fingerprint)
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    prior_status = str(getattr(prior, "status", None) or "") if prior is not None else None
    evidence = dict(proposal.evidence or {})
    evidence["repeat_count"] = 1
    evidence["scan_job_id"] = scan_job_id
    if prior is not None:
        # 旧记录已是误报 / 忽略 / 已解决：新记录上写明旧状态，不改动旧记录本身（§十九）。
        evidence["prior_status"] = prior_status
    row = SecurityFinding(
        project_id=project_id,
        test_run_id=test_run_id,
        api_id=None,
        mutation_type=proposal.mutation_type,
        severity=item.severity,
        status="OPEN",
        title=str(proposal.title)[:200],
        description=str(proposal.description)[:8000],
        evidence=evidence,
        recommendation=str(proposal.recommendation)[:8000],
        fingerprint=fingerprint,
        created_by=None,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # 并发插入撞了部分唯一索引：改走更新分支，保证重复命中只累加计数。
        db.rollback()
        open_row = (
            db.query(SecurityFinding)
            .filter(
                SecurityFinding.project_id == project_id,
                SecurityFinding.fingerprint == fingerprint,
                SecurityFinding.status.in_(("OPEN", "CONFIRMED")),
            )
            .order_by(SecurityFinding.id.desc())
            .first()
        )
        if open_row is None:
            return None, False
        evidence = dict(open_row.evidence or {})
        evidence["repeat_count"] = int(evidence.get("repeat_count") or 0) + 1
        evidence["last_scan_job_id"] = scan_job_id
        open_row.evidence = evidence
        if test_run_id:
            open_row.test_run_id = test_run_id
        open_row.updated_at = _now()
        db.add(open_row)
        db.flush()
        return open_row, False
    return row, True


def _link_scan_finding(
    db: Session,
    *,
    project_id: int,
    job_id: int,
    finding: Any,
    item: NormalizedZAPAlert,
) -> tuple[Any | None, bool]:
    """写扫描任务与 Finding 的关系行；同一任务命中同一 Finding 只累加 repeat_count。"""
    existing = (
        db.query(SecurityScanFinding)
        .filter(
            SecurityScanFinding.job_id == job_id,
            SecurityScanFinding.finding_id == finding.id,
        )
        .first()
    )
    if existing is not None:
        existing.repeat_count = int(existing.repeat_count or 1) + 1
        db.add(existing)
        db.flush()
        return existing, False
    row = SecurityScanFinding(
        project_id=project_id,
        job_id=job_id,
        finding_id=finding.id,
        source=item.source,
        source_rule_id=item.rule_id,
        source_alert_name=item.name[:200],
        risk=item.risk,
        confidence=int(item.confidence),
        url=(item.url or "")[:800],
        method=(item.method or "")[:10],
        parameter=(item.parameter or "")[:200],
        fingerprint=item.fingerprint,
        evidence_json=item.as_dict(),
        first_seen_in_job=True,
        repeat_count=1,
    )
    db.add(row)
    db.flush()
    return row, True
