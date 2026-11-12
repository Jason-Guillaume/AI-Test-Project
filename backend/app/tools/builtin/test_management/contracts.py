"""测试资产工具的结构化输入契约。

供 Agent 工作流校验模型输出后交给测试资产工具保存；只依赖业务公开 schema，
不反向依赖 Agent 状态或工作流。
"""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, Field
from app.features.test_management.schemas import (
    TestAssertionCreate, TestCaseDataCreate, TestCasePreconditionCreate, TestStepCreate,
)


class TestPointDraft(BaseModel):
    """TestPointGeneratorNode 单条产出。落库时由 tool 补 source_type=AI 等追溯字段。"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    target_type: Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"] = "API"
    strategy_id: int | None = Field(None, gt=0)
    api_id: int | None = Field(None, gt=0)
    business_flow_id: int | None = Field(None, gt=0)
    business_action_id: int | None = Field(None, gt=0)
    rationale: str | None = Field(None, description="生成理由（供人工 review 判断）")


class TestPointDraftList(BaseModel):
    """TestPointGeneratorNode 产出的集合包装（LLM 结构化输出根对象）。"""

    points: list[TestPointDraft]


# Fixture 引用键：与 fixture.fixture_key 同规则（^[A-Z][A-Z0-9_]{0,99}$）。
FixtureKey = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Z][A-Z0-9_]{0,99}$")]

# Mock 场景作用域：与 mock_management 的 MockScope 同取值。
MockScope = Literal["SETUP", "EXECUTION", "BOTH"]


class MockScenarioRef(BaseModel):
    """required_mocks 单项：只能引用提示词 available_mocks 里列出的 scenario_id。"""

    mock_scenario_id: int = Field(
        ..., gt=0, description="提示词 available_mocks 里的 mock_scenario_id",
    )
    scope: MockScope = Field(
        "EXECUTION",
        description="SETUP/EXECUTION/BOTH：该 Mock 在哪些阶段生效（默认 EXECUTION）",
    )


class TestCaseDraft(BaseModel):
    """TestCaseGeneratorNode 单条产出：用例 + 子实体。子实体复用 test_management Create 模型。"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    case_type: Literal[
        "FUNCTIONAL", "BUSINESS", "NEGATIVE", "BOUNDARY", "PERMISSION", "SECURITY", "EXCEPTION"
    ] = "FUNCTIONAL"
    target_type: Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"] = "API"
    test_point_id: int | None = Field(None, gt=0, description="源自哪个已确认测试点")
    api_id: int | None = Field(None, gt=0)
    business_flow_id: int | None = Field(None, gt=0)
    business_action_id: int | None = Field(None, gt=0)
    preconditions: list[TestCasePreconditionCreate] = Field(default_factory=list)
    test_data: list[TestCaseDataCreate] = Field(default_factory=list)
    steps: list[TestStepCreate] = Field(default_factory=list)
    assertions: list[TestAssertionCreate] = Field(default_factory=list, description="至少 1 条断言")
    # 所需 Fixture：只填提示词里列出的 fixture_key，需要运行时数据时才有；不写真实 ID。
    required_fixtures: list[FixtureKey] = Field(
        default_factory=list, max_length=20,
        description="所需 Fixture 的 fixture_key（仅可引用已注册且 ACTIVE 的）",
    )
    # 所需 Mock：只填提示词 available_mocks 里列出的 scenario_id，需要模拟依赖行为时才有。
    required_mocks: list[MockScenarioRef] = Field(
        default_factory=list, max_length=20,
        description="所需 Mock 场景的 mock_scenario_id（仅可引用本项目已配置的）",
    )
    rationale: str | None = None


class TestCaseDraftList(BaseModel):
    """TestCaseGeneratorNode 产出的集合包装。"""

    cases: list[TestCaseDraft]


