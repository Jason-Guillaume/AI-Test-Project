"""数据库安全边界：环境归类、标识符校验、表白名单、操作白名单。

这是纯校验层，不做 I/O（sql_builder 负责拼语句，database_provider 负责短连接执行）。

关键约定（§10）：
- 环境归类用 **整词相等**，不用子串（`latest` 不能因为含 "test" 被当成测试环境）；
  未知 name 一律按 STAGING，默认关闭。
- PRODUCTION 无条件拒绝，不读策略开关。
- DEV / TEST 也要求存在策略行：没有策略 = 拒绝，不做「开发环境默许所有表」。
- 表名精确匹配白名单，不支持通配符与 schema 前缀通配。
- DELETE 需要三重同时成立：策略白名单含 DELETE、provider config.allow_delete=true、
  risk_level=CRITICAL。第一阶段 UI 不提供 DELETE 表单项。
- 配置里出现 `sql` 字符串字段直接拒绝（Schema 已 extra=forbid，这里再拦一道）。
"""

from __future__ import annotations

import re

from app.features.test_data.models.connection import DatabaseAccessPolicy
from app.features.test_data.schemas import DB_OPERATIONS, RISK_LEVELS
from app.models.configuration import Environment
from app.shared.errors import (
    CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
    CODE_DATABASE_OPERATION_FORBIDDEN,
    CODE_DATABASE_TABLE_NOT_ALLOWED,
    AppError,
)

# 环境 name 整词相等映射（大小写不敏感）。
_DEV_NAMES = frozenset({"dev", "development"})
_TEST_NAMES = frozenset({"test", "testing"})
_STAGING_NAMES = frozenset({"staging", "stage", "uat", "pre", "preprod", "pre-production"})
_PRODUCTION_NAMES = frozenset({"production", "prod", "live"})

# 标识符：字母或下划线开头，最多 63 字符。禁止分号、注释、UNION、子查询——
# 不合法直接拒绝，不尝试修复。
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

# SELECT 禁止回读的敏感列名（写入允许，快照里由 Masker 处理）。
SENSITIVE_COLUMN_HINTS = (
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "private_key", "credential", "authorization", "access_key", "auth_token",
)

# 禁止出现在 Provider 配置顶层的键（extra=forbid 已挡 422，这里是防御性复检）。
FORBIDDEN_CONFIG_KEYS = frozenset({"sql", "query", "raw_sql", "statement"})


def classify(environment_name: str | None) -> str:
    """按 Environment.name 整词相等归类；未知一律 STAGING（默认关闭）。"""
    name = (environment_name or "").strip().lower()
    if name in _PRODUCTION_NAMES:
        return "PRODUCTION"
    if name in _DEV_NAMES:
        return "DEV"
    if name in _TEST_NAMES:
        return "TEST"
    if name in _STAGING_NAMES:
        return "STAGING"
    # 未知环境按 STAGING 处理：默认关闭，必须显式开策略。
    return "STAGING"


def environment_class(environment: Environment) -> str:
    """归类一个 Environment 实体。"""
    return classify(environment.name)


def validate_identifier(value: str | None, *, field: str) -> str:
    """校验表名 / 列名 / schema 名等标识符，非法直接拒绝（不尝试修复）。"""
    text = (value or "").strip()
    if not IDENTIFIER_PATTERN.fullmatch(text):
        raise AppError(
            f"{field} 标识符不合法：{text!r}（只允许字母/数字/下划线，且以字母或下划线开头）",
            status_code=400,
            code=CODE_DATABASE_TABLE_NOT_ALLOWED,
        )
    return text


def validate_config_no_sql(config: dict | None, *, what: str = "Provider 配置") -> None:
    """拒绝配置里出现 sql / raw_sql / statement 等字符串字段。"""
    if not config:
        return
    for key in FORBIDDEN_CONFIG_KEYS:
        if key in config:
            raise AppError(
                f"{what} 不允许包含 {key} 字段：数据库操作必须是结构化配置",
                status_code=400,
                code=CODE_DATABASE_OPERATION_FORBIDDEN,
            )


def _normalize_policy(policy: DatabaseAccessPolicy | None) -> tuple[list[str], list[str], bool]:
    """把策略行归一成 (enabled, allowed_tables, allowed_operations)。"""
    if policy is None:
        return False, [], []
    tables = policy.allowed_tables or []
    operations = policy.allowed_operations or []
    return bool(policy.enabled), [str(t) for t in tables], [str(o).upper() for o in operations]


