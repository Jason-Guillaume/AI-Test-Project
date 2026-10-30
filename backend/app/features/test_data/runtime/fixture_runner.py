"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import DataExecution, FixtureExecution
from app.features.test_data.models.fixture import Fixture, FixtureStep
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import CODE_FIXTURE_DISABLED, AppError
from app.features.test_data.runtime.generation_context import collect_outputs
from app.features.test_data.runtime.provider_dispatch import run_step


def generate_one(masker: SensitiveDataMasker, db: Session, *, fixture: Fixture, project_id: int, owner_project_id: int, environment: Environment, actor: User, scope: str, injected: dict[str, dict[str, Any]], data_execution: DataExecution, variables: dict[str, Any] | None, test_run_id: int | None, case_execution_id: int | None) -> None:
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
        input_snapshot=masker.mask_body({"fixture_key": fixture.fixture_key, "scope": scope}),
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
            result = run_step(masker,
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

        outputs = collect_outputs(
            db, fixture_id=fixture.id, fixture_key=fixture.fixture_key, private=private,
        )
        fx_exec.status = "READY"
        fx_exec.output_snapshot = masker.mask_body(dict(outputs))
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
