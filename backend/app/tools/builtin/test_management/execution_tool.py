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

from sqlalchemy.orm import Session

from app.features.test_management.models.execution import TestRun
from app.features.test_management.services.run_service import RunService
from app.features.test_management.services.selected_case_run_service import create_test_run as _create_test_run
from app.platform.projects.services.access_service import get_project_or_404
from app.core.models.identity import User
from app.core.http.errors import not_found


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
    """委托测试管理应用服务创建选定用例运行。"""
    return _create_test_run(
        db, project_id, actor,
        case_ids=case_ids, environment_id=environment_id,
        session_id=session_id, source_label=source_label,
    )


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


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'create_test_run': ('execution.create_test_run', 'execute'),
    'get_test_run': ('execution.get_test_run', 'read'),
    'get_case_executions': ('runtime.execution.get_case_executions', 'read'),
})