def assert_database_allowed(
    environment: Environment,
    policy: DatabaseAccessPolicy | None,
) -> str:
    """执行前检查环境是否允许数据库造数，返回归类结果。

    1. PRODUCTION：无条件拒绝，不读策略开关
    2. 策略不存在或 enabled=false：拒绝
    """
    env_class = classify(environment.name)
    if env_class == "PRODUCTION":
        raise AppError(
            "生产环境禁止数据库造数操作",
            status_code=400,
            code=CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
        )
    enabled, _tables, _ops = _normalize_policy(policy)
    if not enabled:
        raise AppError(
            f"环境 {environment.name}（{env_class}）未开启数据库造数策略",
            status_code=400,
            code=CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
        )
    return env_class


def check_table_allowed(policy: DatabaseAccessPolicy | None, table: str) -> str:
    """表白名单精确匹配：不支持通配符与 schema 前缀。"""
    table = validate_identifier(table, field="table")
    _enabled, allowed_tables, _ops = _normalize_policy(policy)
    allowed = {str(t).strip() for t in allowed_tables}
    if table not in allowed:
        raise AppError(
            f"表 {table} 不在白名单内：{', '.join(sorted(allowed)) or '（空）'}",
            status_code=400,
            code=CODE_DATABASE_TABLE_NOT_ALLOWED,
        )
    return table


def check_operation_allowed(
    policy: DatabaseAccessPolicy | None,
    operation: str,
    *,
    allow_delete: bool = False,
    risk_level: str | None = None,
) -> str:
    """操作白名单校验；DELETE 需要三重同时成立。"""
    op = (operation or "").strip().upper()
    if op not in DB_OPERATIONS:
        raise AppError(
            f"不支持的数据库操作：{operation!r}（只支持 INSERT/UPDATE/SELECT/DELETE）",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    _enabled, _tables, allowed_operations = _normalize_policy(policy)
    if op not in allowed_operations:
        raise AppError(
            f"操作 {op} 不在策略白名单内：{', '.join(allowed_operations) or '（空）'}",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    if op == "DELETE":
        # 三重确认：策略含 DELETE + config.allow_delete + risk_level=CRITICAL。
        if not allow_delete:
            raise AppError(
                "DELETE 需要在 Provider 配置中显式 allow_delete=true",
                status_code=400,
                code=CODE_DATABASE_OPERATION_FORBIDDEN,
            )
        if (risk_level or "").upper() not in RISK_LEVELS or (risk_level or "").upper() != "CRITICAL":
            raise AppError(
                "DELETE 需要 Provider 风险等级为 CRITICAL",
                status_code=400,
                code=CODE_DATABASE_OPERATION_FORBIDDEN,
            )
    return op


def check_sensitive_columns(columns: list[str]) -> None:
    """SELECT 回读列检查：禁止把 password/secret/token 等敏感列读进快照。"""
    sensitive = [c for c in (columns or []) if is_sensitive_column(c)]
    if sensitive:
        raise AppError(
            f"禁止 SELECT 回读敏感列：{', '.join(sensitive)}",
            status_code=400,
            code=CODE_DATABASE_TABLE_NOT_ALLOWED,
        )


def is_sensitive_column(column: str) -> bool:
    """判断列名是否敏感（SELECT 回读时禁止进快照）。"""
    lowered = (column or "").strip().lower()
    return any(hint in lowered for hint in SENSITIVE_COLUMN_HINTS)


def validate_allowed_tables(tables: list[str]) -> list[str]:
    """策略保存时校验表白名单元素合法（去重、保序、拒绝非法标识符）。"""
    seen: dict[str, str] = {}
    for raw in tables or []:
        table = validate_identifier(raw, field="table")
        seen.setdefault(table, raw)
    return list(seen)


def validate_allowed_operations(operations: list[str]) -> list[str]:
    """策略保存时校验操作白名单：只允许 INSERT/UPDATE/SELECT/DELETE。"""
    normalized: list[str] = []
    for raw in operations or []:
        op = (raw or "").strip().upper()
        if op not in DB_OPERATIONS:
            raise AppError(
                f"不支持的数据库操作：{raw!r}（只支持 INSERT/UPDATE/SELECT/DELETE）",
                status_code=400,
                code=CODE_DATABASE_OPERATION_FORBIDDEN,
            )
        if op not in normalized:
            normalized.append(op)
    if not normalized:
        raise AppError(
            "操作白名单不能为空",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    return normalized
