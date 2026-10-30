"""领域 DTO 的唯一公开入口；显式导出各资源的 canonical 定义。"""

from __future__ import annotations

from app.features.test_management.schemas.common import CASE_EXECUTION_STATUSES
from app.features.test_management.schemas.common import CASE_EXECUTOR_TYPES
from app.features.test_management.schemas.executions import CaseExecutionListResponse
from app.features.test_management.schemas.executions import CaseExecutionResponse
from app.features.test_management.schemas.common import CaseExecutionStatus
from app.features.test_management.schemas.common import CaseExecutorType
from app.features.test_management.schemas.common import TEST_ASSERTION_TYPES
from app.features.test_management.schemas.common import TEST_CASE_TYPES
from app.features.test_management.schemas.common import TEST_DATA_SOURCE_TYPES
from app.features.test_management.schemas.common import TEST_EXECUTION_MODES
from app.features.test_management.schemas.common import TEST_OPERATORS
from app.features.test_management.schemas.common import TEST_PLAN_STATUSES
from app.features.test_management.schemas.common import TEST_PRECONDITION_TYPES
from app.features.test_management.schemas.common import TEST_PRIORITIES
from app.features.test_management.schemas.common import TEST_RUN_STATUSES
from app.features.test_management.schemas.common import TEST_SOURCE_TYPES
from app.features.test_management.schemas.common import TEST_STATUSES
from app.features.test_management.schemas.common import TEST_STEP_TYPES
from app.features.test_management.schemas.common import TEST_STRATEGY_CATEGORIES
from app.features.test_management.schemas.common import TEST_SUITE_TYPES
from app.features.test_management.schemas.common import TEST_TARGET_TYPES
from app.features.test_management.schemas.common import TEST_VALUE_TYPES
from app.features.test_management.schemas.case_inputs import TestAssertionBase
from app.features.test_management.schemas.case_inputs import TestAssertionCreate
from app.features.test_management.schemas.case_inputs import TestAssertionResponse
from app.features.test_management.schemas.common import TestAssertionType
from app.features.test_management.schemas.case_inputs import TestAssertionUpdate
from app.features.test_management.schemas.cases import TestCaseBase
from app.features.test_management.schemas.cases import TestCaseCreate
from app.features.test_management.schemas.case_inputs import TestCaseDataBase
from app.features.test_management.schemas.case_inputs import TestCaseDataCreate
from app.features.test_management.schemas.case_inputs import TestCaseDataResponse
from app.features.test_management.schemas.case_inputs import TestCaseDataUpdate
from app.features.test_management.schemas.cases import TestCaseDetailResponse
from app.features.test_management.schemas.case_inputs import TestCaseFixtureItem
from app.features.test_management.schemas.case_inputs import TestCaseFixtureReplace
from app.features.test_management.schemas.case_inputs import TestCaseFixtureResponse
from app.features.test_management.schemas.cases import TestCaseListResponse
from app.features.test_management.schemas.case_inputs import TestCasePreconditionBase
from app.features.test_management.schemas.case_inputs import TestCasePreconditionCreate
from app.features.test_management.schemas.case_inputs import TestCasePreconditionResponse
from app.features.test_management.schemas.case_inputs import TestCasePreconditionUpdate
from app.features.test_management.schemas.cases import TestCaseResponse
from app.features.test_management.schemas.common import TestCaseType
from app.features.test_management.schemas.cases import TestCaseUpdate
from app.features.test_management.schemas.common import TestDataSourceType
from app.features.test_management.schemas.common import TestExecutionMode
from app.features.test_management.schemas.common import TestOperator
from app.features.test_management.schemas.plans import TestPlanBase
from app.features.test_management.schemas.plans import TestPlanCreate
from app.features.test_management.schemas.plans import TestPlanListResponse
from app.features.test_management.schemas.plans import TestPlanResponse
from app.features.test_management.schemas.common import TestPlanStatus
from app.features.test_management.schemas.plans import TestPlanSuiteAdd
from app.features.test_management.schemas.plans import TestPlanSuiteResponse
from app.features.test_management.schemas.plans import TestPlanUpdate
from app.features.test_management.schemas.points import TestPointBase
from app.features.test_management.schemas.points import TestPointCreate
from app.features.test_management.schemas.points import TestPointListResponse
from app.features.test_management.schemas.points import TestPointResponse
from app.features.test_management.schemas.points import TestPointUpdate
from app.features.test_management.schemas.common import TestPreconditionType
from app.features.test_management.schemas.common import TestPriority
from app.features.test_management.schemas.executions import TestRunCreateRequest
from app.features.test_management.schemas.executions import TestRunListResponse
from app.features.test_management.schemas.executions import TestRunResponse
from app.features.test_management.schemas.common import TestRunStatus
from app.features.test_management.schemas.common import TestSourceType
from app.features.test_management.schemas.common import TestStatus
from app.features.test_management.schemas.case_inputs import TestStepBase
from app.features.test_management.schemas.case_inputs import TestStepCreate
from app.features.test_management.schemas.case_inputs import TestStepResponse
from app.features.test_management.schemas.common import TestStepType
from app.features.test_management.schemas.case_inputs import TestStepUpdate
from app.features.test_management.schemas.strategies import TestStrategyBase
from app.features.test_management.schemas.common import TestStrategyCategory
from app.features.test_management.schemas.strategies import TestStrategyCreate
from app.features.test_management.schemas.strategies import TestStrategyListResponse
from app.features.test_management.schemas.strategies import TestStrategyResponse
from app.features.test_management.schemas.strategies import TestStrategyUpdate
from app.features.test_management.schemas.suites import TestSuiteBase
from app.features.test_management.schemas.suites import TestSuiteCaseAdd
from app.features.test_management.schemas.suites import TestSuiteCaseResponse
from app.features.test_management.schemas.suites import TestSuiteCreate
from app.features.test_management.schemas.suites import TestSuiteListResponse
from app.features.test_management.schemas.suites import TestSuiteResponse
from app.features.test_management.schemas.common import TestSuiteType
from app.features.test_management.schemas.suites import TestSuiteUpdate
from app.features.test_management.schemas.common import TestTargetType
from app.features.test_management.schemas.common import TestValueType


