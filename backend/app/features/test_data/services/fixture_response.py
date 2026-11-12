"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.fixture import Fixture, FixtureDependency, FixtureOutput, FixtureStep
from app.features.test_data.schemas import (
    FixtureBriefResponse,
    FixtureDependencyResponse,
    FixtureDetailResponse,
    FixtureOutputResponse,
    FixtureStepResponse,
)
from app.features.test_data.services.provider_service import provider_visible


def attach_counters(db: Session, items: list[Fixture]) -> list[FixtureBriefResponse]:
    """给列表项补输出名 / 步骤数 / 依赖数 / 引用数（聚合查询，避免 N+1）。"""
    ids = [row.id for row in items]
    if not ids:
        return []

    output_names: dict[int, list[str]] = {}
    for fid, name in (
        db.query(FixtureOutput.fixture_id, FixtureOutput.name)
        .filter(FixtureOutput.fixture_id.in_(ids))
        .order_by(FixtureOutput.sort, FixtureOutput.id)
        .all()
    ):
        output_names.setdefault(fid, []).append(name)

    step_counts: dict[int, int] = {fid: 0 for fid in ids}
    generate_counts: dict[int, int] = {fid: 0 for fid in ids}
    cleanup_counts: dict[int, int] = {fid: 0 for fid in ids}
    for fid, phase in (
        db.query(FixtureStep.fixture_id, FixtureStep.phase)
        .filter(FixtureStep.fixture_id.in_(ids))
        .all()
    ):
        step_counts[fid] = step_counts.get(fid, 0) + 1
        if phase == "GENERATE":
            generate_counts[fid] = generate_counts.get(fid, 0) + 1
        else:
            cleanup_counts[fid] = cleanup_counts.get(fid, 0) + 1

    dep_counts: dict[int, int] = {fid: 0 for fid in ids}
    for (fid,) in (
        db.query(FixtureDependency.fixture_id)
        .filter(FixtureDependency.fixture_id.in_(ids))
        .all()
    ):
        dep_counts[fid] = dep_counts.get(fid, 0) + 1

    ref_counts: dict[int, int] = {fid: 0 for fid in ids}
    for (fid,) in (
        db.query(TestCaseFixture.fixture_id).filter(TestCaseFixture.fixture_id.in_(ids)).all()
    ):
        ref_counts[fid] = ref_counts.get(fid, 0) + 1

    responses: list[FixtureBriefResponse] = []
    for row in items:
        resp = FixtureBriefResponse.model_validate(row)
        resp.output_names = output_names.get(row.id, [])
        resp.step_count = step_counts.get(row.id, 0)
        resp.generate_step_count = generate_counts.get(row.id, 0)
        resp.cleanup_step_count = cleanup_counts.get(row.id, 0)
        resp.dependency_count = dep_counts.get(row.id, 0)
        resp.referenced_case_count = ref_counts.get(row.id, 0)
        responses.append(resp)
    return responses


def detail_response(db: Session, fixture: Fixture) -> FixtureDetailResponse:
    """详情：基本信息 + 步骤 + 输出契约 + 依赖 + 引用它的用例。"""
    steps = (
        db.query(FixtureStep)
        .filter(FixtureStep.fixture_id == fixture.id)
        .order_by(FixtureStep.phase, FixtureStep.sort, FixtureStep.id)
        .all()
    )
    outputs = (
        db.query(FixtureOutput)
        .filter(FixtureOutput.fixture_id == fixture.id)
        .order_by(FixtureOutput.sort, FixtureOutput.id)
        .all()
    )
    dependencies = (
        db.query(FixtureDependency)
        .filter(FixtureDependency.fixture_id == fixture.id)
        .order_by(FixtureDependency.sort, FixtureDependency.id)
        .all()
    )

    step_responses: list[FixtureStepResponse] = []
    for step in steps:
        resp = FixtureStepResponse.model_validate(step)
        # Provider 归属校验：跨项目引用置 None（对调用方隐藏存在性）。
        if resp.provider_id is not None and provider_visible(
            db, resp.provider_id, fixture.project_id
        ) is None:
            resp.provider_id = None
        step_responses.append(resp)

    dep_responses: list[FixtureDependencyResponse] = []
    for dep in dependencies:
        target = db.get(Fixture, dep.depends_on_fixture_id)
        resp = FixtureDependencyResponse.model_validate(dep)
        if target is not None:
            resp.depends_on_key = target.fixture_key
            resp.depends_on_name = target.name
            resp.depends_on_entity_type = target.entity_type
        dep_responses.append(resp)

    referenced_cases: list[dict] = [
        {"test_case_id": row.test_case_id, "sort": row.sort}
        for row in (
            db.query(TestCaseFixture)
            .filter(TestCaseFixture.fixture_id == fixture.id)
            .order_by(TestCaseFixture.sort, TestCaseFixture.id)
            .all()
        )
    ]

    brief = attach_counters(db, [fixture])[0]
    return FixtureDetailResponse(
        **brief.model_dump(),
        steps=step_responses,
        outputs=[FixtureOutputResponse.model_validate(o) for o in outputs],
        dependencies=dep_responses,
        referenced_cases=referenced_cases,
    )
