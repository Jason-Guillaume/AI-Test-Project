"""Cleanup 执行（§15）。

两类清理来源，按「后生成的先清理」执行：
1. Provider 主动声明的 ``cleanup_handle``（``output_snapshot["_cleanup"]`` 保留键）；
2. Fixture 显式的 ``phase=CLEANUP`` 步骤。

两条红线：
- **Cleanup 失败不得覆盖原错误码**。本模块只写 ``cleanup_*`` 三列，从不碰
  ``data_execution.status / error_code / error_message``——造数成功但清理失败
  的记录必须仍然显示 READY + 原来的错误信息。
- **尽力而为，不因一条失败停下**。某一条句柄失败要继续清理剩下的，最后汇总。

清理时的变量来源只有**已脱敏**的执行记录快照：敏感值已经是 ``******``，
所以 cleanup 的路径模板只应引用非敏感的输出（``task_id`` 之类），这也正是
``CleanupBinding`` 的约束。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.features.business.executors.api_executor import ApiRequestExecutor
from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import (
    DataExecution,
    FixtureExecution,
    ProviderExecution,
)
from app.features.test_data.models.fixture import Fixture, FixtureStep
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.providers import (
    CLEANUP_HANDLE_KEY,
    PROVIDER_REGISTRY,
    BaseProvider,
    ProviderContext,
    ProviderResult,
    provider_for_step_type,
    run_safe,
)
from app.features.test_data.runtime.variable_resolver import (
    ResolveScope,
    resolve_template,
    resolve_token_str,
)
from app.features.environment_configuration.services.environment_service import resolve_project_environment
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.errors import (
    CODE_CLEANUP_FAILED,
    CODE_DATA_EXECUTION_NOT_FOUND,
    CODE_FIXTURE_NOT_FOUND,
    AppError,
)

_EXECUTOR = ApiRequestExecutor()
_MASKER = SensitiveDataMasker()


class CleanupRunner:
    """按 data_execution 执行清理。无状态，进程级复用。"""

    def __init__(self, masker: SensitiveDataMasker | None = None) -> None:
        """初始化对象状态。"""
        self._masker = masker or _MASKER

    # ---------------------------------------------------------------- 入口

    def run_data_execution(
        self,
        db: Session,
        *,
        data_execution_id: int,
        actor: User,
    ) -> dict[str, Any]:
        """执行一次造数的全部清理，返回 ``{status, error_code, error_message}``。"""
        data_exec = db.get(DataExecution, data_execution_id)
        if data_exec is None:
            raise AppError(
                f"造数记录 {data_execution_id} 不存在",
                status_code=404,
                code="DATA_EXECUTION_NOT_FOUND",
            )

        project_id = data_exec.project_id
        try:
            environment = (
                resolve_project_environment(db, project_id, data_exec.environment_id)
                if data_exec.environment_id else None
            )
        except AppError:
            environment = None
        # 只有真正生成成功的 Fixture 才清理：生成失败时数据可能根本没落地。
        fx_execs = (
            db.query(FixtureExecution)
            .filter(
                FixtureExecution.data_execution_id == data_execution_id,
                FixtureExecution.status == "READY",
            )
            .order_by(FixtureExecution.id.asc())
            .all()
        )

        # 清理模板只能看到**已脱敏**的契约输出（快照里敏感值已是 ******）。
        outputs_by_key = self._outputs_by_key(fx_execs)

        # 后生成的先清理：按 fixture_execution 倒序，句柄与 CLEANUP 步骤也各自倒序。
        per_fixture: dict[int, list[str]] = {}
        for fx_exec in reversed(fx_execs):
            if environment is None:
                per_fixture[fx_exec.id] = ["没有可用的执行环境，跳过清理"]
                continue
            failures = []
            for handle in reversed(self._handles_for(db, fx_exec)):
                result = self._run_handle(
                    db, handle,
                    environment=environment, actor=actor, project_id=project_id,
                    outputs_by_key=outputs_by_key,
                )
                if not result.success:
                    failures.append(result.error_message or result.error_code or "清理失败")
            failures.extend(self._run_cleanup_steps(
                db, fx_exec, environment=environment, actor=actor, project_id=project_id,
                outputs_by_key=outputs_by_key,
            ))
            per_fixture[fx_exec.id] = failures

        all_failures = [message for failures in per_fixture.values() for message in failures]
        failed = bool(all_failures)

        # 只写 cleanup_* 三列，造数结果一个字节都不动。
        data_exec.cleanup_status = "FAILED" if failed else "SUCCESS"
        data_exec.cleanup_error_code = CODE_CLEANUP_FAILED if failed else None
        data_exec.cleanup_error_message = "; ".join(all_failures)[:2000] if failed else None
        for fx_exec in fx_execs:
            failures = per_fixture.get(fx_exec.id, [])
            fx_exec.cleanup_status = "FAILED" if failures else "SUCCESS"
            fx_exec.cleanup_error_code = CODE_CLEANUP_FAILED if failures else None
            fx_exec.cleanup_error_message = "; ".join(failures)[:2000] if failures else None

        db.commit()
        return {
            "status": "FAILED" if failed else "SUCCESS",
            "error_code": CODE_CLEANUP_FAILED if failed else None,
            "error_message": "; ".join(all_failures)[:2000] if failed else None,
        }

    def cleanup_fixture(
        self,
        db: Session,
        *,
        fixture_id: int,
        project_id: int,
        environment: Environment,
        actor: User,
    ) -> DataExecution:
        """手工清理一个 Fixture：跑它的 CLEANUP 步骤，写一条 MANUAL 记录。

        没有 CLEANUP 步骤时返回 SKIPPED，不算失败。
        """
        fixture = db.get(Fixture, fixture_id)
        if fixture is None or fixture.project_id != project_id:
            raise AppError(
                f"Fixture {fixture_id} 不存在",
                status_code=404,
                code=CODE_FIXTURE_NOT_FOUND,
            )

        data_exec = DataExecution(
            project_id=project_id,
            status="CLEANING",
            environment_id=environment.id,
            scope="MANUAL",
            started_at=datetime.now(),
            cleanup_status="PENDING",
        )
        db.add(data_exec)
        db.flush()

        steps = db.query(FixtureStep).filter(
            FixtureStep.fixture_id == fixture_id,
            FixtureStep.phase == "CLEANUP",
        ).order_by(FixtureStep.sort.desc(), FixtureStep.id.desc()).all()

        fx_exec = FixtureExecution(
            data_execution_id=data_exec.id,
            project_id=project_id,
            fixture_id=fixture.id,
            fixture_key=fixture.fixture_key,
            status="CLEANING",
            scope=fixture.scope,
            started_at=datetime.now(),
        )
        db.add(fx_exec)
        db.flush()

        failures: list[str] = []
        for step in steps:
            result = self._run_cleanup_step(
                db,
                step=step,
                owner_project_id=fixture.project_id,
                environment=environment,
                actor=actor,
                project_id=project_id,
                outputs_by_key={},
                data_execution=data_exec,
                fixture_execution=fx_exec,
            )
            if not result.success:
                failures.append(
                    f"步骤 {step.name}: {result.error_message or result.error_code}"
                )

        fx_exec.status = "FAILED" if failures else ("CLEANED" if steps else "SKIPPED")
        fx_exec.finished_at = datetime.now()
        data_exec.status = "FAILED" if failures else "CLEANED"
        data_exec.finished_at = datetime.now()
        data_exec.cleanup_status = "FAILED" if failures else "SUCCESS"
        data_exec.cleanup_error_code = CODE_CLEANUP_FAILED if failures else None
        data_exec.cleanup_error_message = "; ".join(failures)[:2000] if failures else None
        db.commit()
        return data_exec

    # ---------------------------------------------------------------- 句柄

    @staticmethod
    def _handles_for(db: Session, fx_exec: FixtureExecution) -> list[dict[str, Any]]:
        """取一个 Fixture 执行记录里的全部 cleanup 句柄，保持生成顺序。

        句柄挂在 ``provider_execution.output_snapshot[_cleanup]`` 上；调用方用
        ``reversed()`` 反转成「后生成的先清理」。
        """
        records = (
            db.query(ProviderExecution)
            .filter(ProviderExecution.fixture_execution_id == fx_exec.id)
            .order_by(ProviderExecution.id.asc())
            .all()
        )
        handles: list[dict[str, Any]] = []
        for rec in records:
            handle = (rec.output_snapshot or {}).get(CLEANUP_HANDLE_KEY)
            if isinstance(handle, dict) and handle:
                handles.append(handle)
        return handles

    @staticmethod
    def _outputs_by_key(fx_execs: list[FixtureExecution]) -> dict[str, dict[str, Any]]:
        """从本次造数的 READY 记录取脱敏后的契约输出（`fixture.<KEY>.<name>` 用）。"""
        outputs: dict[str, dict[str, Any]] = {}
        for fx_exec in fx_execs:
            snapshot = fx_exec.output_snapshot or {}
            outputs[fx_exec.fixture_key] = {
                k: v for k, v in snapshot.items() if k != CLEANUP_HANDLE_KEY
            }
        return outputs

    def _run_handle(
        self,
        db: Session,
        handle: dict[str, Any],
        *,
        environment: Environment,
        actor: User,
        project_id: int,
        outputs_by_key: dict[str, dict[str, Any]],
    ) -> ProviderResult:
        """运行处理。"""
        scope_vars = _scope_variables(outputs_by_key)
        kind = str(handle.get("type") or "").upper()
        if kind == "API":
            return self._run_api_handle(
                handle, db=db, environment=environment, project_id=project_id,
                scope_vars=scope_vars,
            )
        if kind == "POOL_LEASE":
            return self._run_lease_handle(handle, db=db, project_id=project_id)
        return ProviderResult.fail(
            CODE_CLEANUP_FAILED,
            f"未知的清理句柄类型：{kind or '空'}",
        )

    def _run_api_handle(
        self,
        handle: dict[str, Any],
        *,
        db: Session,
        environment: Environment,
        project_id: int,
        scope_vars: dict[str, Any],
    ) -> ProviderResult:
        """执行 API 清理句柄：路径与请求体里的模板再次解析，并过出站白名单。

        模板用 ``required=False``——清理是尽力而为，某个输出取不到不该把整条记录卡住；
        解析不到的占位符替换成空串，接口本身失败会在这里体现为 CLEANUP_FAILED。
        """
        path = str(handle.get("path") or "")
        method = str(handle.get("method") or "DELETE").upper()
        headers = dict(handle.get("headers") or {})
        body = handle.get("body") or {}

        scope = ResolveScope(variables=scope_vars, environment=environment)
        try:
            resolved_path = str(resolve_token_str(path, scope, required=False) or "")
            resolved_body = resolve_template(body, scope, required=False)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult.fail(CODE_CLEANUP_FAILED, f"清理模板解析失败：{exc}")
        if resolved_body is None:
            resolved_body = {}
        if not isinstance(resolved_body, (dict, list)):
            return ProviderResult.fail(
                CODE_CLEANUP_FAILED, f"清理请求体解析结果不是对象或数组：{type(resolved_body).__name__}",
            )

        url = _EXECUTOR.build_url(environment, resolved_path, {})
        started = time.perf_counter()
        result = _EXECUTOR.execute(
            db,
            method=method,
            url=url,
            project_id=project_id,
            headers=headers,
            json_body=resolved_body if resolved_body else None,
            timeout=30,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        request_snapshot = _MASKER.mask_request(
            method, url, headers, None, resolved_body or {}, "json",
        )
        response_snapshot = _MASKER.mask_response(
            result.status_code, result.response_headers,
            _try_parse_json(result.response_body),
        )
        if result.error_message:
            return ProviderResult.fail(
                CODE_CLEANUP_FAILED, result.error_message,
                request_snapshot=request_snapshot, response_snapshot=response_snapshot,
            )
        if not result.success:
            return ProviderResult.fail(
                CODE_CLEANUP_FAILED,
                f"清理接口 HTTP {result.status_code}（{elapsed_ms}ms）",
                request_snapshot=request_snapshot,
                response_snapshot=response_snapshot,
            )
        return ProviderResult.ok(
            {"http_status": result.status_code},
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
        )

    def _run_lease_handle(
        self,
        handle: dict[str, Any],
        *,
        db: Session,
        project_id: int,
    ) -> ProviderResult:
        """释放数据池租约。"""
        from app.features.test_data.models.pool import DataPoolLease
        from app.features.test_data.services.pool_service import PoolService

        item_id = handle.get("item_id")
        lease_id = handle.get("lease_id")
        if not item_id or not lease_id:
            return ProviderResult.fail(
                CODE_CLEANUP_FAILED, "POOL_LEASE 句柄缺少 item_id / lease_id",
            )
        lease = db.get(DataPoolLease, lease_id)
        if lease is None or lease.project_id != project_id:
            return ProviderResult.fail(
                CODE_CLEANUP_FAILED, f"租约 {lease_id} 不存在",
            )
        try:
            PoolService().release(db, item_id=int(item_id), lease_id=int(lease_id))
        except AppError as exc:
            return ProviderResult.fail(exc.code or CODE_CLEANUP_FAILED, str(exc))
        except Exception as exc:  # noqa: BLE001
            return ProviderResult.fail(CODE_CLEANUP_FAILED, str(exc)[:300])
        return ProviderResult.ok({"released_lease_id": int(lease_id)})

    # ---------------------------------------------------------------- 清理 步骤

    def _run_cleanup_steps(
        self,
        db: Session,
        fx_exec: FixtureExecution,
        *,
        environment: Environment,
        actor: User,
        project_id: int,
        outputs_by_key: dict[str, dict[str, Any]],
    ) -> list[str]:
        """运行清理`steps`。"""
        fixture = db.get(Fixture, fx_exec.fixture_id) if fx_exec.fixture_id else None
        if fixture is None:
            return []
        failures: list[str] = []
        steps = db.query(FixtureStep).filter(
            FixtureStep.fixture_id == fx_exec.fixture_id,
            FixtureStep.phase == "CLEANUP",
        ).order_by(FixtureStep.sort.desc(), FixtureStep.id.desc()).all()
        for step in steps:
            result = self._run_cleanup_step(
                db,
                step=step,
                owner_project_id=fixture.project_id,
                environment=environment,
                actor=actor,
                project_id=project_id,
                outputs_by_key=outputs_by_key,
                data_execution=db.get(DataExecution, fx_exec.data_execution_id),
                fixture_execution=fx_exec,
            )
            if not result.success:
                failures.append(f"步骤 {step.name}: {result.error_message or result.error_code}")
        return failures

    def _run_cleanup_step(
        self,
        db: Session,
        *,
        step: FixtureStep,
        owner_project_id: int,
        environment: Environment,
        actor: User,
        project_id: int,
        outputs_by_key: dict[str, dict[str, Any]],
        data_execution: DataExecution | None,
        fixture_execution: FixtureExecution | None,
    ) -> ProviderResult:
        """跑一个 CLEANUP 步骤：模板用**脱敏后的**契约输出解析。"""
        provider: BaseProvider | None
        config_json: dict[str, Any]
        provider_row: "DataProvider | None" = None
        if step.provider_id is not None:
            provider_row = db.get(DataProvider, step.provider_id)
            if provider_row is None or provider_row.project_id != owner_project_id:
                return ProviderResult.fail("PROVIDER_NOT_FOUND", f"Provider {step.provider_id} 不存在")
            provider = PROVIDER_REGISTRY.get(provider_row.provider_type)
            config_json = dict(provider_row.config_json or {})
        else:
            provider = provider_for_step_type(step.step_type)
            config_json = dict(step.config_json or {})
        if provider is None:
            return ProviderResult.fail(
                "PROVIDER_NOT_FOUND", f"步骤类型 {step.step_type} 没有 Provider 实现",
            )

        scope_vars = _scope_variables(outputs_by_key)
        private: dict[str, Any] = {}
        for values in outputs_by_key.values():
            private.update(values)

        ctx = ProviderContext(
            db=db,
            project_id=owner_project_id,
            environment=environment,
            actor=actor,
            variables=private,
            scope=ResolveScope(variables=scope_vars, environment=environment),
            runtime_scope="CLEANUP",
            step=step,
            provider=provider_row,
        )
        started = datetime.now()
        result = run_safe(provider, ctx)
        finished = datetime.now()

        rec = ProviderExecution(
            fixture_execution_id=fixture_execution.id if fixture_execution else None,
            data_execution_id=data_execution.id if data_execution else None,
            project_id=project_id,
            provider_id=step.provider_id,
            provider_type=provider.provider_type,
            step_id=step.id,
            status="SUCCESS" if result.success else "FAILED",
            input_snapshot=self._masker.mask_body(config_json),
            output_snapshot=self._masker.mask_body(dict(result.outputs)),
            started_at=started,
            finished_at=finished,
            duration_ms=int((finished - started).total_seconds() * 1000),
            error_code=None if result.success else result.error_code,
            error_message=None if result.success else result.error_message,
        )
        db.add(rec)
        db.flush()
        return result


def _scope_variables(outputs_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """把契约输出排成模板可取用的变量：``fixture.<KEY>.<name>`` 嵌套 + 扁平两处。"""
    scope_vars: dict[str, Any] = {
        "fixture": {key: dict(values) for key, values in outputs_by_key.items()},
    }
    for key, values in outputs_by_key.items():
        for name, value in values.items():
            scope_vars[f"fixture.{key}.{name}"] = value
    return scope_vars


def _try_parse_json(text: str | None) -> Any:
    """尝试将响应文本解析为 JSON；解析失败时返回空结果。"""
    if not text:
        return None
    try:
        import json

        return json.loads(text)
    except (ValueError, TypeError):
        return text


__all__ = ["CleanupRunner"]