__all__ = [
    'TEST_STRATEGY_CATEGORIES',
    'TestStrategyCategory',
    'TEST_PRIORITIES',
    'TestPriority',
    'TEST_TARGET_TYPES',
    'TestTargetType',
    'TEST_STATUSES',
    'TestStatus',
    'TEST_SOURCE_TYPES',
    'TestSourceType',
    'TEST_CASE_TYPES',
    'TestCaseType',
    'TEST_PRECONDITION_TYPES',
    'TestPreconditionType',
    'TEST_OPERATORS',
    'TestOperator',
    'TEST_VALUE_TYPES',
    'TestValueType',
    'TEST_DATA_SOURCE_TYPES',
    'TestDataSourceType',
    'TEST_STEP_TYPES',
    'TestStepType',
    'TEST_ASSERTION_TYPES',
    'TestAssertionType',
    'TEST_SUITE_TYPES',
    'TestSuiteType',
    'TEST_PLAN_STATUSES',
    'TestPlanStatus',
    'TEST_EXECUTION_MODES',
    'TestExecutionMode',
    'TEST_RUN_STATUSES',
    'TestRunStatus',
    'CASE_EXECUTION_STATUSES',
    'CaseExecutionStatus',
    'CASE_EXECUTOR_TYPES',
    'CaseExecutorType',
    'TestStrategyBase',
    'TestStrategyCreate',
    'TestStrategyUpdate',
    'TestStrategyResponse',
    'TestStrategyListResponse',
    'TestPointBase',
    'TestPointCreate',
    'TestPointUpdate',
    'TestPointResponse',
    'TestPointListResponse',
    'TestCaseBase',
    'TestCaseCreate',
    'TestCaseUpdate',
    'TestCaseResponse',
    'TestCaseListResponse',
    'TestCasePreconditionBase',
    'TestCasePreconditionCreate',
    'TestCasePreconditionUpdate',
    'TestCasePreconditionResponse',
    'TestCaseDataBase',
    'TestCaseDataCreate',
    'TestCaseDataUpdate',
    'TestCaseDataResponse',
    'TestCaseFixtureItem',
    'TestCaseFixtureReplace',
    'TestCaseFixtureResponse',
    'TestStepBase',
    'TestStepCreate',
    'TestStepUpdate',
    'TestStepResponse',
    'TestAssertionBase',
    'TestAssertionCreate',
    'TestAssertionUpdate',
    'TestAssertionResponse',
    'TestCaseDetailResponse',
    'TestSuiteBase',
    'TestSuiteCreate',
    'TestSuiteUpdate',
    'TestSuiteResponse',
    'TestSuiteListResponse',
    'TestSuiteCaseAdd',
    'TestSuiteCaseResponse',
    'TestPlanBase',
    'TestPlanCreate',
    'TestPlanUpdate',
    'TestPlanResponse',
    'TestPlanListResponse',
    'TestPlanSuiteAdd',
    'TestPlanSuiteResponse',
    'TestRunCreateRequest',
    'TestRunResponse',
    'TestRunListResponse',
    'CaseExecutionResponse',
    'CaseExecutionListResponse',
]
