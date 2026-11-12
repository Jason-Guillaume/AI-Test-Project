"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from typing import Iterable
from app.features.security_testing.zap.contracts import ZAPProgress
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_CONCURRENCY_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_DURATION_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_REQUEST_DELAY_MS
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_RULE_DURATION_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MIN_REQUEST_DELAY_MS
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_ACTIVE_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.common import _as_bool
from app.features.security_testing.zap.protocol.common import _escape_regex
from app.features.security_testing.zap.protocol.common import _int_of
from app.features.security_testing.zap.protocol.common import _string_of
from app.features.security_testing.zap.protocol.context import assert_url_in_scope
from app.features.security_testing.zap.protocol.transport import call


def start_passive_scan(state: ZAPProtocolState) -> None:
    """触发被动扫描。

    ZAP 的被动扫描是自动的：请求一产生就分析。这个方法保留在接口上是为了
    让编排层显式表达「这一阶段开始了」，不做任何 ZAP 调用。
    """
    return None


def wait_passive_scan(state: ZAPProtocolState, timeout_seconds: float=120.0, poll_interval: float=1.0) -> ZAPProgress:
    """等待被动扫描队列清空。

    超时不算失败——被动扫描是异步的，超时说明「还没扫完」，
    返回 running=True 让 Worker 决定是继续等还是判超时。

    Worker 应当传入较短的 timeout_seconds（如 30s），
    这样心跳与取消检查还能在两次调用之间执行。
    """
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    interval = max(0.05, float(poll_interval))
    progress = pscan_progress(state, )
    while progress.running and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        time.sleep(min(interval, max(0.05, remaining)))
        progress = pscan_progress(state, )
    return progress


def list_passive_rules(state: ZAPProtocolState) -> list[dict[str, str]]:
    """列出当前生效的被动扫描规则清单（需求 §十四「查看实际扫描规则清单」）。"""
    try:
        body = call(state, "POST", "/JSON/pscan/getActiveRules", timeout_seconds=10.0)
    except ZAPConnectorError:
        return []
    rules: list[dict[str, str]] = []
    if isinstance(body, dict):
        policy = body
    elif isinstance(body, list):
        policy = {str(item): {"description": ""} for item in body}
    else:
        return []
    for rule_id, meta in policy.items():
        description = str(meta.get("description") or "") if isinstance(meta, dict) else ""
        rules.append({"rule_id": str(rule_id), "description": description})
    return rules


