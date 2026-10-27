"""Data Factory 编排器（§8）。

把一次「造数」跑完：依赖展开 → 按序执行步骤 → 收集输出契约 → 写执行记录。

约定：
- 依赖链从 ``fixture_dependency`` 表展开（保存时由 FIXTURE 步骤派生，也可手工声明）。
  因此步骤循环里遇到 ``step_type=FIXTURE`` 直接跳过——它已经被依赖链执行过了，
  再跑一遍会把同一个 Fixture 生成两次。
- 每个 Fixture 有自己的**私有变量** dict。步骤中间键只留在私有 dict 里，
  不进入输出契约，也不传给下一个 Fixture（验收标准一：中间变量不出契约）。
- 只有 ``fixture_output.source_path`` 声明过的键才对外可见，注入形态是
  ``fixture.<KEY>.<name>``（嵌套）与 ``fixture.<KEY>.<name>``（扁平）两处，
  模板里两种写法都能取到。
- ``scope`` 由调用方传入：手工试跑传 CASE（不写项目级缓存，避免试跑污染项目数据），
  用例执行传 CASE/RUN，Run 级准备传 RUN。缓存读写在 Phase C 的 lifecycle 里。
- Provider 抛出的具体错误码（如 DATABASE_TABLE_NOT_ALLOWED）**原样**记录并上抛，
  不统一改写成 FIXTURE_GENERATION_FAILED——排障时要知道是白名单问题还是接口问题。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import (
    DataExecution,
    FixtureExecution,
    ProviderExecution,
)
from app.features.test_data.models.fixture import Fixture, FixtureOutput, FixtureStep
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.providers import (
    CLEANUP_HANDLE_KEY,
    PROVIDER_REGISTRY,
    RESPONSE_BODY_KEY,
    RESERVED_STEP_TYPES,
    BaseProvider,
    ProviderContext,
    ProviderResult,
    provider_for_step_type,
    run_safe,
)
from app.features.test_data.runtime.fixture_resolver import (
    expand_dependency_order,
    load_visible_fixture,
)
from app.features.test_data.runtime.variable_resolver import (
    _MISSING,
    ResolveScope,
    walk_path,
)
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.errors import (
    CODE_DATA_RESOLVE_FAILED,
    CODE_FIXTURE_DISABLED,
    CODE_FIXTURE_NOT_FOUND,
    CODE_FIXTURE_STEP_UNSUPPORTED,
    CODE_PROVIDER_DISABLED,
    CODE_PROVIDER_NOT_FOUND,
    AppError,
)


def build_scope_variables(
    injected: dict[str, dict[str, Any]],
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把已注入的 Fixture 输出展开成模板可见的 variables。

    同时给两种写法：嵌套 ``fixture.<KEY>.<out>``（``variables["fixture"]``）与
    扁平 ``fixture.<KEY>.<out>``。Data Factory 的步骤上下文和用例执行器共用这一个
    入口，避免两侧各写一份展开逻辑。``base`` 是本次生成自己的运行期变量，优先级更高。
    """
    scope_vars: dict[str, Any] = {"fixture": {key: dict(values) for key, values in injected.items()}}
    for key, values in injected.items():
        for name, value in values.items():
            scope_vars[f"fixture.{key}.{name}"] = value
    return {**scope_vars, **(base or {})}


