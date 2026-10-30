"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from app.features.test_management.schemas.common import TestAssertionType
from app.features.test_management.schemas.common import TestDataSourceType
from app.features.test_management.schemas.common import TestOperator
from app.features.test_management.schemas.common import TestPreconditionType
from app.features.test_management.schemas.common import TestStepType
from app.features.test_management.schemas.common import TestTargetType
from app.features.test_management.schemas.common import TestValueType


class TestCasePreconditionBase(BaseModel):
    type: TestPreconditionType = Field(default="VARIABLE", description="前置条件类型")
    target: str | None = Field(None, max_length=200, description="目标：变量名/实体/说明")
    operator: TestOperator = Field(default="EQ", description="操作符")
    expected_value: str | None = Field(None, description="期望值")
    description: str | None = Field(None, max_length=500, description="说明")
    config_json: dict[str, Any] | None = Field(None, description="附加配置")
    sort: int = Field(default=0, ge=0, description="排序")


class TestCasePreconditionCreate(TestCasePreconditionBase):
    """新增前置条件入参（test_case_id 由路径提供）。"""


class TestCasePreconditionUpdate(BaseModel):
    type: TestPreconditionType | None = None
    target: str | None = Field(None, max_length=200)
    operator: TestOperator | None = None
    expected_value: str | None = None
    description: str | None = Field(None, max_length=500)
    config_json: dict[str, Any] | None = None
    sort: int | None = Field(None, ge=0)


class TestCasePreconditionResponse(BaseModel):
    id: int
    test_case_id: int
    type: str
    target: str | None = None
    operator: str
    expected_value: str | None = None
    description: str | None = None
    config_json: dict[str, Any] | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestCaseDataBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="数据项名")
    value_type: TestValueType = Field(default="STRING", description="值类型")
    value: str | None = Field(None, description="值或引用标识")
    source_type: TestDataSourceType = Field(default="STATIC", description="来源")
    required: bool = Field(default=False, description="是否必需")
    description: str | None = Field(None, max_length=500, description="说明")
    config_json: dict[str, Any] | None = Field(None, description="附加配置")
    sort: int = Field(default=0, ge=0, description="排序")


class TestCaseDataCreate(TestCaseDataBase):
    """新增测试数据入参（test_case_id 由路径提供）。"""


class TestCaseDataUpdate(BaseModel):
    value_type: TestValueType | None = None
    value: str | None = None
    source_type: TestDataSourceType | None = None
    required: bool | None = None
    description: str | None = Field(None, max_length=500)
    config_json: dict[str, Any] | None = None
    sort: int | None = Field(None, ge=0)


class TestCaseDataResponse(BaseModel):
    id: int
    test_case_id: int
    name: str
    value_type: str
    value: str | None = None
    source_type: str
    required: bool
    description: str | None = None
    config_json: dict[str, Any] | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestCaseFixtureItem(BaseModel):
    """用例声明所需 Fixture 的一项：只引用 fixture_key，不写真实 task_id。"""

    fixture_key: str = Field(
        ..., min_length=1, max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]{0,99}$",
        description="Fixture 引用键（与 fixture.fixture_key 同规则）",
    )
    sort: int = Field(default=0, ge=0, description="排序")


class TestCaseFixtureReplace(BaseModel):
    """整体替换用例所需 Fixture 列表；空列表表示解除全部声明。"""

    fixtures: list[TestCaseFixtureItem] = Field(default_factory=list, max_length=50)


class TestCaseFixtureResponse(BaseModel):
    id: int
    test_case_id: int
    fixture_id: int
    fixture_key: str
    name: str | None = None
    entity_type: str | None = None
    scope: str | None = None
    status: str | None = None
    outputs: list[str] = Field(
        default_factory=list, description="输出契约名：测试数据按 fixture_key + output 绑定",
    )
    sort: int

    model_config = ConfigDict(from_attributes=True)


class TestStepBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="步骤名")
    step_type: TestStepType = Field(default="ACTION", description="步骤类型：SETUP/ACTION/ASSERT/CLEANUP")
    target_type: TestTargetType | None = Field(None, description="被测对象类型")
    target_id: int | None = Field(None, gt=0, description="被测对象ID")
    sort: int = Field(default=0, ge=0, description="排序")
    config_json: dict[str, Any] | None = Field(None, description="步骤配置")


class TestStepCreate(TestStepBase):
    """新增测试步骤入参（test_case_id 由路径提供）。"""


class TestStepUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    step_type: TestStepType | None = None
    target_type: TestTargetType | None = None
    target_id: int | None = Field(None, gt=0)
    sort: int | None = Field(None, ge=0)
    config_json: dict[str, Any] | None = None


class TestStepResponse(BaseModel):
    id: int
    test_case_id: int
    name: str
    step_type: str
    target_type: str | None = None
    target_id: int | None = None
    sort: int
    config_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestAssertionBase(BaseModel):
    assertion_type: TestAssertionType = Field(
        default="STATUS_CODE", description="断言类型：STATUS_CODE/JSON_PATH/HEADER/RESPONSE_TIME/CONTAINS/NOT_CONTAINS",
    )
    source: str | None = Field(None, max_length=100, description="来源标识：HEADER名/CONTEXT作用域")
    path: str | None = Field(None, max_length=500, description="JSONPath 或字段路径")
    operator: TestOperator = Field(default="EQ", description="操作符")
    expected_value: str | None = Field(None, description="期望值")
    required: bool = Field(default=True, description="是否必需（软断言=False）")
    step_id: int | None = Field(None, ge=0, description="关联步骤ID")
    sort: int = Field(default=0, ge=0, description="排序")


class TestAssertionCreate(TestAssertionBase):
    """新增断言入参（test_case_id 由路径提供）。"""


class TestAssertionUpdate(BaseModel):
    assertion_type: TestAssertionType | None = None
    source: str | None = Field(None, max_length=100)
    path: str | None = Field(None, max_length=500)
    operator: TestOperator | None = None
    expected_value: str | None = None
    required: bool | None = None
    step_id: int | None = Field(None, ge=0)
    sort: int | None = Field(None, ge=0)


class TestAssertionResponse(BaseModel):
    id: int
    test_case_id: int
    step_id: int | None = None
    assertion_type: str
    source: str | None = None
    path: str | None = None
    operator: str
    expected_value: str | None = None
    required: bool
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
