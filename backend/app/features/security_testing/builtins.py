"""系统内置安全策略与变异规则（迁移 0011 末尾幂等插入）。

八套模板覆盖第一阶段的全部可执行类别：
认证、授权、IDOR、参数、Header、方法、重放、业务状态。

约定：
- 模板行 project_id 为空、scope=SYSTEM、builtin=true，禁止项目成员修改规则体。
- 预留攻击类（INJECTION / RATE_LIMIT / UPLOAD / SSRF）**不插入可执行规则**，
  只在 schemas.STRATEGY_CATEGORIES 里保留枚举位，执行时直接拒绝。
- PARAMETER_BASIC 的规则是「模板」：target_field 为空，表示执行前按 API Schema 展开，
  不在模板里写死具体字段名。
- 重复 upgrade 时按 strategy_key 跳过策略、按 (strategy_id, mutation_type, target_field)
  跳过规则，迁移可反复重放。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

# 策略配置字段：（strategy_key, name, category, description, risk_level, [rules]）。
# 规则字段以元组表示：name、mutation_type、target_location、target_field、mutation_config，
# 以及 expected_security_behavior、expected_status_codes、severity，
# 以及 enabled、confirmation_required、sort。
BUILTIN_STRATEGIES: tuple[tuple[str, str, str, str, str, list[tuple]], ...] = (
    (
        "AUTH_BASIC",
        "认证基础检查",
        "AUTHENTICATION",
        "去掉、置空、伪造与畸形化认证头，观察接口是否在缺少合法凭证时仍然放行。",
        "MEDIUM",
        [
            ("去掉 Token", "REMOVE_TOKEN", "HEADER", "Authorization", {},
             "EXPECTED_DENY", [401, 403], "HIGH", True, False, 10),
            ("空 Token", "EMPTY_TOKEN", "HEADER", "Authorization", {},
             "EXPECTED_DENY", [401, 403], "HIGH", True, False, 20),
            ("非法 Token", "INVALID_TOKEN", "HEADER", "Authorization", {},
             "EXPECTED_DENY", [401, 403], "HIGH", True, False, 30),
            ("畸形 Token", "MALFORMED_TOKEN", "HEADER", "Authorization", {},
             "EXPECTED_DENY", [401, 403], "HIGH", True, False, 40),
            ("错误认证方案", "WRONG_AUTH_SCHEME", "HEADER", "Authorization", {},
             "EXPECTED_DENY", [401, 403], "MEDIUM", True, False, 50),
            # 过期 Token 只有在测试人员事先准备好 Fixture 输出时才执行，禁止伪造 JWT。
            (
                "过期 Token", "EXPIRED_TOKEN", "HEADER", "Authorization",
                {"token_source": {"fixture_key": "EXPIRED_TOKEN", "output": "token"}},
                "EXPECTED_DENY", [401, 403], "MEDIUM", True, False, 60,
            ),
        ],
    ),
    (
        "AUTHORIZATION_BASIC",
        "越权基础检查",
        "AUTHORIZATION",
        "换用户、换被测业务项目，验证接口是否按主体校验权限。",
        "HIGH",
        [
            (
                "换用户", "CROSS_USER", "HEADER", "Authorization",
                {
                    "token_source": {"fixture_key": "USER_B", "output": "token"},
                    "resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
                    "candidates": [
                        {"fixture_key": "USER_B", "output": "token"},
                        {"fixture_key": "TASK_B", "output": "task_id"},
                    ],
                },
                "EXPECTED_DENY", [403, 404], "CRITICAL", True, False, 10,
            ),
            (
                "换被测项目", "CROSS_PROJECT", "BODY", "project_id",
                {"resource_source": {"fixture_key": "PROJECT_B", "output": "project_id"},
                 "location": "BODY", "field": "project_id"},
                "EXPECTED_DENY", [403, 404], "HIGH", True, False, 20,
            ),
        ],
    ),
    (
        "IDOR_BASIC",
        "水平越权检查（IDOR）",
        "IDOR",
        "用另一份资源的 ID 直接访问，验证接口是否校验资源归属。候选只来自 Fixture 输出。",
        "HIGH",
        [
            (
                "换资源所有者", "IDOR", "PATH", "task_id",
                {"resource_source": {"fixture_key": "TASK_B", "output": "task_id"},
                 "location": "PATH", "field": "task_id"},
                "EXPECTED_DENY", [403, 404], "CRITICAL", True, False, 10,
            ),
        ],
    ),
    (
        "PARAMETER_BASIC",
        "参数校验检查",
        "PARAMETER",
        "按 API Schema 生成缺失、空值、类型错误、边界与非法枚举值。"
        "没有 Schema 的字段不自动乱改；target_field 为空表示执行前按 Schema 展开。",
        "LOW",
        [
            ("删除必填字段", "REMOVE_FIELD", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "MEDIUM", True, False, 10),
            ("空值", "NULL_VALUE", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "MEDIUM", True, False, 20),
            ("空字符串", "EMPTY_STRING", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 30),
            ("类型错误", "TYPE_MUTATION", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "MEDIUM", True, False, 40),
            ("零值", "ZERO", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 50),
            ("负数", "NEGATIVE", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 60),
            ("超出上限", "OVER_MAX", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 70),
            ("低于下限", "UNDER_MIN", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 80),
            ("非法枚举", "INVALID_ENUM", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 90),
            ("非法格式", "INVALID_FORMAT", "BODY", None, {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 100),
        ],
    ),
    (
        "HEADER_BASIC",
        "请求头检查",
        "HEADER",
        "删除、置空与非法化请求头，以及 Content-Type 与认证头的篡改。",
        "LOW",
        [
            ("删除请求头", "REMOVE_HEADER", "HEADER", "Content-Type", {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "MEDIUM", True, False, 10),
            ("空请求头", "EMPTY_HEADER", "HEADER", "Content-Type", {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 20),
            ("非法请求头值", "INVALID_HEADER_VALUE", "HEADER", "Content-Type", {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "LOW", True, False, 30),
            ("Content-Type 篡改", "CONTENT_TYPE_MUTATION", "HEADER", "Content-Type", {},
             "EXPECTED_VALIDATION_ERROR", [400, 422], "MEDIUM", True, False, 40),
        ],
    ),
    (
        "METHOD_BASIC",
        "未声明方法检查",
        "METHOD",
        "只测试策略允许且接口未登记的方法，不把所有方法都打一遍。"
        "DELETE 只有规则标记高风险确认才进入计划。",
        "MEDIUM",
        [
            (
                "未声明方法", "METHOD_MUTATION", "METHOD", None,
                {"methods": []},
                "EXPECTED_DENY", [405, 403, 404], "MEDIUM", True, False, 10,
            ),
        ],
    ),
    (
        "REPLAY_BASIC",
        "重放检查",
        "REPLAY",
        "同一请求重复 2 或 3 次，检查是否产生新的业务结果。"
        "系统不保证清掉重放多出来的业务数据，默认高风险需确认。",
        "HIGH",
        [
            (
                "重复发送", "REPLAY_SAME_REQUEST", "REQUEST", None,
                {"replay_count": 2, "replay_interval_ms": 0},
                "EXPECTED_IDEMPOTENT", [200, 409], "HIGH", True, True, 10,
            ),
        ],
    ),
    (
        "BUSINESS_STATE_BASIC",
        "业务状态绕过检查",
        "BUSINESS_STATE",
        "用业务配置里的终态数据再次调用该动作。终态 Fixture 由 mutation_config 点名，"
        "不存在时计划项标记 SECURITY_FIXTURE_REQUIRED，不硬跑。",
        "HIGH",
        [
            (
                "终态重复执行", "BUSINESS_STATE", "PATH", "task_id",
                {"state_entity": "task", "fixture_key": "SUCCESS_TASK",
                 "output": "task_id", "location": "PATH", "field": "task_id"},
                "EXPECTED_DENY", [409, 400, 403, 404], "HIGH", True, True, 10,
            ),
        ],
    ),
)

_INSERT_STRATEGY = sa.text(
    "INSERT INTO security_strategy "
    "(project_id, scope, name, strategy_key, category, description, enabled, risk_level, builtin) "
    "VALUES (NULL, :scope, :name, :strategy_key, :category, :description, :enabled, "
    ":risk_level, :builtin)"
)

_INSERT_RULE = sa.text(
    "INSERT INTO security_mutation_rule "
    "(project_id, strategy_id, name, mutation_type, target_location, target_field, operator, "
    "mutation_config, expected_security_behavior, expected_status_codes, severity, enabled, "
    "confirmation_required, sort) "
    "VALUES (NULL, :strategy_id, :name, :mutation_type, :target_location, :target_field, "
    ":operator, :mutation_config, :expected_security_behavior, :expected_status_codes, "
    ":severity, :enabled, :confirmation_required, :sort)"
).bindparams(
    sa.bindparam("mutation_config", type_=sa.JSON()),
    sa.bindparam("expected_status_codes", type_=sa.JSON()),
)


def ensure_builtin_strategies(conn) -> int:
    """幂等补齐系统内置策略与规则，返回本次新插入的策略条数。

    策略按 strategy_key 跳过，规则按 (strategy_id, mutation_type, target_field) 跳过，
    因此迁移链被重复重放时不会重复插入，也不会因为中途失败留下半套模板。
    """
    existing_keys = {
        row[0]
        for row in conn.execute(
            sa.text("SELECT strategy_key FROM security_strategy WHERE project_id IS NULL")
        ).fetchall()
    }

    inserted = 0
    for key, name, category, description, risk_level, rules in BUILTIN_STRATEGIES:
        if key in existing_keys:
            row = conn.execute(
                sa.text(
                    "SELECT id FROM security_strategy "
                    "WHERE project_id IS NULL AND strategy_key = :key"
                ),
                {"key": key},
            ).first()
            strategy_id = row[0] if row else None
        else:
            conn.execute(
                _INSERT_STRATEGY,
                {
                    "scope": "SYSTEM",
                    "name": name,
                    "strategy_key": key,
                    "category": category,
                    "description": description,
                    "enabled": True,
                    "risk_level": risk_level,
                    "builtin": True,
                },
            )
            row = conn.execute(
                sa.text(
                    "SELECT id FROM security_strategy "
                    "WHERE project_id IS NULL AND strategy_key = :key"
                ),
                {"key": key},
            ).first()
            strategy_id = row[0]
            inserted += 1

        if strategy_id is None:
            continue
        for (rule_name, mutation_type, location, field, config, behavior, codes,
             severity, enabled, confirmation, sort) in rules:
            hit = conn.execute(
                sa.text(
                    "SELECT id FROM security_mutation_rule "
                    "WHERE strategy_id = :sid AND mutation_type = :mt "
                    "AND target_field IS NOT DISTINCT FROM :field"
                ),
                {"sid": strategy_id, "mt": mutation_type, "field": field},
            ).first()
            if hit is not None:
                continue
            conn.execute(
                _INSERT_RULE,
                {
                    "strategy_id": strategy_id,
                    "name": rule_name,
                    "mutation_type": mutation_type,
                    "target_location": location,
                    "target_field": field,
                    "operator": mutation_type,
                    "mutation_config": config,
                    "expected_security_behavior": behavior,
                    "expected_status_codes": codes,
                    "severity": severity,
                    "enabled": enabled,
                    "confirmation_required": confirmation,
                    "sort": sort,
                },
            )
    return inserted
