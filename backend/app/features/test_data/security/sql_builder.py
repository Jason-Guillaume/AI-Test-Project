"""结构化配置 → psycopg 参数化 SQL 的唯一拼装点（§10.1）。

设计原则：Provider 只提交结构化 JSON（table / operation / columns / values / where），
**禁止**配置里出现 ``sql`` 字符串。所有值走 psycopg 占位符 ``%s``，所有表名、列名、
schema 名走 ``psycopg.sql.Identifier`` 并由 ``db_guard.validate_identifier`` 先校验过。
不合法标识符直接拒绝，不尝试修复；不做分号 / 注释 / UNION / 子查询的任何解析，
因为这些形状压根无法从结构化配置里表达出来。

本模块只做拼装，不做 I/O、不做权限判断：
- 权限 / 白名单 / 环境归类 → ``security/db_guard.py``
- 短连接执行 → ``providers/database_provider.py``
平台库的 ``Session`` **绝不**执行这里拼出来的语句。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from psycopg import sql

from app.features.test_data.security.db_guard import (
    check_sensitive_columns,
    validate_identifier,
)
from app.shared.errors import (
    CODE_DATABASE_OPERATION_FORBIDDEN,
    CODE_DATABASE_TABLE_NOT_ALLOWED,
    AppError,
)

#: SELECT 缺省 limit（§10.1：默认 1，最大 20）。
DEFAULT_SELECT_LIMIT = 1
MAX_SELECT_LIMIT = 20


@dataclass
class BuiltQuery:
    """拼装结果：可直接交给 psycopg 连接执行。"""

    statement: sql.Composed
    params: list[Any] = field(default_factory=list)
    operation: str = ""
    table: str = ""
    #: INSERT 是否 RETURNING id（只有 id 在允许列里才为 True）。
    returning_id: bool = False
    #: SELECT 的列，调用方据此组装快照。
    select_columns: list[str] = field(default_factory=list)


def _ident(value: Any, *, what: str) -> sql.Identifier:
    """校验并安全引用 SQL 表名或列名。"""
    text = validate_identifier(value, field=what)
    return sql.Identifier(text)


def _placeholders(count: int) -> sql.Composed:
    """拼成 ``( %s, %s )`` 形式；INSERT 的 VALUES 需要括号。"""
    if count <= 0:
        return sql.SQL("()")
    return sql.SQL("({})").format(sql.SQL(", ").join([sql.SQL("%s")] * count))


def _where_clauses(where: dict[str, Any]) -> tuple[sql.Composed, list[Any]]:
    """把 ``{col: value}`` 拼成 ``col=%s AND col=%s``，键按名字排序保证确定性。"""
    if not where:
        return sql.SQL(""), []
    params: list[Any] = []
    parts: list[sql.Composed] = []
    for column in sorted(where.keys()):
        parts.append(sql.SQL("{} = %s").format(_ident(column, what="where 列名")))
        params.append(where[column])
    return sql.SQL(" AND ").join(parts), params


def build_insert(table: str, columns: list[str], values: dict[str, Any]) -> BuiltQuery:
    """``INSERT INTO t (c1,c2) VALUES (%s,%s) [RETURNING id]``。

    ``columns`` 与 ``values`` 的键必须完全一致；不一致视为配置错误。
    ``id`` 只有在允许列里才 RETURNING——不能凭空指定要取回一个配置没写的列。
    """
    table_text = validate_identifier(table, field="table")
    if not columns:
        raise AppError(
            "INSERT 需要 columns：明确列出写入的列",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    if not values:
        raise AppError(
            "INSERT 需要 values：写入的值不能为空",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )

    col_texts = [validate_identifier(c, field="列名") for c in columns]
    value_keys = [str(k) for k in values.keys()]
    if col_texts != value_keys:
        raise AppError(
            f"INSERT 的 columns 与 values 的键必须完全一致："
            f"columns={col_texts}，values={value_keys}",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )

    stmt = sql.SQL(
        "INSERT INTO {} ({}) VALUES {}"
    ).format(
        sql.Identifier(table_text),
        sql.SQL(", ").join(_ident(c, what="列名") for c in col_texts),
        _placeholders(len(col_texts)),
    )
    returning_id = "id" in col_texts
    if returning_id:
        stmt = stmt + sql.SQL(" RETURNING id")

    return BuiltQuery(
        statement=stmt,
        params=[values[c] for c in value_keys],
        operation="INSERT",
        table=table_text,
        returning_id=returning_id,
    )


def build_update(table: str, values: dict[str, Any], where: dict[str, Any]) -> BuiltQuery:
    """``UPDATE t SET c=%s, ... WHERE ...``，输出 affected_rows。"""
    table_text = validate_identifier(table, field="table")
    if not values:
        raise AppError(
            "UPDATE 需要 values：要写入的值不能为空",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    where_sql, where_params = _where_clauses(where or {})
    if not where_params:
        raise AppError(
            "UPDATE 必须带 where 条件，禁止无条件全表更新",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )

    parts: list[sql.Composed] = [
        sql.SQL("{} = %s").format(_ident(k, what="SET 列名")) for k in sorted(values.keys())
    ]
    stmt = sql.SQL("UPDATE {} SET {} WHERE {}").format(
        sql.Identifier(table_text),
        sql.SQL(", ").join(parts),
        where_sql,
    )
    return BuiltQuery(
        statement=stmt,
        params=[values[k] for k in sorted(values.keys())] + where_params,
        operation="UPDATE",
        table=table_text,
    )


def build_delete(table: str, where: dict[str, Any]) -> BuiltQuery:
    """``DELETE FROM t WHERE ...``，输出 affected_rows。"""
    table_text = validate_identifier(table, field="table")
    where_sql, where_params = _where_clauses(where or {})
    if not where_params:
        raise AppError(
            "DELETE 必须带 where 条件，禁止无条件全表删除",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    stmt = sql.SQL("DELETE FROM {} WHERE {}").format(
        sql.Identifier(table_text), where_sql
    )
    return BuiltQuery(statement=stmt, params=where_params, operation="DELETE", table=table_text)


def build_select(table: str, columns: list[str], where: dict[str, Any], limit: int | None) -> BuiltQuery:
    """``SELECT cols FROM t WHERE ... LIMIT n``。

    必须带 where，必须有 limit（默认 1，最大 20）；禁止回读 password/secret/token
    这类敏感列（写入允许，快照里才由 Masker 处理）。
    """
    table_text = validate_identifier(table, field="table")
    if not columns:
        raise AppError(
            "SELECT 需要 columns：明确列出要读的列",
            status_code=400,
            code=CODE_DATABASE_TABLE_NOT_ALLOWED,
        )
    col_texts = [validate_identifier(c, field="列名") for c in columns]
    check_sensitive_columns(col_texts)
    where_sql, where_params = _where_clauses(where or {})
    if not where_params:
        raise AppError(
            "SELECT 必须带 where 条件",
            status_code=400,
            code=CODE_DATABASE_TABLE_NOT_ALLOWED,
        )

    lim = DEFAULT_SELECT_LIMIT if limit is None else int(limit)
    if lim < 1 or lim > MAX_SELECT_LIMIT:
        raise AppError(
            f"SELECT 的 limit 必须在 1..{MAX_SELECT_LIMIT} 之间，收到 {limit}",
            status_code=400,
            code=CODE_DATABASE_TABLE_NOT_ALLOWED,
        )

    stmt = sql.SQL("SELECT {} FROM {} WHERE {} LIMIT %s").format(
        sql.SQL(", ").join(_ident(c, what="列名") for c in col_texts),
        sql.Identifier(table_text),
        where_sql,
    )
    return BuiltQuery(
        statement=stmt,
        params=where_params + [lim],
        operation="SELECT",
        table=table_text,
        select_columns=col_texts,
    )


_BUILDERS = {
    "INSERT": build_insert,
    "UPDATE": build_update,
    "DELETE": build_delete,
    "SELECT": build_select,
}


def build(
    operation: str,
    *,
    table: str,
    columns: list[str] | None = None,
    values: dict[str, Any] | None = None,
    where: dict[str, Any] | None = None,
    limit: int | None = None,
) -> BuiltQuery:
    """按操作类型分派。未知操作报 ``DATABASE_OPERATION_FORBIDDEN``。"""
    op = (operation or "").strip().upper()
    builder = _BUILDERS.get(op)
    if builder is None:
        raise AppError(
            f"不支持的数据库操作：{operation!r}",
            status_code=400,
            code=CODE_DATABASE_OPERATION_FORBIDDEN,
        )
    if op == "INSERT":
        return builder(table, list(columns or []), dict(values or {}))
    if op == "UPDATE":
        return builder(table, dict(values or {}), dict(where or {}))
    if op == "DELETE":
        return builder(table, dict(where or {}))
    return builder(table, list(columns or []), dict(where or {}), limit)


__all__ = [
    "BuiltQuery",
    "DEFAULT_SELECT_LIMIT",
    "MAX_SELECT_LIMIT",
    "build",
    "build_delete",
    "build_insert",
    "build_select",
    "build_update",
]
