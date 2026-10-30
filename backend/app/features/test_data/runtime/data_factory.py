"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.test_data.runtime.generation_context import build_scope_variables
from app.features.test_data.runtime.generation_context import read_source_path

import time
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import DataExecution, ProviderExecution
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.providers import PROVIDER_REGISTRY, run_safe
from app.features.test_data.runtime.generation_plan import iter_generation_plan
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_FIXTURE_NOT_FOUND,
    CODE_PROVIDER_DISABLED,
    CODE_PROVIDER_NOT_FOUND,
    AppError,
)
from app.features.test_data.runtime.contracts import GenerationResult
from app.features.test_data.runtime.generation_context import build_context
from app.features.test_data.runtime.result_writer import finish
from app.features.test_data.runtime.fixture_runner import generate_one
from app.features.test_data.runtime.result_writer import persist
from app.features.test_data.runtime.result_writer import record_provider_result


class DataFactory:
    """协调生成计划和事务；Provider、上下文和记录分别由明确能力持有。"""

    def __init__(self, masker: SensitiveDataMasker | None = None) -> None:
        """初始化对象状态。"""
        self._masker = masker or SensitiveDataMasker()

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
            for fixture in iter_generation_plan(db, fixture_id, project_id):
                generate_one(self._masker,
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
            finish(
                data_exec, started,
                status="FAILED",
                error_code=exc.code or "FIXTURE_GENERATION_FAILED",
                error_message=str(exc),
            )
            persist(db)
            raise

        finish(data_exec, started, status="READY")
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
            input_snapshot=self._masker.mask_body(provider_row.config_json),
            started_at=datetime.now(),
        )
        db.add(step_exec)
        db.flush()

        started = time.perf_counter()
        ctx = build_context(
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

        record_provider_result(self._masker, step_exec, result, started)
        finish(
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


__all__ = [
    'GenerationResult',
    'build_scope_variables',
    'read_source_path',
]
