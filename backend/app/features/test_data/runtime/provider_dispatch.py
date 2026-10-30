"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import DataExecution, FixtureExecution, ProviderExecution
from app.features.test_data.models.fixture import FixtureStep
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.providers import (
    PROVIDER_REGISTRY,
    RESERVED_STEP_TYPES,
    BaseProvider,
    ProviderResult,
    provider_for_step_type,
    run_safe,
)
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_FIXTURE_STEP_UNSUPPORTED,
    CODE_PROVIDER_DISABLED,
    CODE_PROVIDER_NOT_FOUND,
    AppError,
)
from app.features.test_data.runtime.generation_context import build_context
from app.features.test_data.runtime.generation_context import merge_outputs
from app.features.test_data.runtime.result_writer import record_provider_result


def run_step(masker: SensitiveDataMasker, db: Session, *, step: FixtureStep, owner_project_id: int, environment: Environment, actor: User, project_id: int, private: dict[str, Any], injected: dict[str, dict[str, Any]], runtime_scope: str, fixture_execution: FixtureExecution, data_execution: DataExecution, test_run_id: int | None, case_execution_id: int | None) -> ProviderResult:
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
            input_snapshot=masker.mask_body(step.config_json),
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

    provider, config_json, provider_row = step_binding(db, step, owner_project_id)
    started = time.perf_counter()
    rec = ProviderExecution(
        fixture_execution_id=fixture_execution.id,
        data_execution_id=data_execution.id,
        project_id=project_id,
        provider_id=step.provider_id,
        provider_type=provider.provider_type,
        step_id=step.id,
        status="RUNNING",
        input_snapshot=masker.mask_body(config_json),
        started_at=datetime.now(),
    )
    db.add(rec)
    db.flush()

    ctx = build_context(
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

    record_provider_result(masker, rec, result, started)
    db.flush()

    if result.success:
        merge_outputs(private, result)
    return result


def step_binding(db: Session, step: FixtureStep, owner_project_id: int) -> tuple[BaseProvider, dict[str, Any], DataProvider | None]:
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
