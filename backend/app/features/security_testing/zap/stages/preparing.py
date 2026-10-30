"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.security_testing.zap import scope_guard
from app.features.security_testing.zap.connector import ZAP_REASON_PLUGIN_MISSING, ZAPConnectorError
from app.features.security_testing.zap.contracts import (
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STAGE,
    EVENT_TYPE_WARNING,
    JOB_STATUS_PREPARING,
    ZAPCapabilities,
    is_active_scan,
)
from app.features.security_testing.zap.openapi_export import (
    build_openapi_document,
    count_interfaces,
    render_openapi_json,
)
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.contracts import _host_pattern
from app.features.security_testing.zap.stages.control import checkpoint
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.control import fail
from app.features.security_testing.zap.stages.control import merged_paths
from app.features.security_testing.zap.stages.persistence import update_job


def stage_preparing(context: ScanStageContext, snap: ScanSnapshot, started: float) -> None:
    """PREPARING：连通性、能力检测、范围设置、Context 创建、OpenAPI 导入。"""
    checkpoint(context, snap, JOB_STATUS_PREPARING, "准备扫描上下文", progress=1)
    emit(context, snap, EVENT_TYPE_STAGE, JOB_STATUS_PREPARING, "开始准备扫描上下文")

    # 运行期再校验一次范围与授权：创建到执行之间配置可能已经变化（§三十四）。
    scope_guard.validate_target_url(snap.base_url, allowed_hosts=snap.allowed_hosts or None)
    scope_guard.assert_active_scan_authorized(
        environment_name=snap.environment_name,
        scan_mode=snap.scan_mode,
        active_authorized=snap.authorization_status == scope_guard.AUTHORIZATION_STATUS_AUTHORIZED,
        environment_active_allowed=snap.active_scan_allowed,
    )

    about = context.connector.check_health()
    capabilities = context.connector.get_capabilities()
    missing = [
        cap.name for cap in capabilities.capabilities
        if not cap.supported and cap.name in ("spider", "passive", "active", "history")
    ]
    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
        f"ZAP {about.version} 已连接，能力检测完成",
        {"zap_version": about.version, "add_on_count": len(capabilities.about.add_on_names),
         "missing_core_capabilities": missing},
    )
    if missing:
        fail(context, snap, "ZAP_PLUGIN_MISSING", f"ZAP 缺少必需插件：{', '.join(missing)}")

    host_pattern = _host_pattern(snap.base_url)
    context.connector.apply_scope(
        base_url=snap.base_url,
        allowed_hosts=snap.allowed_hosts,
        include_paths=merged_paths(snap.include_paths, snap.include_paths_profile),
        exclude_paths=merged_paths(snap.exclude_paths, snap.exclude_paths_profile),
    )
    context = context.connector.create_scan_context(host_pattern=host_pattern)
    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
        f"扫描上下文已创建：{context.host_pattern}",
    )

    # 接口契约导入：把平台 API 契约喂给 ZAP 的 OpenAPI Support，
    # 让 ZAP 按契约发起请求而不是只靠爬虫发现（Phase C）。
    import_openapi(context, snap, capabilities)

    # 默认低强度：只在主动扫描时收紧规则集与危险路径排除（§十五）。
    # 这里的值全部会被 connector 再截断到硬上限，策略里的数字不是可信输入。
    if snap.active_enabled and is_active_scan(snap.scan_mode):
        context.connector.set_active_scan_limits(
            max_duration=min(int(snap.max_duration or 20), 60),
            max_concurrency=min(int(snap.max_concurrency or 5), 20),
            request_delay_ms=snap.request_delay,
            max_alerts_per_rule=snap.max_alerts_per_rule or 20,
        )
        emit(context,
            snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
            "已按低强度参数收紧主动扫描限额",
            {"max_duration_minutes": min(int(snap.max_duration or 20), 60),
             "max_concurrency": min(int(snap.max_concurrency or 5), 20),
             "request_delay_ms": snap.request_delay},
        )
    update_job(context, snap, stage=JOB_STATUS_PREPARING)


def import_openapi(context: ScanStageContext, snap: ScanSnapshot, capabilities: ZAPCapabilities) -> None:
    """把项目接口契约导入 ZAP 的 OpenAPI Support（Phase C）。

    组件缺失时不失败：如实记录为功能限制并降级为爬虫发现，绝不伪造「已导入」
    （§三：实际 API 不支持时必须给出兼容实现或明确标记功能限制）。
    """
    if not any(
        cap.name == "openapi" and cap.supported for cap in capabilities.capabilities
    ):
        emit(context,
            snap, EVENT_TYPE_WARNING, JOB_STATUS_PREPARING,
            "ZAP 未启用 OpenAPI Support 组件，接口发现将依赖爬虫，覆盖面受限",
            {"limitation": "no_openapi_support"},
        )
        return

    with context.db_factory() as db:
        document = build_openapi_document(
            db,
            snap.project_id,
            base_url=snap.base_url,
            target_name=snap.target_name,
            environment_name=snap.environment_name,
        )
    total = count_interfaces(document)
    if total == 0:
        emit(context,
            snap, EVENT_TYPE_WARNING, JOB_STATUS_PREPARING,
            "项目接口契约为空，接口发现只能依赖爬虫",
            {"limitation": "no_api_contract"},
        )
        return

    try:
        result = context.connector.import_openapi(render_openapi_json(document))
    except ZAPConnectorError as exc:
        if exc.reason != ZAP_REASON_PLUGIN_MISSING:
            raise
        emit(context,
            snap, EVENT_TYPE_WARNING, JOB_STATUS_PREPARING,
            "ZAP 缺少 OpenAPI Support 组件，接口发现将依赖爬虫，覆盖面受限",
            {"limitation": "no_openapi_support", "interfaces": total},
        )
        return

    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PREPARING,
        f"已向 ZAP 导入 {total} 个接口定义",
        {"interfaces": total, "zap_response": result},
    )
