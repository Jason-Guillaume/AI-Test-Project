"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.test_data.schemas import (
    FIXTURE_CLEANUP_POLICIES,
    FIXTURE_ON_FAILURE,
    FIXTURE_PHASES,
    FIXTURE_SCOPES,
    FIXTURE_STATUSES,
    FIXTURE_STEP_TYPES,
    VALUE_TYPES,
    FixtureOutputInput,
    FixtureStepInput,
)
from app.core.http.errors import (
    CODE_FIXTURE_DEPENDENCY_CYCLE,
    CODE_FIXTURE_NOT_FOUND,
    AppError,
    bad_request,
    conflict,
)


def raise_cycle(path_keys: list[str]) -> None:
    """环检测失败：400 FIXTURE_DEPENDENCY_CYCLE，带出环上的 key 序列。"""
    raise AppError(
        "Fixture 依赖存在环：" + " → ".join(path_keys),
        status_code=400,
        code=CODE_FIXTURE_DEPENDENCY_CYCLE,
    )


def raise_not_found(message: str = "Fixture 不存在") -> None:
    """资源不存在或不可见时抛出 404 错误。"""
    raise AppError(message, status_code=404, code=CODE_FIXTURE_NOT_FOUND)


def validate_scope(value: str) -> str:
    """校验范围。"""
    if value not in FIXTURE_SCOPES:
        raise bad_request("作用域取值非法：CASE/RUN/PROJECT/GLOBAL")
    return value


def validate_status(value: str) -> str:
    """校验状态。"""
    if value not in FIXTURE_STATUSES:
        raise bad_request("状态取值非法：DRAFT/ACTIVE/DISABLED")
    return value


def validate_cleanup_policy(value: str) -> str:
    """校验清理策略。"""
    if value not in FIXTURE_CLEANUP_POLICIES:
        raise bad_request("清理策略取值非法：AFTER_CASE/AFTER_RUN/MANUAL/NEVER")
    return value


def validate_step(step: FixtureStepInput) -> None:
    """步骤字面量校验；provider_id 归属校验由调用方完成。"""
    if step.phase not in FIXTURE_PHASES:
        raise bad_request("步骤阶段取值非法：GENERATE/CLEANUP")
    if step.step_type not in FIXTURE_STEP_TYPES:
        raise bad_request(f"步骤类型取值非法：{step.step_type}")
    if step.on_failure not in FIXTURE_ON_FAILURE:
        raise bad_request("失败策略取值非法：ABORT/CONTINUE")
    if not step.name.strip():
        raise bad_request("步骤名称不能为空")


def validate_output(out: FixtureOutputInput) -> None:
    """校验输出。"""
    if out.value_type not in VALUE_TYPES:
        raise bad_request(f"输出值类型取值非法：{out.value_type}")
    if not out.source_path.strip():
        raise bad_request("输出 source_path 不能为空")
    if not out.name.strip():
        raise bad_request("输出名称不能为空")


def validate_outputs_unique(outputs: list[FixtureOutputInput]) -> None:
    """校验`outputs``unique`。"""
    names = [out.name.strip() for out in outputs]
    if len(set(names)) != len(names):
        raise conflict("输出契约名称必须唯一")
