"""平台内置扫描策略（§十六）。

迁移 0013 调用 ``ensure_builtin_profiles`` 幂等补齐 6 个内置策略；
它们 ``project_id`` 为空、``is_builtin=True``、``code`` 非空，对所有项目共享可见。
项目内禁止修改与删除（service 层强制，见 profile_service.update / delete）：
改内置等于改全平台默认强度，项目级调整要复制成自定义策略；
只有平台管理员能改全局内置策略，且改完影响所有项目。

设计口径（§十六、§十五）：
- 默认全部**被动**策略；两个主动策略是「低强度」配置，仍受 connector 侧硬上限约束。
- 主动策略 ``active_enabled=True`` 只是「该策略具备主动扫描能力」，是否真的执行
  还要过 scope_guard.assert_active_scan_authorized（环境开关 + 显式批准 + 非生产）。
- 内置策略的 selected_rule_ids 为空，表示沿用 ZAP 策略默认规则集；不在此处
  预置「全部规则」，避免默认启用高强度规则（§十五）。
"""

from __future__ import annotations

import sqlalchemy as sa

from app.features.security_testing.zap.contracts import (
    SCAN_MODE_API_ACTIVE,
    SCAN_MODE_API_PASSIVE,
    SCAN_MODE_WEB_PASSIVE,
    SCAN_MODE_WEB_ACTIVE,
)
from app.features.security_testing.zap.scope_guard import HIGH_RISK_ACTIVE_PATH_PATTERNS

#: (code, name, scan_mode, spider, client_spider, passive, active, max_duration,
#:  max_depth, max_concurrency, request_delay, max_alerts_per_rule, max_request_budget,
#:  active_enabled, description)
BUILTIN_PROFILES: tuple[tuple, ...] = (
    (
        "API_PASSIVE_BASIC",
        "API 被动扫描（基础）",
        SCAN_MODE_API_PASSIVE,
        True, False, True, False,
        15, 3, 2, 500, 20, 2000, False,
        "只导入 OpenAPI 并用被动扫描规则分析请求/响应，不发送额外探测请求",
    ),
    (
        "WEB_PASSIVE_BASIC",
        "Web 被动扫描（基础）",
        SCAN_MODE_WEB_PASSIVE,
        True, True, True, False,
        20, 4, 2, 500, 20, 3000, False,
        "Client Spider 真实浏览器渲染爬取页面，再用被动扫描规则分析",
    ),
    (
        "AUTHENTICATED_API_PASSIVE",
        "API 鉴权被动扫描",
        SCAN_MODE_API_PASSIVE,
        True, False, True, False,
        15, 3, 2, 500, 20, 2000, False,
        "API 鉴权（Bearer / Header）+ 被动扫描；扫描前必须通过登录态验证接口",
    ),
    (
        "AUTHENTICATED_WEB_PASSIVE",
        "Web 鉴权被动扫描",
        SCAN_MODE_WEB_PASSIVE,
        True, True, True, False,
        20, 4, 2, 500, 20, 3000, False,
        "浏览器登录态爬取登录后页面 + 被动扫描；只配 Authorization 头不算已登录",
    ),
    (
        "API_ACTIVE_LOW_RISK",
        "API 主动扫描（低强度）",
        SCAN_MODE_API_ACTIVE,
        True, False, True, True,
        30, 3, 4, 800, 10, 5000, True,
        "低强度主动扫描：默认排除危险路径，单规则告警上限 10，并发不超过 4",
    ),
    (
        "WEB_ACTIVE_LOW_RISK",
        "Web 主动扫描（低强度）",
        SCAN_MODE_WEB_ACTIVE,
        True, True, True, True,
        30, 4, 4, 800, 10, 5000, True,
        "低强度主动扫描：默认排除危险路径，需人工批准且非生产环境",
    ),
)


# 内置主动策略统一排除的危险路径（§十五：仅作候选，不能仅凭路径字符串认定安全）。
# 存的是路径原文，转义与正则组装在 scope_guard.compile_path_regex 里做。
_BUILTIN_ACTIVE_EXCLUDES: list[str] = list(HIGH_RISK_ACTIVE_PATH_PATTERNS)

_INSERT_PROFILE = sa.text(
    "INSERT INTO security_scan_profile "
    "(project_id, code, is_builtin, name, scan_mode, spider_enabled, client_spider_enabled, "
    "passive_enabled, active_enabled, max_duration, max_depth, max_concurrency, request_delay, "
    "max_alerts_per_rule, max_request_budget, exclude_paths, enabled, description) "
    "VALUES (NULL, :code, true, :name, :scan_mode, :spider, :client_spider, :passive, "
    ":active, :max_duration, :max_depth, :max_concurrency, :request_delay, "
    ":max_alerts_per_rule, :max_request_budget, :exclude_paths, true, :description)"
).bindparams(sa.bindparam("exclude_paths", type_=sa.JSON()))


def ensure_builtin_profiles(conn) -> int:
    """幂等补齐平台内置扫描策略，返回本次新插入的条数。

    按 ``code`` 跳过：迁移链被重复重放时不会重复插入，也不会留下半套模板。
    """
    existing_codes = {
        row[0]
        for row in conn.execute(
            sa.text("SELECT code FROM security_scan_profile WHERE project_id IS NULL")
        ).fetchall()
    }

    inserted = 0
    for (
        code, name, scan_mode, spider, client_spider, passive, active,
        max_duration, max_depth, max_concurrency, request_delay,
        max_alerts_per_rule, max_request_budget, active_enabled, description,
    ) in BUILTIN_PROFILES:
        if code in existing_codes:
            continue
        exclude_paths = _BUILTIN_ACTIVE_EXCLUDES if active_enabled else []
        conn.execute(
            _INSERT_PROFILE,
            {
                "code": code,
                "name": name,
                "scan_mode": scan_mode,
                "spider": spider,
                "client_spider": client_spider,
                "passive": passive,
                "active": active,
                "max_duration": max_duration,
                "max_depth": max_depth,
                "max_concurrency": max_concurrency,
                "request_delay": request_delay,
                "max_alerts_per_rule": max_alerts_per_rule,
                "max_request_budget": max_request_budget,
                "exclude_paths": exclude_paths,
                "description": description,
            },
        )
        inserted += 1

    # 不主动 commit：alembic 迁移在自己的事务边界里提交。
    return inserted


#: 内置策略代号清单（供 service 层与前端判断「是否内置策略」）。
BUILTIN_PROFILE_CODES: tuple[str, ...] = tuple(item[0] for item in BUILTIN_PROFILES)
