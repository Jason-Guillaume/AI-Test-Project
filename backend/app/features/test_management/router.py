"""测试管理路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下。资源级路径：
- /projects/{project_id}/test-(strategies|points|cases|suites|plans|runs)
- /test-(strategies|points|cases|suites|plans)/{id}
- /test-cases/{id}/(preconditions|data|steps|assertions) 与子实体 /test-case-*/{id}
- /test-suites/{id}/cases、/test-suite-cases/{id}
- /test-plans/{id}/suites、/test-plan-suites/{id}
- /test-plans/{plan_id}/runs（触发执行）、/test-runs/{id}(/cases)

权限：读 viewer+、写 member+、越权与不存在共用 404。端点统一 sync def；service owns commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.test_management.schemas import (
    CaseExecutionListResponse,
    TestAssertionCreate,
    TestAssertionUpdate,
    TestCaseCreate,
    TestCaseDataCreate,
    TestCaseDataUpdate,
    TestCaseListResponse,
    TestCasePreconditionCreate,
    TestCasePreconditionUpdate,
    TestCaseUpdate,
    TestPlanCreate,
    TestPlanSuiteAdd,
    TestPlanUpdate,
    TestPointCreate,
    TestPointUpdate,
    TestRunCreateRequest,
    TestRunListResponse,
    TestRunResponse,
    TestStepCreate,
    TestStepUpdate,
    TestStrategyCreate,
    TestStrategyUpdate,
    TestSuiteCaseAdd,
    TestSuiteCreate,
    TestSuiteUpdate,
)
from app.features.test_management.services.case_service import CaseService
from app.features.test_management.services.plan_service import PlanService
from app.features.test_management.services.point_service import PointService
from app.features.test_management.services.run_service import RunService
from app.features.test_management.services.strategy_service import StrategyService
from app.features.test_management.services.suite_service import SuiteService
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["测试管理"])

# 服务无状态，路由层复用单例。
_STRATEGY = StrategyService()
_POINT = PointService()
_CASE = CaseService()
_SUITE = SuiteService()
_PLAN = PlanService()
_RUN = RunService()


# --------------------------------------------------------------------------- 测试策略


@router.get("/projects/{project_id}/test-strategies", response_model=list, summary="测试策略列表")
def list_strategies(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    category: str | None = Query(None),
    keyword: str | None = Query(None),
):
    # response_model=list 时返回 items；前端按需改用 ListResponse。
    return _STRATEGY.list_strategies(
        db, project_id, user, category=category, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post(
    "/projects/{project_id}/test-strategies",
    status_code=status.HTTP_201_CREATED,
    summary="新建测试策略",
)
def create_strategy(
    project_id: int,
    body: TestStrategyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _STRATEGY.create_strategy(db, project_id, body, actor=user)


@router.get("/test-strategies/{strategy_id}", summary="测试策略详情")
def get_strategy(strategy_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _STRATEGY.get_strategy(db, strategy_id, user)


@router.patch("/test-strategies/{strategy_id}", summary="编辑测试策略")
def update_strategy(
    strategy_id: int,
    body: TestStrategyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _STRATEGY.update_strategy(db, strategy_id, body, actor=user)


@router.delete("/test-strategies/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试策略")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _STRATEGY.delete_strategy(db, strategy_id, actor=user)
    return None


# --------------------------------------------------------------------------- 测试点


@router.get("/projects/{project_id}/test-points", response_model=list, summary="测试点列表")
def list_points(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    strategy_id: int | None = Query(None, ge=1),
    target_type: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    return _POINT.list_points(
        db, project_id, user, strategy_id=strategy_id, target_type=target_type,
        status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-points", status_code=status.HTTP_201_CREATED, summary="新建测试点")
def create_point(
    project_id: int, body: TestPointCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _POINT.create_point(db, project_id, body, actor=user)


@router.get("/test-points/{point_id}", summary="测试点详情")
def get_point(point_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _POINT.get_point(db, point_id, user)


@router.patch("/test-points/{point_id}", summary="编辑测试点")
def update_point(
    point_id: int, body: TestPointUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _POINT.update_point(db, point_id, body, actor=user)


@router.delete("/test-points/{point_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试点")
def delete_point(point_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _POINT.delete_point(db, point_id, actor=user)
    return None


# --------------------------------------------------------------------------- 测试用例


@router.get("/projects/{project_id}/test-cases", response_model=list, summary="测试用例列表")
def list_cases(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    test_point_id: int | None = Query(None, ge=1),
    target_type: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    return _CASE.list_cases(
        db, project_id, user, test_point_id=test_point_id, target_type=target_type,
        status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-cases", status_code=status.HTTP_201_CREATED, summary="新建测试用例")
def create_case(
    project_id: int, body: TestCaseCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.create_case(db, project_id, body, actor=user)


@router.get("/test-cases/{case_id}", summary="测试用例基本信息")
def get_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CASE.get_case(db, case_id, user)


@router.get("/test-cases/{case_id}/detail", summary="测试用例聚合详情（前置条件/数据/步骤/断言）")
def get_case_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CASE.get_case_detail(db, case_id, user)


@router.patch("/test-cases/{case_id}", summary="编辑测试用例（乐观锁）")
def update_case(
    case_id: int, body: TestCaseUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.update_case(db, case_id, body, actor=user)


@router.delete("/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试用例")
def delete_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CASE.delete_case(db, case_id, actor=user)
    return None


# --------------------------------------------------------------------------- 用例子实体：前置条件


@router.get("/test-cases/{case_id}/preconditions", response_model=list, summary="前置条件列表")
def list_preconditions(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CASE.list_preconditions(db, case_id, user)


@router.post("/test-cases/{case_id}/preconditions", status_code=status.HTTP_201_CREATED, summary="新增前置条件")
def create_precondition(
    case_id: int, body: TestCasePreconditionCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.create_precondition(db, case_id, body, actor=user)


@router.patch("/test-case-preconditions/{precondition_id}", summary="编辑前置条件")
def update_precondition(
    precondition_id: int, body: TestCasePreconditionUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.update_precondition(db, precondition_id, body, actor=user)


@router.delete("/test-case-preconditions/{precondition_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除前置条件")
def delete_precondition(precondition_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CASE.delete_precondition(db, precondition_id, actor=user)
    return None


# --------------------------------------------------------------------------- 用例子实体：测试数据


@router.get("/test-cases/{case_id}/data", response_model=list, summary="测试数据列表")
def list_data(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CASE.list_data(db, case_id, user)


@router.post("/test-cases/{case_id}/data", status_code=status.HTTP_201_CREATED, summary="新增测试数据")
def create_data(
    case_id: int, body: TestCaseDataCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.create_data(db, case_id, body, actor=user)


@router.patch("/test-case-data/{data_id}", summary="编辑测试数据")
def update_data(
    data_id: int, body: TestCaseDataUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.update_data(db, data_id, body, actor=user)


@router.delete("/test-case-data/{data_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试数据")
def delete_data(data_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CASE.delete_data(db, data_id, actor=user)
    return None


# --------------------------------------------------------------------------- 用例子实体：步骤


@router.get("/test-cases/{case_id}/steps", response_model=list, summary="测试步骤列表")
def list_steps(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CASE.list_steps(db, case_id, user)


@router.post("/test-cases/{case_id}/steps", status_code=status.HTTP_201_CREATED, summary="新增测试步骤")
def create_step(
    case_id: int, body: TestStepCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.create_step(db, case_id, body, actor=user)


@router.patch("/test-steps/{step_id}", summary="编辑测试步骤")
def update_step(
    step_id: int, body: TestStepUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.update_step(db, step_id, body, actor=user)


@router.delete("/test-steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试步骤")
def delete_step(step_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CASE.delete_step(db, step_id, actor=user)
    return None


# --------------------------------------------------------------------------- 用例子实体：断言


@router.get("/test-cases/{case_id}/assertions", response_model=list, summary="断言列表")
def list_assertions(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CASE.list_assertions(db, case_id, user)


@router.post("/test-cases/{case_id}/assertions", status_code=status.HTTP_201_CREATED, summary="新增断言")
def create_assertion(
    case_id: int, body: TestAssertionCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.create_assertion(db, case_id, body, actor=user)


@router.patch("/test-assertions/{assertion_id}", summary="编辑断言")
def update_assertion(
    assertion_id: int, body: TestAssertionUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CASE.update_assertion(db, assertion_id, body, actor=user)


@router.delete("/test-assertions/{assertion_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除断言")
def delete_assertion(assertion_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CASE.delete_assertion(db, assertion_id, actor=user)
    return None


# --------------------------------------------------------------------------- 测试套件


@router.get("/projects/{project_id}/test-suites", response_model=list, summary="测试套件列表")
def list_suites(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    suite_type: str | None = Query(None),
    keyword: str | None = Query(None),
):
    return _SUITE.list_suites(
        db, project_id, user, suite_type=suite_type, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-suites", status_code=status.HTTP_201_CREATED, summary="新建测试套件")
def create_suite(
    project_id: int, body: TestSuiteCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _SUITE.create_suite(db, project_id, body, actor=user)


@router.get("/test-suites/{suite_id}", summary="测试套件详情")
def get_suite(suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _SUITE.get_suite(db, suite_id, user)


@router.patch("/test-suites/{suite_id}", summary="编辑测试套件")
def update_suite(
    suite_id: int, body: TestSuiteUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _SUITE.update_suite(db, suite_id, body, actor=user)


@router.delete("/test-suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试套件")
def delete_suite(suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _SUITE.delete_suite(db, suite_id, actor=user)
    return None


# --------------------------------------------------------------------------- 套件-用例关联


@router.get("/test-suites/{suite_id}/cases", response_model=list, summary="套件下的用例列表")
def list_suite_cases(suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _SUITE.list_suite_cases(db, suite_id, user)


@router.post("/test-suites/{suite_id}/cases", status_code=status.HTTP_201_CREATED, summary="把用例加入套件")
def add_suite_case(
    suite_id: int, body: TestSuiteCaseAdd,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _SUITE.add_suite_case(db, suite_id, body, actor=user)


@router.delete("/test-suite-cases/{suite_case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="从套件移除用例")
def remove_suite_case(suite_case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _SUITE.remove_suite_case(db, suite_case_id, actor=user)
    return None


# --------------------------------------------------------------------------- 测试计划


@router.get("/projects/{project_id}/test-plans", response_model=list, summary="测试计划列表")
def list_plans(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    return _PLAN.list_plans(
        db, project_id, user, status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-plans", status_code=status.HTTP_201_CREATED, summary="新建测试计划")
def create_plan(
    project_id: int, body: TestPlanCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _PLAN.create_plan(db, project_id, body, actor=user)


@router.get("/test-plans/{plan_id}", summary="测试计划详情")
def get_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _PLAN.get_plan(db, plan_id, user)


@router.patch("/test-plans/{plan_id}", summary="编辑测试计划")
def update_plan(
    plan_id: int, body: TestPlanUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _PLAN.update_plan(db, plan_id, body, actor=user)


@router.delete("/test-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试计划")
def delete_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _PLAN.delete_plan(db, plan_id, actor=user)
    return None


# --------------------------------------------------------------------------- 计划-套件关联


@router.get("/test-plans/{plan_id}/suites", response_model=list, summary="计划下的套件列表")
def list_plan_suites(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _PLAN.list_plan_suites(db, plan_id, user)


@router.post("/test-plans/{plan_id}/suites", status_code=status.HTTP_201_CREATED, summary="把套件加入计划")
def add_plan_suite(
    plan_id: int, body: TestPlanSuiteAdd,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _PLAN.add_plan_suite(db, plan_id, body, actor=user)


@router.delete("/test-plan-suites/{plan_suite_id}", status_code=status.HTTP_204_NO_CONTENT, summary="从计划移除套件")
def remove_plan_suite(plan_suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _PLAN.remove_plan_suite(db, plan_suite_id, actor=user)
    return None


# --------------------------------------------------------------------------- 测试执行


@router.post(
    "/test-plans/{plan_id}/runs",
    response_model=TestRunResponse,
    status_code=status.HTTP_200_OK,
    summary="触发测试计划执行（同步执行，返回完成的 TestRun）",
)
def create_run(
    plan_id: int, body: TestRunCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _RUN.create_and_execute_run(db, plan_id, body, actor=user)


@router.get("/test-runs/{run_id}", response_model=TestRunResponse, summary="测试执行记录详情")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _RUN.get_run(db, run_id, user)


@router.get("/test-runs/{run_id}/cases", response_model=CaseExecutionListResponse, summary="用例执行记录列表")
def list_case_executions(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _RUN.list_case_executions(db, run_id, user)


@router.get("/projects/{project_id}/test-runs", response_model=TestRunListResponse, summary="项目测试执行记录列表")
def list_runs(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return _RUN.list_runs(db, project_id, user, page=page, page_size=page_size)
