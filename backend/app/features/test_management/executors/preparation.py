"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from typing import Any
from sqlalchemy.orm import Session
from app.features.business.executors.context import ExecutionContext
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_step import TestStep
from app.features.test_data.runtime.data_factory import build_scope_variables
from app.execution.templates.resolver import (
    ResolveScope,
    generate_faker_value,
    resolve_env_key,
    resolve_template,
)
from app.core.models.configuration import Environment
from app.core.http.errors import CODE_DATA_RESOLVE_FAILED, CODE_VARIABLE_RESOLVE_FAILED, AppError


_VAR_SOURCES = ("VARIABLE", "RUNTIME")


def extract_fixture_outputs(variables: ExecutionContext | None) -> dict[str, dict[str, Any]]:
    """从 ExecutionContext 取出 ``{fixture_key: {output_name: value}}``。

    值本身是 dict 的条目视为一个 Fixture 命名空间；扁平标量条目留给 ``${runtime.X}``，
    不参与 Fixture 解析。
    """
    if variables is None:
        return {}
    raw = variables.variables if isinstance(variables, ExecutionContext) else dict(variables or {})
    return {
        key: dict(value)
        for key, value in raw.items()
        if isinstance(value, dict)
    }


def load_data_values(
    db: Session,
    case_id: int,
    environment: Environment,
    fixture_outputs: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """加载测试数据并解析为 name→value（§12.1 的 source_type 分派）。

    - STATIC：value 字面值
    - ENVIRONMENT：环境键（base_url / gateway_prefix / default_headers）
    - FIXTURE：从 Data Factory 注入的契约输出取
    - FAKER：白名单生成器现取现造
    - VARIABLE / RUNTIME：value 是变量名，从已注入变量里取

    缺失且 ``required`` 的项抛 ``AppError(DATA_RESOLVE_FAILED)`` —— 用例 ERROR，
    不是 FAILED（造数/解析失败不等于产品断言失败）。
    返回的第二个元素是「数据项名与 Fixture 输出同名」的冲突列表，写进 context_json。
    """
    fixture_outputs = fixture_outputs or {}
    flat_names = {f"{key}.{name}" for key, values in fixture_outputs.items() for name in values}

    rows = (
        db.query(TestCaseData)
        .filter(TestCaseData.test_case_id == case_id)
        .order_by(TestCaseData.sort.asc(), TestCaseData.id.asc())
        .all()
    )
    values: dict[str, Any] = {}
    overrides: list[str] = []
    for row in rows:
        source = (row.source_type or "STATIC").upper()
        cfg = row.config_json if isinstance(row.config_json, dict) else {}
        if source == "ENVIRONMENT":
            values[row.name] = resolve_env_key(environment, row.value or "")
        elif source == "FIXTURE":
            values[row.name] = fixture_output_value(row, cfg, fixture_outputs)
        elif source == "FAKER":
            values[row.name] = faker_data_value(row, cfg)
        elif source in _VAR_SOURCES:
            values[row.name] = lookup_variable((row.value or "").strip(), fixture_outputs, row)
        else:
            values[row.name] = parse_value(row.value, row.value_type)
        if row.name in flat_names:
            overrides.append(row.name)
    return values, overrides


def fixture_output_value(
    row: TestCaseData,
    cfg: dict[str, Any],
    fixture_outputs: dict[str, dict[str, Any]],
) -> Any:
    """FIXTURE 数据项：按 config_json 的 fixture_key/output 取已注入的契约输出。"""
    key = str(cfg.get("fixture_key") or "").strip()
    output = str(cfg.get("output") or "").strip()
    if not key or not output:
        raise AppError(
            f"测试数据 {row.name} 的 FIXTURE 配置缺少 fixture_key 或 output",
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    outs = fixture_outputs.get(key)
    found = isinstance(outs, dict) and output in outs and outs[output] is not None
    if not found and row.required:
        raise AppError(
            f"测试数据 {row.name} 引用的 Fixture 输出 {key}.{output} 不可用",
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    return outs.get(output) if isinstance(outs, dict) else None


def faker_data_value(row: TestCaseData, cfg: dict[str, Any]) -> Any:
    """FAKER 数据项：只调白名单生成器，不执行用户代码。"""
    generator = str(cfg.get("generator") or "").strip()
    if not generator:
        raise AppError(
            f"测试数据 {row.name} 的 FAKER 配置缺少 generator",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        )
    locale = str(cfg.get("locale") or "zh_CN")
    choices = cfg.get("choices") if isinstance(cfg.get("choices"), list) else None
    try:
        return generate_faker_value(generator, locale=locale, choices=choices)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - Faker 内部异常收敛成统一错误码
        raise AppError(
            f"测试数据 {row.name} 的 FAKER 生成失败（generator={generator}）：{exc}",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        ) from exc


def lookup_variable(
    target: str,
    fixture_outputs: dict[str, dict[str, Any]],
    row: TestCaseData,
) -> Any:
    """VARIABLE / RUNTIME 数据项：value 是变量名，不是字面值。

    依次按 fixture_key、输出名、`KEY.name` 三种写法找；找不到且必需时报
    ``DATA_RESOLVE_FAILED``。
    """
    if not target:
        if row.required:
            raise AppError(
                f"测试数据 {row.name} 的 source_type={row.source_type} 缺少变量名",
                status_code=400,
                code=CODE_DATA_RESOLVE_FAILED,
            )
        return None
    for key, values in fixture_outputs.items():
        if target == key:
            return dict(values)
        if isinstance(values, dict) and target in values:
            return values[target]
        if isinstance(values, dict) and f"{key}.{target}" in values:
            return values[f"{key}.{target}"]
    if row.required:
        raise AppError(
            f"测试数据 {row.name} 引用的变量 {target} 不可用",
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    return None


def fixture_flat(fixture_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fixture 输出的扁平视图 ``KEY.name → value``，供业务流变量使用。"""
    flat: dict[str, Any] = {}
    for key, values in fixture_outputs.items():
        for name, value in values.items():
            flat[f"{key}.{name}"] = value
    return flat


def build_execution_scope(
    data_values: dict[str, Any],
    environment: Environment,
    fixture_outputs: dict[str, dict[str, Any]],
) -> ResolveScope:
    """用例执行器的模板作用域：`${data.X}` 走测试数据，`${env.X}` 走环境，
    `${fixture.K.n}` / `${runtime.X}` 走 Data Factory 注入的输出。"""
    return ResolveScope(
        variables=build_scope_variables(fixture_outputs),
        data_values=data_values,
        environment=environment,
    )


def parse_value(raw: str | None, value_type: str | None) -> Any:
    """按 value_type 把字符串值解析为对应类型；解析失败保留字符串。"""
    if raw is None:
        return None
    vt = (value_type or "STRING").upper()
    if vt == "STRING":
        return raw
    if vt in ("INTEGER", "NUMBER"):
        try:
            return int(raw) if vt == "INTEGER" else float(raw)
        except (ValueError, TypeError):
            return raw
    if vt == "BOOLEAN":
        return raw.strip().lower() in ("true", "1", "yes", "on")
    if vt in ("OBJECT", "ARRAY"):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


def load_action_step_config(db: Session, case_id: int) -> dict[str, Any]:
    """取首个 ACTION 步骤的 config_json（无则空 dict）。"""
    step = (
        db.query(TestStep)
        .filter(TestStep.test_case_id == case_id, TestStep.step_type == "ACTION")
        .order_by(TestStep.sort.asc(), TestStep.id.asc())
        .first()
    )
    if step is None:
        # 退而取任意步骤。
        step = db.query(TestStep).filter(TestStep.test_case_id == case_id).order_by(TestStep.sort.asc()).first()
    cfg = step.config_json if (step is not None and isinstance(step.config_json, dict)) else {}
    return cfg


def load_assertions(db: Session, case_id: int) -> list[dict[str, Any]]:
    """加载`assertions`。"""
    rows = (
        db.query(TestAssertion)
        .filter(TestAssertion.test_case_id == case_id)
        .order_by(TestAssertion.sort.asc(), TestAssertion.id.asc())
        .all()
    )
    return [
        {"id": a.id, "assertion_type": a.assertion_type, "source": a.source,
         "path": a.path, "operator": a.operator, "expected_value": a.expected_value,
         "required": a.required}
        for a in rows
    ]


def resolve_tokens(obj: Any, scope: ResolveScope) -> Any:
    """占位符解析统一委托 VariableResolver（§12.1：执行器不再自己写正则）。

    支持 ``${data.X}`` / ``${env.X}``（原有语义不变），以及 Phase C 新增的
    ``${fixture.KEY.name}`` / ``${runtime.X}`` / ``${faker.X}``。
    """
    return resolve_template(obj, scope, required=False)
