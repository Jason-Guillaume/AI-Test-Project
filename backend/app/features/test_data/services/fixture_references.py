"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.schemas import FixtureStepInput
from app.features.test_data.services.provider_service import provider_visible
from app.core.http.errors import CODE_PROVIDER_NOT_FOUND, AppError, bad_request
from app.features.test_data.services.fixture_validation import raise_cycle
from app.features.test_data.services.fixture_validation import raise_not_found


def resolve_key_to_fixture(
    db: Session, project_id: int, fixture_key: str, *, for_dependency: bool = False
) -> Fixture:
    """按 key 解析 Fixture：本项目同 key，或 scope=GLOBAL 且 ACTIVE 的定义。

    跨项目私有 Fixture 一律 404（隐藏存在性）。依赖场景额外要求 ACTIVE。
    """
    key = (fixture_key or "").strip()
    if not key:
        raise bad_request("fixture_key 不能为空")
    own = (
        db.query(Fixture)
        .filter(Fixture.project_id == project_id, Fixture.fixture_key == key)
        .first()
    )
    if own is not None:
        if for_dependency and own.status != "ACTIVE":
            raise_not_found(f"依赖的 Fixture {key} 不是 ACTIVE 状态")
        return own
    other = (
        db.query(Fixture)
        .filter(Fixture.fixture_key == key, Fixture.scope == "GLOBAL", Fixture.status == "ACTIVE")
        .first()
    )
    if other is not None:
        return other
    raise_not_found(f"Fixture {key} 不存在")


def assert_dependency_allowed(owner: Fixture, target: Fixture) -> None:
    """依赖合法性：禁止自依赖；跨项目只允许 GLOBAL 且 ACTIVE。"""
    if target.id == owner.id:
        raise_cycle([owner.fixture_key, owner.fixture_key])
    if target.project_id != owner.project_id:
        if target.scope != "GLOBAL" or target.status != "ACTIVE":
            raise_not_found(f"Fixture {target.fixture_key} 不存在")


def resolve_step_targets(
    db: Session, fixture: Fixture, steps: list[FixtureStepInput]
) -> set[int]:
    """解析 FIXTURE 步骤引用的 fixture_key，返回被依赖的 Fixture ID 集合。

    其他步骤若引用 Provider，这里校验归属（跨项目引用显示为 404）。
    """
    targets: set[int] = set()
    for step in steps:
        config = step.config_json or {}
        if step.step_type == "FIXTURE":
            target = resolve_key_to_fixture(
                db, fixture.project_id, str(config.get("fixture_key") or ""),
                for_dependency=True,
            )
            assert_dependency_allowed(fixture, target)
            targets.add(target.id)
        elif step.provider_id is not None:
            if provider_visible(db, step.provider_id, fixture.project_id) is None:
                raise AppError(
                    f"步骤引用的 Provider {step.provider_id} 不存在",
                    status_code=404,
                    code=CODE_PROVIDER_NOT_FOUND,
                )
    return targets
