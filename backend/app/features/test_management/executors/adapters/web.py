"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations


def execute_web(db, test_case, *, environment, actor, fixture_outputs, variables, extra_headers, case_execution_id):
    """交给 Web 领域校验确认指纹并管理浏览器资源。"""
    from app.features.web_testing.services.execution_adapter import run_web_case
    return run_web_case(db, test_case, environment=environment, actor=actor, fixture_outputs=fixture_outputs,
                        variables=variables, extra_headers=extra_headers, case_execution_id=case_execution_id)