@dataclass
class GenerationResult:
    """一次生成的结果。``outputs`` 是**未脱敏**的契约输出，调用方注入上下文用。"""

    data_execution_id: int
    status: str
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class DataFactory:
    """造数编排器。无状态，进程级复用。"""

    def __init__(self, masker: SensitiveDataMasker | None = None) -> None:
        """初始化对象状态。"""
        self._masker = masker or SensitiveDataMasker()

    # ---------------------------------------------------------------- 入口：固定数据 Fixture

    def generate(
        self,
        db: Session,
        *,
        fixture_id: int,
        project_id: int,
        environment: Environment,
        actor: User,
        scope: str = "CASE",
        variables: dict[str, Any] | None = None,
        test_run_id: int | None = None,
        case_execution_id: int | None = None,
    ) -> GenerationResult:
        """生成一个 Fixture（含其依赖链），写 ``data_execution`` 总记录。

        成功返回 READY；失败把记录落成 FAILED 后**原样抛出** AppError，调用方决定
        是转成 HTTP 错误还是让用例 ERROR。
        """
        data_exec = DataExecution(
            project_id=project_id,
            status="GENERATING",
            environment_id=environment.id,
            scope=scope,
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
            started_at=datetime.now(),
            cleanup_status="PENDING",
        )
        db.add(data_exec)
        db.flush()

        outputs: dict[str, dict[str, Any]] = {}
        started = time.perf_counter()
        try:
            ordered = expand_dependency_order(db, fixture_id)
            for fixture in ordered:
                # 依赖边在保存时对拥有者校验过；这里按**消费方**项目再核一次，
                # 防止引用保存之后 GLOBAL 定义被停用或改成私有。
                load_visible_fixture(db, fixture.id, project_id=project_id)
                self._generate_one(
                    db,
                    fixture=fixture,
                    project_id=project_id,
                    owner_project_id=fixture.project_id,
                    environment=environment,
                    actor=actor,
                    scope=scope,
                    variables=variables,
                    injected=outputs,
                    data_execution=data_exec,
                    test_run_id=test_run_id,
                    case_execution_id=case_execution_id,
                )
        except AppError as exc:
            self._finish(
                data_exec, started,
                status="FAILED",
                error_code=exc.code or "FIXTURE_GENERATION_FAILED",
                error_message=str(exc),
            )
            self._persist(db)
            raise

        self._finish(data_exec, started, status="READY")
        db.commit()
        return GenerationResult(
            data_execution_id=data_exec.id,
            status="READY",
            outputs=outputs,
        )

    def generate_key(
        self,
        db: Session,
        *,
        fixture_key: str,
        project_id: int,
        environment: Environment,
        actor: User,
        scope: str = "CASE",
        variables: dict[str, Any] | None = None,
        test_run_id: int | None = None,
        case_execution_id: int | None = None,
    ) -> GenerationResult:
        """按 fixture_key 生成（用例侧只引用 key，不引用自增 ID）。"""
        key = (fixture_key or "").strip()
        if not key:
            raise AppError("fixture_key 不能为空", status_code=400, code=CODE_FIXTURE_NOT_FOUND)
        fixture = db.query(Fixture).filter(
            Fixture.project_id == project_id,
            Fixture.fixture_key == key,
        ).first()
        if fixture is None:
            fixture = db.query(Fixture).filter(
                Fixture.fixture_key == key,
                Fixture.scope == "GLOBAL",
                Fixture.status == "ACTIVE",
            ).first()
        if fixture is None:
            raise AppError(
                f"Fixture {key} 不存在",
                status_code=404,
                code=CODE_FIXTURE_NOT_FOUND,
            )
        return self.generate(
            db,
            fixture_id=fixture.id,
            project_id=project_id,
            environment=environment,
            actor=actor,
            scope=scope,
            variables=variables,
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
        )

    # ---------------------------------------------------------------- 入口：单 Provider 试跑

    def test_provider(
        self,
        db: Session,
        *,
        provider_id: int,
        project_id: int,
        environment: Environment,
        actor: User,
        variables: dict[str, Any] | None = None,
    ) -> DataExecution:
        """手工试跑一个 Data Provider（不走 Fixture，不写契约输出）。

        走完整的归属、环境、白名单校验——试跑和生产用同一条路径。
        """
        provider_row = db.get(DataProvider, provider_id)
        if provider_row is None or provider_row.project_id != project_id:
            raise AppError(
                f"Provider {provider_id} 不存在",
                status_code=404,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        if not provider_row.enabled:
            raise AppError(
                f"Provider {provider_row.name} 已停用",
                status_code=400,
                code=CODE_PROVIDER_DISABLED,
            )

        instance = PROVIDER_REGISTRY.get(provider_row.provider_type)
        if instance is None:
            raise AppError(
                f"不支持的 Provider 类型：{provider_row.provider_type}",
                status_code=400,
                code=CODE_PROVIDER_NOT_FOUND,
            )

        data_exec = DataExecution(
            project_id=project_id,
            status="GENERATING",
            environment_id=environment.id,
            scope="MANUAL",
            started_at=datetime.now(),
        )
        db.add(data_exec)
        db.flush()

        step_exec = ProviderExecution(
            data_execution_id=data_exec.id,
            project_id=project_id,
            provider_id=provider_row.id,
            provider_type=provider_row.provider_type,
            status="RUNNING",
            input_snapshot=self._mask(provider_row.config_json),
            started_at=datetime.now(),
        )
        db.add(step_exec)
        db.flush()

        started = time.perf_counter()
        ctx = self._build_context(
            db=db,
            project_id=project_id,
            environment=environment,
            actor=actor,
            variables=dict(variables or {}),
            injected={},
            runtime_scope="MANUAL",
            step=None,
            provider=provider_row,
        )
        result = run_safe(instance, ctx)

        self._record_provider_result(step_exec, result, started)
        self._finish(
            data_exec, started,
            status="READY" if result.success else "FAILED",
            error_code=None if result.success else result.error_code,
            error_message=None if result.success else result.error_message,
        )
        db.commit()
        if not result.success:
            raise AppError(
                result.error_message or "Provider 试跑失败",
                status_code=400,
                code=result.error_code or "FIXTURE_GENERATION_FAILED",
            )
        return data_exec

    # ---------------------------------------------------------------- 单 固定数据 Fixture

    def _generate_one(
        self,
        db: Session,
        *,
        fixture: Fixture,
        project_id: int,
        owner_project_id: int,
        environment: Environment,
        actor: User,
        scope: str,
        injected: dict[str, dict[str, Any]],
        data_execution: DataExecution,
        variables: dict[str, Any] | None,
        test_run_id: int | None,
        case_execution_id: int | None,
    ) -> None:
        """生成一个 Fixture，把契约输出合并进 ``injected``。失败即抛。"""
        if fixture.status != "ACTIVE":
            raise AppError(
                f"Fixture {fixture.fixture_key} 状态为 {fixture.status}，只有 ACTIVE 可执行",
                status_code=400,
                code=CODE_FIXTURE_DISABLED,
            )

        fx_exec = FixtureExecution(
            data_execution_id=data_execution.id,
            project_id=project_id,
            fixture_id=fixture.id,
            fixture_key=fixture.fixture_key,
            status="GENERATING",
            scope=fixture.scope,
            cache_hit=False,
            input_snapshot=self._mask({"fixture_key": fixture.fixture_key, "scope": scope}),
            started_at=datetime.now(),
        )
        db.add(fx_exec)
        db.flush()

        # 运行期变量是这次生成自己的输入，${runtime.X} 就是从这里取。
        private: dict[str, Any] = dict(variables or {})
        started = time.perf_counter()
        outputs: dict[str, Any] = {}

        try:
            steps = db.query(FixtureStep).filter(
                FixtureStep.fixture_id == fixture.id,
                FixtureStep.phase == "GENERATE",
            ).order_by(FixtureStep.sort.asc(), FixtureStep.id.asc()).all()

            for step in steps:
                if step.step_type == "FIXTURE":
                    continue
                result = self._run_step(
                    db,
                    step=step,
                    owner_project_id=owner_project_id,
                    environment=environment,
                    actor=actor,
                    project_id=project_id,
                    private=private,
                    injected=injected,
                    runtime_scope=scope,
                    fixture_execution=fx_exec,
                    data_execution=data_execution,
                    test_run_id=test_run_id,
                    case_execution_id=case_execution_id,
                )
                if not result.success and step.on_failure != "CONTINUE":
                    raise AppError(
                        result.error_message or f"步骤 {step.name} 执行失败",
                        status_code=400,
                        code=result.error_code or "FIXTURE_GENERATION_FAILED",
                    )

            outputs = self._collect_outputs(
                db, fixture_id=fixture.id, fixture_key=fixture.fixture_key, private=private,
            )
            fx_exec.status = "READY"
            fx_exec.output_snapshot = self._mask(dict(outputs))
        except AppError as exc:
            fx_exec.status = "FAILED"
            fx_exec.error_code = exc.code or "FIXTURE_GENERATION_FAILED"
            fx_exec.error_message = str(exc)[:2000]
        finally:
            fx_exec.finished_at = datetime.now()
            fx_exec.duration_ms = int((time.perf_counter() - started) * 1000)
            db.flush()

        if fx_exec.status != "READY":
            raise AppError(
                fx_exec.error_message or "Fixture 生成失败",
                status_code=400,
                code=fx_exec.error_code or "FIXTURE_GENERATION_FAILED",
            )
        injected[fixture.fixture_key] = dict(outputs)

    def _run_step(
        self,
        db: Session,
        *,
        step: FixtureStep,
        owner_project_id: int,
        environment: Environment,
        actor: User,
        project_id: int,
        private: dict[str, Any],
        injected: dict[str, dict[str, Any]],
        runtime_scope: str,
        fixture_execution: FixtureExecution,
        data_execution: DataExecution,
        test_run_id: int | None,
        case_execution_id: int | None,
    ) -> ProviderResult:
        """执行单个步骤并写 ``provider_execution`` 记录。成功即合并输出到私有变量。"""
        if step.step_type in RESERVED_STEP_TYPES:
            now = datetime.now()
            rec = ProviderExecution(
                fixture_execution_id=fixture_execution.id,
                data_execution_id=data_execution.id,
                project_id=project_id,
                provider_id=step.provider_id,
                provider_type=str(step.step_type),
                step_id=step.id,
                status="SKIPPED",
                input_snapshot=self._mask(step.config_json),
                started_at=now,
                finished_at=now,
                error_code=CODE_FIXTURE_STEP_UNSUPPORTED,
                error_message=f"步骤类型 {step.step_type} 只保存不执行",
            )
            db.add(rec)
            db.flush()
            raise AppError(
                f"步骤 {step.name} 的类型 {step.step_type} 只保存不执行",
                status_code=400,
                code=CODE_FIXTURE_STEP_UNSUPPORTED,
            )

        provider, config_json, provider_row = self._step_binding(db, step, owner_project_id)
        started = time.perf_counter()
        rec = ProviderExecution(
            fixture_execution_id=fixture_execution.id,
            data_execution_id=data_execution.id,
            project_id=project_id,
            provider_id=step.provider_id,
            provider_type=provider.provider_type,
            step_id=step.id,
            status="RUNNING",
            input_snapshot=self._mask(config_json),
            started_at=datetime.now(),
        )
        db.add(rec)
        db.flush()

        ctx = self._build_context(
            db=db,
            project_id=owner_project_id,
            environment=environment,
            actor=actor,
            variables=private,
            injected=injected,
            runtime_scope=runtime_scope,
            step=step,
            provider=provider_row,
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
        )
        result = run_safe(provider, ctx)

        self._record_provider_result(rec, result, started)
        db.flush()

        if result.success:
            self._merge_outputs(private, result)
        return result

    @staticmethod
    def _step_binding(
        db: Session,
        step: FixtureStep,
        owner_project_id: int,
    ) -> tuple[BaseProvider, dict[str, Any], DataProvider | None]:
        """解析步骤引用的 Provider，返回 (Provider 实例, 配置 dict, Provider 行)。

        优先引用 ``step.provider_id``（配置在 Provider 行上）；否则按 ``step_type``
        找到同类型实现，用步骤自己的 config_json。归属校验按**拥有者**项目——
        GLOBAL Fixture 的步骤配置属于它自己的项目。

        返回的 Provider 行要放进 ``ProviderContext.provider``：``config_of`` 靠它决定
        配置来自 Provider 行还是步骤内联配置。
        """
        if step.provider_id is not None:
            provider_row = db.get(DataProvider, step.provider_id)
            if provider_row is None or provider_row.project_id != owner_project_id:
                raise AppError(
                    f"Provider {step.provider_id} 不存在",
                    status_code=404,
                    code=CODE_PROVIDER_NOT_FOUND,
                )
            if not provider_row.enabled:
                raise AppError(
                    f"Provider {provider_row.name} 已停用",
                    status_code=400,
                    code=CODE_PROVIDER_DISABLED,
                )
            instance = PROVIDER_REGISTRY.get(provider_row.provider_type)
            if instance is None:
                raise AppError(
                    f"不支持的 Provider 类型：{provider_row.provider_type}",
                    status_code=400,
                    code=CODE_PROVIDER_NOT_FOUND,
                )
            return instance, dict(provider_row.config_json or {}), provider_row

        instance = provider_for_step_type(step.step_type)
        if instance is None:
            raise AppError(
                f"步骤类型 {step.step_type} 没有对应的 Provider 实现",
                status_code=400,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        return instance, dict(step.config_json or {}), None

    # ---------------------------------------------------------------- 上下文与输出

    @staticmethod
    def _build_context(
        *,
        db: Session,
        project_id: int,
        environment: Environment,
        actor: User,
        variables: dict[str, Any],
        injected: dict[str, dict[str, Any]],
        runtime_scope: str,
        step: FixtureStep | None,
        provider: DataProvider | None,
        test_run_id: int | None = None,
        case_execution_id: int | None = None,
    ) -> ProviderContext:
        """组装 ``ProviderContext``：私有变量 + 已注入的 Fixture 输出 + 作用域。"""
        return ProviderContext(
            db=db,
            project_id=project_id,
            environment=environment,
            actor=actor,
            variables=variables,
            scope=ResolveScope(variables=build_scope_variables(injected, base=variables), environment=environment),
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
            runtime_scope=runtime_scope,
            step=step,
            provider=provider,
        )

    @staticmethod
    def _merge_outputs(private: dict[str, Any], result: ProviderResult) -> None:
        """把步骤输出合并进私有变量。

        ``_response`` 是 Provider 的完整响应体，摊平到顶层——这样输出契约里
        ``source_path='$.data.id'`` 这种 JSON 路径写法能取到 ``response.data.id``，
        与只写映射名（``task_id``）两种写法都成立。
        """
        response = result.outputs.get(RESPONSE_BODY_KEY)
        if isinstance(response, dict):
            private.update(response)
        for key, value in result.outputs.items():
            if key == RESPONSE_BODY_KEY:
                continue
            private[key] = value

    def _collect_outputs(
        self,
        db: Session,
        *,
        fixture_id: int,
        fixture_key: str,
        private: dict[str, Any],
    ) -> dict[str, Any]:
        """按输出契约从私有变量取值。缺一个就失败——契约必须被完整满足。"""
        outputs = db.query(FixtureOutput).filter(
            FixtureOutput.fixture_id == fixture_id,
        ).order_by(FixtureOutput.sort.asc(), FixtureOutput.id.asc()).all()
        if not outputs:
            return {}

        collected: dict[str, Any] = {}
        missing: list[FixtureOutput] = []
        for out in outputs:
            value = read_source_path(private, out.source_path)
            if value is _MISSING:
                missing.append(out)
            else:
                collected[out.name] = value
        if missing:
            raise AppError(
                "Fixture " + fixture_key + " 的输出契约未取到值："
                + ", ".join(o.name + "(" + (o.source_path or "") + ")" for o in missing),
                status_code=400,
                code=CODE_DATA_RESOLVE_FAILED,
            )
        return collected

    # ---------------------------------------------------------------- 记录收尾

    def _record_provider_result(
        self,
        rec: ProviderExecution,
        result: ProviderResult,
        started: float,
    ) -> None:
        """写入 Provider 执行结果：状态、耗时、脱敏快照、cleanup 句柄。"""
        rec.status = "SUCCESS" if result.success else "FAILED"
        rec.finished_at = datetime.now()
        rec.duration_ms = int((time.perf_counter() - started) * 1000)
        snapshot = self._mask(dict(result.outputs))
        if result.cleanup_handle is not None:
            snapshot = dict(snapshot or {})
            snapshot[CLEANUP_HANDLE_KEY] = result.cleanup_handle
        rec.output_snapshot = snapshot
        rec.error_code = None if result.success else result.error_code
        rec.error_message = None if result.success else (result.error_message or None)

    def _mask(self, value: Any) -> Any:
        """脱敏对应数据。"""
        return self._masker.mask_body(value)

    @staticmethod
    def _finish(
        data_exec: DataExecution,
        started: float,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """保存固定数据生成结果并关闭执行记录。"""
        data_exec.status = status
        data_exec.finished_at = datetime.now()
        data_exec.duration_ms = int((time.perf_counter() - started) * 1000)
        data_exec.error_code = error_code
        data_exec.error_message = error_message

    @staticmethod
    def _persist(db: Session) -> None:
        """把失败记录落库；commit 失败则回滚，原异常照常上抛。"""
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()


def read_source_path(private: dict[str, Any], source_path: str) -> Any:
    """按 ``source_path`` 从私有变量取值。

    两种写法都支持：
    - 裸键：``task_id`` → ``private["task_id"]``（Provider 输出映射名）
    - JSON 路径：``$.data.id`` / ``$data.id`` → ``private["data"]["id"]``
    """
    path = (source_path or "").strip()
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        path = path[1:]
    if not path:
        return _MISSING
    return walk_path(private, path)


__all__ = ["DataFactory", "GenerationResult", "read_source_path"]