def start_active_scan(state: ZAPProtocolState, url: str, *, max_duration: int=20, max_rule_duration: int=10, max_concurrency: int=5, request_delay_ms: int=0, max_alerts_per_rule: int=20, selected_rule_ids: Iterable[str]=(), excluded_paths: Iterable[str]=(), threshold: str='default') -> str:
    """启动受控主动扫描，返回 ZAP scan id。

    所有参数都先过硬上限截断，再下发——**配置值永远不会被信任**。
    selected_rule_ids 为空表示沿用 ZAP 已启用规则；非空时只保留这些规则，
    其余全部关闭（§十五「禁止默认启用所有高强度规则」）。
    """
    assert_url_in_scope(state, url)
    # 攻击开关是运维侧的硬保险：一旦被关掉，平台不得自己改回去（§十五 / §三十四）。
    try:
        policy = call(state, "POST", "/JSON/ascan/getAttackPolicy", timeout_seconds=10.0)
    except ZAPConnectorError:
        policy = None
    if isinstance(policy, dict) and not _as_bool(policy.get("attackEnabled")):
        raise ZAPConnectorError(
            "主动扫描已被禁用（attackEnabled=false），平台不会自动改回开启",
            reason=ZAP_REASON_ACTIVE_FAILED,
        )
    duration = max(1, min(int(max_duration or 20), ACTIVE_MAX_DURATION_HARD_CAP))
    rule_duration = max(1, min(int(max_rule_duration or 10), ACTIVE_MAX_RULE_DURATION_HARD_CAP))
    concurrency = max(1, min(int(max_concurrency or 1), ACTIVE_MAX_CONCURRENCY_HARD_CAP))
    delay = max(ACTIVE_MIN_REQUEST_DELAY_MS, min(int(request_delay_ms or 0), ACTIVE_MAX_REQUEST_DELAY_MS))
    per_rule = max(1, min(int(max_alerts_per_rule or 20), ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP))
    threshold = threshold if threshold in ("default", "low", "medium", "high") else "default"

    knobs = [
        ("POST", "/JSON/ascan/setMaxDurationInMinutes", {"maxDurationInMinutes": duration}),
        ("POST", "/JSON/ascan/setMaxRuleDurationInMinutes", {"maxRuleDurationInMinutes": rule_duration}),
        ("POST", "/JSON/ascan/setConcurrency", {"concurrency": concurrency}),
        ("POST", "/JSON/ascan/setRequestTimingInMs", {"requestTimingInMs": delay}),
        ("POST", "/JSON/ascan/setMaxAlertsPerRule", {"maxAlertsPerRule": per_rule}),
        ("POST", "/JSON/ascan/setDefaultRuleThreshold", {"threshold": threshold}),
        ("POST", "/JSON/ascan/enableAttack", {"state": 1}),
    ]
    excluded = [p for p in excluded_paths if p and p.strip()]
    if excluded:
        knobs.append(("POST", "/JSON/ascan/setAttackPolicy",
                      {"excludedPaths": "|".join(_escape_regex(p) for p in excluded[:100])}))

    try:
        for method, path, body in knobs:
            call(state, method, path, json_body=body, timeout_seconds=10.0)

        wanted = [str(r) for r in selected_rule_ids if r is not None and str(r).strip()]
        if wanted:
            # 只开选中的规则：先关掉全部，再逐个打开。
            for method, path, body in [
                ("POST", "/JSON/ascan/enableAttack", {"state": 1}),
            ]:
                call(state, method, path, json_body=body, timeout_seconds=10.0)
            try:
                policy = call(state, "POST", "/JSON/ascan/getAttackPolicy", timeout_seconds=10.0)
                enabled = {
                    r.strip() for r in str(
                        policy.get("enabledRules") if isinstance(policy, dict) else ""
                    ).split(",") if r.strip()
                }
            except ZAPConnectorError:
                enabled = set()
            for rule_id in enabled - set(wanted):
                call(state, "POST", "/JSON/ascan/enableRule",
                           json_body={"ruleId": rule_id, "state": 0}, timeout_seconds=10.0)
            for rule_id in wanted:
                call(state, "POST", "/JSON/ascan/enableRule",
                           json_body={"ruleId": rule_id, "state": 1}, timeout_seconds=10.0)

        result = call(state, "POST", "/JSON/ascan/scan", json_body={"url": url}, timeout_seconds=30.0)
    except ZAPConnectorError as exc:
        if exc.reason == ZAP_REASON_PLUGIN_MISSING:
            raise ZAPConnectorError(
                "ZAP 缺少主动扫描组件，无法执行受控主动扫描",
                reason=ZAP_REASON_ACTIVE_FAILED,
            ) from exc
        raise

    scan_id = _string_of(result, "scan", result) if isinstance(result, dict) else str(result)
    text = str(scan_id).strip()
    if not text or not text.lstrip("-").isdigit() or int(text) < 0:
        raise ZAPConnectorError(
            "主动扫描被 ZAP 拒绝（目标不在范围内或攻击已关闭）", reason=ZAP_REASON_ACTIVE_FAILED,
        )
    state.scan_ids.append(text)
    return text


def set_active_scan_limits(state: ZAPProtocolState, *, max_duration: int=20, max_rule_duration: int=10, max_concurrency: int=5, request_delay_ms: int=0) -> None:
    """单独设置主动扫描限额（供任务预热与审计核对用）。"""
    duration = max(1, min(int(max_duration or 20), ACTIVE_MAX_DURATION_HARD_CAP))
    rule_duration = max(1, min(int(max_rule_duration or 10), ACTIVE_MAX_RULE_DURATION_HARD_CAP))
    concurrency = max(1, min(int(max_concurrency or 1), ACTIVE_MAX_CONCURRENCY_HARD_CAP))
    delay = max(ACTIVE_MIN_REQUEST_DELAY_MS, min(int(request_delay_ms or 0), ACTIVE_MAX_REQUEST_DELAY_MS))
    call(state, "POST", "/JSON/ascan/setMaxDurationInMinutes",
               json_body={"maxDurationInMinutes": duration}, timeout_seconds=10.0)
    call(state, "POST", "/JSON/ascan/setMaxRuleDurationInMinutes",
               json_body={"maxRuleDurationInMinutes": rule_duration}, timeout_seconds=10.0)
    call(state, "POST", "/JSON/ascan/setConcurrency", json_body={"concurrency": concurrency},
               timeout_seconds=10.0)
    call(state, "POST", "/JSON/ascan/setRequestTimingInMs",
               json_body={"requestTimingInMs": delay}, timeout_seconds=10.0)


