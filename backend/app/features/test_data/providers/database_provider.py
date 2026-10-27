"""DATABASE_INSERT / DATABASE_PATCH Provider（§9.6 / §10）。

执行边界，按 §10.1-§10.3 全部生效：

1. 连接必须来自 ``target_database_connection``，且 ``environment_id`` 等于本次运行环境，
   否则 ``DATABASE_ENVIRONMENT_FORBIDDEN``——绝不能用平台库 DATABASE_URL 当目标库。
2. PRODUCTION 无条件拒绝（``db_guard.assert_database_allowed``）。
3. 策略不存在 / 未开启 → 拒绝（DEV/TEST 也要策略行，不做「开发环境默许所有表」）。
4. 表精确匹配白名单 → 否则 ``DATABASE_TABLE_NOT_ALLOWED``。
5. 操作白名单 → 否则 ``DATABASE_OPERATION_FORBIDDEN``；DELETE 需三重确认。
6. 值走 psycopg 占位符，表名列名走 ``psycopg.sql.Identifier`` 并过标识符校验。

用**短连接**执行，执行完立即关闭；平台库的 ``Session`` 从不执行这里拼出的语句。
不在这里产出 DELETE 类 cleanup 句柄（第一阶段不提供 DELETE 功能，清理请用显式
CLEANUP 步骤的 DATABASE_PATCH 步骤表达）。
"""

from __future__ import annotations

import time

from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.test_data.models.connection import DatabaseAccessPolicy, TargetDatabaseConnection
from app.features.test_data.providers.base import BaseProvider, ProviderContext, ProviderResult, config_of
from app.features.test_data.security import db_guard, sql_builder
from app.shared.crypto import decrypt_secret
from app.shared.errors import (
    CODE_DATABASE_CONNECTION_FAILED,
    CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
    CODE_FIXTURE_INVALID,
    CODE_PROVIDER_NOT_FOUND,
    AppError,
)

#: 目标库连接与执行超时（秒）。
CONNECT_TIMEOUT_SECONDS = 5
EXECUTE_TIMEOUT_SECONDS = 15

_MASKER = SensitiveDataMasker()


