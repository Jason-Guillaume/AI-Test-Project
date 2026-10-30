"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.features.test_data.models.fixture import FixtureOutput, FixtureStep
from app.features.test_data.models.provider import DataProvider
from app.features.test_data.providers import RESPONSE_BODY_KEY, ProviderContext, ProviderResult
from app.execution.templates.resolver import MISSING, ResolveScope, walk_path
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import CODE_DATA_RESOLVE_FAILED, AppError


def build_scope_variables(
    injected: dict[str, dict[str, Any]],
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把已注入的 Fixture 输出展开成模板可见的 variables。

    同时给两种写法：嵌套 ``fixture.<KEY>.<out>``（``variables["fixture"]``）与
    扁平 ``fixture.<KEY>.<out>``。Data Factory 的步骤上下文和用例执行器共用这一个
    入口，避免两侧各写一份展开逻辑。``base`` 是本次生成自己的运行期变量，优先级更高。
    """
    scope_vars: dict[str, Any] = {"fixture": {key: dict(values) for key, values in injected.items()}}
    for key, values in injected.items():
        for name, value in values.items():
            scope_vars[f"fixture.{key}.{name}"] = value
    return {**scope_vars, **(base or {})}


def read_source_path(private: dict[str, Any], source_path: str) -> Any:
    """按 ``source_path`` 从私有变量取值。

    两种写法都支持：
    - 裸键：``task_id`` → ``private["task_id"]``（Provider 输出映射名）
    - JSON 路径：``$.data.id`` / ``$data.id`` → ``private["data"]["id"]``
    """
    path = (source_path or "").strip()
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        path = path[1:]
    if not path:
        return MISSING
    return walk_path(private, path)


def build_context(*, db: Session, project_id: int, environment: Environment, actor: User, variables: dict[str, Any], injected: dict[str, dict[str, Any]], runtime_scope: str, step: FixtureStep | None, provider: DataProvider | None, test_run_id: int | None=None, case_execution_id: int | None=None) -> ProviderContext:
    """组装 ``ProviderContext``：私有变量 + 已注入的 Fixture 输出 + 作用域。"""
    return ProviderContext(
        db=db,
        project_id=project_id,
        environment=environment,
        actor=actor,
        variables=variables,
        scope=ResolveScope(variables=build_scope_variables(injected, base=variables), environment=environment),
        test_run_id=test_run_id,
        case_execution_id=case_execution_id,
        runtime_scope=runtime_scope,
        step=step,
        provider=provider,
    )


def merge_outputs(private: dict[str, Any], result: ProviderResult) -> None:
    """把步骤输出合并进私有变量。

    ``_response`` 是 Provider 的完整响应体，摊平到顶层——这样输出契约里
    ``source_path='$.data.id'`` 这种 JSON 路径写法能取到 ``response.data.id``，
    与只写映射名（``task_id``）两种写法都成立。
    """
    response = result.outputs.get(RESPONSE_BODY_KEY)
    if isinstance(response, dict):
        private.update(response)
    for key, value in result.outputs.items():
        if key == RESPONSE_BODY_KEY:
            continue
        private[key] = value


def collect_outputs(db: Session, *, fixture_id: int, fixture_key: str, private: dict[str, Any]) -> dict[str, Any]:
    """按输出契约从私有变量取值。缺一个就失败——契约必须被完整满足。"""
    outputs = db.query(FixtureOutput).filter(
        FixtureOutput.fixture_id == fixture_id,
    ).order_by(FixtureOutput.sort.asc(), FixtureOutput.id.asc()).all()
    if not outputs:
        return {}

    collected: dict[str, Any] = {}
    missing: list[FixtureOutput] = []
    for out in outputs:
        value = read_source_path(private, out.source_path)
        if value is MISSING:
            missing.append(out)
        else:
            collected[out.name] = value
    if missing:
        raise AppError(
            "Fixture " + fixture_key + " 的输出契约未取到值："
            + ", ".join(o.name + "(" + (o.source_path or "") + ")" for o in missing),
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    return collected
