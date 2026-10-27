"""Agent Tool 层：执行编排（§32）。

Agent **不重新实现**执行链路。`create_test_run` 建**临时** `TestPlan` + `TestSuite`
（名称带 `[Agent]` 前缀 + session 标识，便于人工区分与追溯），把选中用例挂入，
随后调用现有 `RunService.create_and_execute_run`——由此复用 TestCaseExecutor /
断言引擎 / CaseExecution 落库全流程。临时计划保留在库中（不自动删除，可审计）。

权限：写操作走 `require_writable_project`（member+，不足 403）；跨项目资源统一 404。
执行环境是**平台级全局**资源（`environment` 表无 project_id），故只校验存在与启用态，
不做项目归属校验。
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.features.test_management.models.execution import TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_plan import TestPlan, TestPlanSuite
from app.features.test_management.models.test_suite import TestSuite, TestSuiteCase
from app.features.test_management.schemas import TestRunCreateRequest
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
)
from app.features.test_management.services.run_service import RunService
from app.features.environment_configuration.services.environment_service import resolve_project_environment
from app.models.identity import User
from app.shared.errors import bad_request, not_found


_RUN = RunService()


def create_test_run(
    db: Session,
    project_id: int,
    actor: User,
    *,
    case_ids: list[int],
    environment_id: int,
    session_id: int,
    source_label: str = "Agent",
) -> dict:
    """为选中用例建临时计划 + 套件并立即执行，返回 TestRun 响应 dict。

    校验（任一失败即中止，不残留半成品）：
    - case_ids 非空（§18 无用例不执行）；
    - 每个 case 存在且属于 project_id（跨项目用例 404，防越权执行）；
    - 环境存在且启用（平台级资源，404 隐藏停用态）。
    - source_label 仅允许 Agent / Task，用于原业务计划与套件页面标记真实来源。
    """
    require_writable_project(db, project_id, actor)
    # 去重保序：case_ids 由前端 / 节点传入，可能含重复。
    ordered_ids = list(dict.fromkeys(case_ids))
    if not ordered_ids:
        raise bad_request("未选择测试用例")

    cases = db.query(TestCase).filter(TestCase.id.in_(ordered_ids)).all()
    if len(cases) != len(ordered_ids):
        raise not_found("部分测试用例不存在")
    for c in cases:
        if c.project_id != project_id:
            raise not_found("测试用例不存在")

    resolve_project_environment(db, project_id, environment_id)

    # 临时计划 / 套件名称带 uuid 短码保证项目内唯一（uq_*_project_name）。
    tag = uuid4().hex[:6]
    source_label = source_label if source_label in {"Agent", "Task"} else "Agent"
    plan = TestPlan(
        project_id=project_id,
        name=f"[{source_label}]session-{session_id}-{tag}",
        description=f"{source_label} 运行 {session_id} 临时执行计划",
        environment_id=environment_id,
        status="ACTIVE",
        execution_mode="MANUAL",
        created_by=actor.id,
    )
    db.add(plan)
    db.flush()
    suite = TestSuite(
        project_id=project_id,
        name=f"[{source_label}]session-{session_id}-{tag}",
        description=f"{source_label} 临时测试套件",
        suite_type="CUSTOM",
        enabled=True,
        created_by=actor.id,
    )
    db.add(suite)
    db.flush()
    # 注意：test_plan_suite 无 enabled 列，test_suite_case 有（执行链路按后者过滤）。
    db.add(TestPlanSuite(plan_id=plan.id, suite_id=suite.id, sort=0))
    for idx, case_id in enumerate(ordered_ids):
        db.add(TestSuiteCase(suite_id=suite.id, test_case_id=case_id, sort=idx, enabled=True))
    db.commit()

    return _RUN.create_and_execute_run(
        db, plan.id, TestRunCreateRequest(environment_id=environment_id), actor=actor,
    ).model_dump(mode="json")


def get_test_run(db: Session, run_id: int, user: User, *, project_id: int) -> dict:
    """取一次执行记录（含通过 / 失败 / 错误计数）。跨项目 404。"""
    get_project_or_404(db, project_id, user)
    run = db.get(TestRun, run_id)
    if run is None or run.project_id != project_id:
        raise not_found("测试执行记录不存在")
    return _RUN.get_run(db, run_id, user).model_dump(mode="json")


def get_case_executions(db: Session, run_id: int, user: User, *, project_id: int) -> dict:
    """取执行记录下的逐用例执行详情（含 assertion_results / 快照 / error_code）。

    快照由执行器在落库前脱敏（SensitiveDataMasker），ResultAnalyzer 读取时已是安全
    形态；仍不得据此推断真实凭证（§34）。
    """
    get_project_or_404(db, project_id, user)
    run = db.get(TestRun, run_id)
    if run is None or run.project_id != project_id:
        raise not_found("测试执行记录不存在")
    return _RUN.list_case_executions(db, run_id, user).model_dump(mode="json")
