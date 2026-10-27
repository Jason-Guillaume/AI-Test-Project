"""Mock 执行作用域生命周期协调（§二十二 / §二十三 / §二十七）。

run_service 在用例执行期间调用本协调器：激活一个 MockContext（承载该用例声明的
scenario_overrides），执行完毕后关闭。这是 test_management → mock_management 的
唯一跨 feature 接入点，与 test_data.runtime.lifecycle.LifecycleManager 同款语义：
「runtime 模块可跨 feature 被执行编排复用，service 之间不互 import」。

并发隔离（§二十四）：绝不改全局默认场景，只在本 Context 内覆盖；不同 Case 的
Context 行级隔离，互不可见。Context 过期由 MockRuntimeService.expire_stale_contexts
惰性回收（§二十六），作为异常中断的安全网。

注意：MockContext 行必须 **已提交** 才能被 Mock Runtime 的独立会话看到，故
``activate_for_case`` 后调用方需 ``db.commit()``；``deactivate`` 由调用方在
CLEANUP 后随用例事务一起提交。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.mock_management.models import TestCaseMock
from app.features.mock_management.services.mock_runtime_service import (
    DEFAULT_CONTEXT_TTL_MINUTES,
    MOCK_CONTEXT_HEADER,
    MockRuntimeService,
)


class MockLifecycle:
    """用例级 MockContext 激活 / 关闭协调器。无状态，run_service 复用单例。"""

    def __init__(self) -> None:
        """初始化对象状态。"""
        self._runtime = MockRuntimeService()

    def activate_for_case(
        self, db: Session, *,
        project_id: int, test_run_id: int, case_execution_id: int, case_id: int,
        ttl_minutes: int = DEFAULT_CONTEXT_TTL_MINUTES,
    ) -> str | None:
        """为用例激活 MockContext：取该用例声明的 Mock（SETUP/EXECUTION/BOTH 都纳入，
        因为单 Context 跨整个用例生命周期），构造 {endpoint_id: scenario_id} 覆盖。

        无声明时返回 None（不创建 Context，对既有用例零影响）。
        """
        rows = (
            db.query(TestCaseMock)
            .filter(TestCaseMock.test_case_id == case_id)
            .order_by(TestCaseMock.sort.asc(), TestCaseMock.id.asc())
            .all()
        )
        if not rows:
            return None
        # 跨整个用例生命周期生效的覆盖：SETUP/EXECUTION/BOTH 全纳入。
        overrides: dict[int, int] = {}
        for row in rows:
            if row.scope in ("SETUP", "EXECUTION", "BOTH"):
                overrides[row.mock_endpoint_id] = row.mock_scenario_id
        if not overrides:
            return None
        ctx = self._runtime.activate_context(
            db, project_id=project_id, test_run_id=test_run_id,
            case_execution_id=case_execution_id, overrides=overrides,
            ttl_minutes=ttl_minutes,
        )
        return ctx.context_id

    def context_headers(self, context_id: str | None) -> dict[str, str] | None:
        """用例执行作用域的请求头，供执行器注入「发给被测系统」的那次请求。

        Mock Runtime 靠 X-Mock-Context 识别执行作用域并应用 scenario_overrides
        （Context Override > Explicit Matcher > Default）。激活 Context 只是建行；
        不把这个头送到被测系统入口，Context 永远不会生效，用例拿到的仍是默认场景。
        被测系统是否把它继续转发给依赖服务，属于被测系统侧的配合义务。
        """
        if not context_id:
            return None
        return {MOCK_CONTEXT_HEADER: context_id}

    def deactivate(self, db: Session, context_id: str | None) -> None:
        """关闭 MockContext（幂等）。context_id 为 None 时无操作。"""
        if not context_id:
            return
        self._runtime.deactivate_context(db, context_id)


__all__ = ["MockLifecycle"]