class DatabaseProvider(BaseProvider):
    """DATABASE_INSERT 与 DATABASE_PATCH 共用一个实现，按 operation 分派。"""

    provider_type = "DATABASE_INSERT"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        """运行对应数据。"""
        from app.features.test_data.schemas import DatabaseProviderConfig

        cfg = self.load_config(config_of(ctx), DatabaseProviderConfig)

        # 防御性复检：schema 层 extra=forbid 已挡 422，这里再拦一次配置字面量。
        db_guard.validate_config_no_sql(config_of(ctx))

        connection = self._load_connection(ctx.db, cfg.connection_id, ctx.project_id)
        self._assert_environment_matches(connection, ctx)
        policy = self._load_policy(ctx.db, ctx.project_id, connection.environment_id)

        env_class = db_guard.assert_database_allowed(ctx.environment, policy)
        table = db_guard.check_table_allowed(policy, cfg.table)
        operation = db_guard.check_operation_allowed(
            policy,
            cfg.operation,
            allow_delete=bool(cfg.allow_delete),
            risk_level=getattr(ctx.provider, "risk_level", None),
        )

        built = sql_builder.build(
            operation,
            table=table,
            columns=list(cfg.columns or []),
            values=dict(cfg.values or {}),
            where=dict(cfg.where or {}),
            limit=cfg.limit,
        )

        # where 里的模板（如 {"id": "${task_id}"}）先求值成实际值。
        params = self._resolve_values(built.params, ctx)

        request_snapshot = {
            "operation": operation,
            "table": table,
            "environment_class": env_class,
            "params": _MASKER.mask_body([str(p) if not isinstance(p, (dict, list)) else p for p in params]),
        }

        outputs, response_snapshot = self._execute(ctx, connection, built, params)
        return ProviderResult.ok(
            outputs,
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
        )

    # ---------------------------------------------------------------- 连接与策略

    @staticmethod
    def _load_connection(db, connection_id: int, project_id: int) -> TargetDatabaseConnection:
        """取连接行：跨项目引用对调用方隐藏（返回 PROVIDER_NOT_FOUND，不暴露存在性）。"""
        row = db.get(TargetDatabaseConnection, connection_id)
        if row is None or row.project_id != project_id:
            raise AppError(
                f"目标库连接 {connection_id} 不存在",
                status_code=404,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        if not row.enabled:
            raise AppError(
                "目标库连接已停用",
                status_code=400,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        return row

    @staticmethod
    def _assert_environment_matches(connection: TargetDatabaseConnection, ctx: ProviderContext) -> None:
        """连接绑定的环境必须等于本次运行环境，否则打到别的环境去了。"""
        if connection.environment_id != ctx.environment.id:
            raise AppError(
                f"目标库连接绑定环境 {connection.environment_id} 与本次运行环境 "
                f"{ctx.environment.id} 不一致",
                status_code=400,
                code=CODE_DATABASE_ENVIRONMENT_FORBIDDEN,
            )

    @staticmethod
    def _load_policy(db, project_id: int, environment_id: int) -> DatabaseAccessPolicy | None:
        """加载策略。"""
        return db.query(DatabaseAccessPolicy).filter(
            DatabaseAccessPolicy.project_id == project_id,
            DatabaseAccessPolicy.environment_id == environment_id,
        ).first()

    # ---------------------------------------------------------------- 执行

    @staticmethod
    def _resolve_values(params: list, ctx: ProviderContext) -> list:
        """把参数里的模板求值成实际值（值全部走占位符，不做字符串拼接）。"""
        from app.features.test_data.runtime.variable_resolver import resolve_token_str

        resolved = []
        for p in params:
            if isinstance(p, str) and "${" in p:
                resolved.append(resolve_token_str(p, ctx.scope, required=True))
            else:
                resolved.append(p)
        return resolved

    @staticmethod
    def _execute(ctx: ProviderContext, connection: TargetDatabaseConnection, built: sql_builder.BuiltQuery, params: list):
        """短连接执行拼装好的语句，返回 (outputs, response_snapshot)。"""
        import psycopg
        from psycopg import OperationalError, ProgrammingError

        password = decrypt_secret(connection.password_encrypted)
        started = time.perf_counter()
        try:
            with psycopg.connect(
                host=connection.host,
                port=connection.port,
                dbname=connection.database_name,
                user=connection.username,
                password=password or None,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
            ) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    if connection.schema_name:
                        # schema 用 Identifier 插值，避免拼接注入。
                        from psycopg import sql as _sql

                        cur.execute(
                            _sql.SQL("SET search_path TO {}").format(_sql.Identifier(connection.schema_name.strip()))
                        )
                    cur.execute(built.statement, params)
                    if built.operation == "INSERT":
                        row = cur.fetchone() if built.returning_id else None
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        outputs = {"inserted_id": row[0] if row and row[0] is not None else None}
                        return outputs, {
                            "rows_affected": cur.rowcount,
                            "duration_ms": elapsed_ms,
                        }
                    if built.operation == "SELECT":
                        rows = cur.fetchall()
                        columns = built.select_columns
                        records = [{col: value for col, value in zip(columns, record)} for record in rows]
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        return records, {
                            "row_count": len(records),
                            "duration_ms": elapsed_ms,
                        }
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    outputs = {"affected_rows": int(cur.rowcount or 0)}
                    return outputs, {
                        "rows_affected": outputs["affected_rows"],
                        "duration_ms": elapsed_ms,
                    }
        except OperationalError as exc:
            raise AppError(
                f"目标库连接失败：{str(exc)[:300]}",
                status_code=400,
                code=CODE_DATABASE_CONNECTION_FAILED,
            ) from exc
        except ProgrammingError as exc:
            raise AppError(
                f"目标库执行失败：{str(exc)[:300]}",
                status_code=400,
                code=CODE_FIXTURE_INVALID,
            ) from exc
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                f"目标库执行失败：{str(exc)[:300]}",
                status_code=400,
                code=CODE_DATABASE_CONNECTION_FAILED,
            ) from exc


__all__ = ["DatabaseProvider"]
