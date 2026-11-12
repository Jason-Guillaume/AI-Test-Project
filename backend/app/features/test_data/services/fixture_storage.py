"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.test_data.models.fixture import Fixture, FixtureOutput, FixtureStep
from app.features.test_data.schemas import FixtureOutputInput, FixtureStepInput
from app.features.test_data.services.fixture_dependencies import reconcile_step_edges
from app.features.test_data.services.fixture_references import resolve_step_targets


def save_steps(db: Session, fixture: Fixture, steps: list[FixtureStepInput]) -> None:
    """整体写入步骤（创建场景：无旧步骤），同时写入步骤派生的依赖边。"""
    reconcile_step_edges(db, fixture.id, set(), resolve_step_targets(db, fixture, steps))
    for row in steps_from_inputs(fixture.id, steps):
        db.add(row)


def save_outputs(db: Session, fixture: Fixture, outputs: list[FixtureOutputInput]) -> None:
    """保存`outputs`。"""
    for row in outputs_from_inputs(fixture.id, outputs):
        db.add(row)
    db.flush()


def steps_from_inputs(fixture_id: int, steps: list[FixtureStepInput]) -> list[FixtureStep]:
    """从`steps`输入。"""
    rows: list[FixtureStep] = []
    for step in steps:
        on_failure = step.on_failure or ("CONTINUE" if step.phase == "CLEANUP" else "ABORT")
        rows.append(
            FixtureStep(
                fixture_id=fixture_id,
                phase=step.phase,
                step_type=step.step_type,
                name=step.name.strip(),
                sort=step.sort,
                provider_id=step.provider_id,
                config_json=step.config_json,
                on_failure=on_failure,
            )
        )
    return rows


def outputs_from_inputs(fixture_id: int, outputs: list[FixtureOutputInput]) -> list[FixtureOutput]:
    """从输出输入。"""
    return [
        FixtureOutput(
            fixture_id=fixture_id,
            name=out.name.strip(),
            value_type=out.value_type,
            source_path=out.source_path.strip(),
            description=(out.description or "").strip() or None,
            sort=out.sort,
        )
        for out in outputs
    ]