def get_scan_progress(state: ZAPProtocolState, scan_ids: Iterable[str]=()) -> ZAPProgress:
    """汇总当前所有阶段的进度。

    percentage 只在 ZAP 明确给出时才填；否则保持 None，
    由前端显示阶段 + 计数而不是虚构一个百分比（§十七）。
    """
    running = False
    alerts = 0
    pages = 0
    requests = 0
    urls = 0
    stages: list[str] = []

    # 爬虫 Spider
    try:
        body = call(state, "POST", "/JSON/spider/isRunning", timeout_seconds=10.0)
        spider_running = _as_bool(body.get("Running")) if isinstance(body, dict) else False
    except ZAPConnectorError:
        spider_running = False
    if spider_running:
        running = True
        stages.append("Spider 爬取")

    # Client Spider（组件缺失时静默降级）
    try:
        body = call(state, "POST", "/JSON/clientspider/isClientSpiderRunning", timeout_seconds=10.0)
        client_running = _as_bool(body.get("Running")) if isinstance(body, dict) else False
    except ZAPConnectorError:
        client_running = False
    if client_running:
        running = True
        stages.append("Client Spider 爬取")

    # 主动扫描
    percentages: list[int] = []
    for scan_id in [s for s in scan_ids if str(s).strip()]:
        try:
            body = call(state, "GET", "/JSON/ascan/progress", params={"scanId": str(scan_id)},
                              timeout_seconds=10.0)
        except ZAPConnectorError:
            continue
        if not isinstance(body, dict):
            continue
        # ascan/progress 对已完成的扫描仍然可读，所以要靠 Percentage 判断是否还在跑。
        percentage = _int_of(body.get("Percentage"))
        if percentage is None or percentage < 100:
            running = True
            stages.append("主动扫描")
        alerts = max(alerts, _int_of(body.get("Number of alerts")))
        requests = max(requests, _int_of(body.get("Number of requests")))
        pages = max(pages, _int_of(body.get("Number of processed URLs")))
        if percentage is not None:
            percentages.append(percentage)

    # 被动扫描
    try:
        pscan = pscan_progress(state, )
        if pscan.running:
            running = True
            stages.append("被动扫描")
        alerts = max(alerts, pscan.alerts)
        requests = max(requests, pscan.requests)
        pages = max(pages, pscan.pages)
        urls = max(urls, pscan.urls)
    except ZAPConnectorError:
        pass

    # 百分比只在 ZAP 明确给出时才填；爬取阶段一律不虚构。
    percentage: int | None = None
    if percentages:
        percentage = int(round(sum(percentages) / len(percentages)))

    return ZAPProgress(
        running=running,
        percentage=percentage,
        stage=" / ".join(stages) if stages else "完成",
        pages=pages,
        requests=requests,
        alerts=alerts,
    )


def stop_scan(state: ZAPProtocolState, scan_ids: Iterable[str]=()) -> None:
    """停止所有运行中的扫描。逐条调用，任一失败不影响其余。"""
    ids = [str(s).strip() for s in scan_ids if str(s).strip()] or list(state.scan_ids)
    stopped: list[str] = []
    for scan_id in ids:
        try:
            call(state, "POST", "/JSON/ascan/stopScan", timeout_seconds=10.0)
            stopped.append(f"ascan:{scan_id}")
        except ZAPConnectorError:
            continue
    for path, label in (
        ("/JSON/spider/stopSpider", "spider"),
        ("/JSON/clientspider/stopClientSpider", "clientspider"),
    ):
        try:
            call(state, "POST", path, timeout_seconds=10.0)
            stopped.append(label)
        except ZAPConnectorError:
            continue
    state.scan_ids = []


def pscan_progress(state: ZAPProtocolState) -> ZAPProgress:
    """读被动扫描进度。"""
    body = call(state, "POST", "/JSON/pscan/progress", timeout_seconds=15.0)
    if not isinstance(body, dict):
        return ZAPProgress(running=False)
    return ZAPProgress(
        running=_as_bool(body.get("Running")) or _int_of(body.get("QueueSize")) > 0,
        percentage=None,
        stage="被动扫描",
        pages=_int_of(body.get("ScannedCount")) or 0,
        requests=_int_of(body.get("QueuedUrls")) or 0,
        alerts=_int_of(body.get("Alerts")) or 0,
        urls=len(body.get("ScannedUrls") or []),
    )
