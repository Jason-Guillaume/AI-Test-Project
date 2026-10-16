"""安全变异引擎：把一条规则应用到基线请求上。

纯函数（§6.3）：函数内不发 HTTP、不查库、不做 ``eval``。Fixture 输出和字段 schema
由调用方（Phase E 的 Runner）查好传进来；引擎只负责「校验 → 定位 → 调算子 → 写
trace → 返回新请求」，并且永远返回副本，不改入参 ``BaselineRequest``。

异常只有三类出口，Runner 按类写 execution.error_code：

- ``AppError(SECURITY_MUTATION_INVALID)``：类型不在白名单、配置含脚本键、
  算子与目标不匹配（子类 ``RuleNotApplicableError`` 表示「跳过」而非「崩了」）。
- ``AppError(SECURITY_MUTATION_NOT_ALLOWED)``：预留攻击类别或尚未开放的算子。
- ``ConfirmationRequiredError``：高风险未确认。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.shared.errors import (
    CODE_SECURITY_CONFIRMATION_REQUIRED,
    CODE_SECURITY_MUTATION_INVALID,
    CODE_SECURITY_MUTATION_NOT_ALLOWED,
    AppError,
)

from app.features.security_testing.runtime import operators, schema_reader, trace
from app.features.security_testing.runtime.types import (
    BaselineRequest,
    ConfirmationRequiredError,
    FieldSpec,
    MutationContext,
    MutationRuleView,
    MutatedRequest,
    ResolveScope,
    RuleNotApplicableError,
)
from app.features.security_testing.schemas import (
    MUTATION_TYPES,
    RESERVED_CATEGORIES,
    validate_no_script_keys,
)

__all__ = ["SecurityMutationEngine"]

#: 这些位置必须能定位到具体字段，没有 schema 就没有可变异的目标。
_SPEC_REQUIRED_LOCATIONS = {"PATH", "QUERY", "BODY"}


def _resolve_spec(fields: Sequence[FieldSpec] | None, rule: MutationRuleView) -> FieldSpec | None:
    """按目标位置与字段名解析 FieldSpec。

    HEADER / COOKIE 允许没有 schema（值取自基线请求头）；PATH / QUERY / BODY 必须
    在 schema 里点得到，否则跳过——无 schema 不自动 fuzz。
    """
    location = rule.target_location.upper()
    if location in {"METHOD", "REQUEST"}:
        return None
    if not rule.target_field:
        if location in _SPEC_REQUIRED_LOCATIONS:
            raise RuleNotApplicableError(
                f"{rule.mutation_type} 需要先展开到具体字段（target_field 为空）",
                code=CODE_SECURITY_MUTATION_INVALID,
            )
        return None
    spec = schema_reader.find_field(fields, location, rule.target_field)
    if spec is None and location in _SPEC_REQUIRED_LOCATIONS:
        raise RuleNotApplicableError(
            f"接口 schema 里没有 {location} 字段 {rule.target_field!r}，跳过（无 schema 不自动 fuzz）",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return spec


class SecurityMutationEngine:
    """安全变异引擎。无状态，所有方法都是静态的。"""

    @staticmethod
    def apply(
        baseline: BaselineRequest,
        rule: Any,
        *,
        scope: ResolveScope | dict[str, Any] | None = None,
        fields: Sequence[FieldSpec] | None = None,
        confirmed: bool = False,
        auth_type: str | None = None,
    ) -> MutatedRequest:
        """应用一条规则，返回变异后的请求与脱敏前的 trace。

        Args:
            baseline: 基线请求（不会被修改）。
            rule: ``MutationRuleView``、ORM 行或 dict。
            scope: 已解析的 Fixture 输出作用域。
            fields: 接口字段 schema（``schema_reader.read_fields`` 的产出）。
            confirmed: 高风险是否已由成员确认。
            auth_type: 接口的鉴权类型；缺省时用 ``baseline.auth_type``。

        Returns:
            MutatedRequest：``request`` 可直接展开成执行器入参；``changed`` 为
            False 且 ``notes`` 非空说明基线不具备可测条件，应记 INCONCLUSIVE。

        Raises:
            AppError: 见模块文档的三类出口。
        """
        view = rule if isinstance(rule, MutationRuleView) else MutationRuleView.from_row(rule)
        mutation_type = view.mutation_type

        if mutation_type not in MUTATION_TYPES:
            raise AppError(f"不支持的变异类型：{mutation_type}", code=CODE_SECURITY_MUTATION_INVALID)
        # 配置侧已在创建时校验过；这里再拦一次，防止库里存在历史脏数据。
        validate_no_script_keys(view.mutation_config)

        category = view.category or operators.CATEGORY_BY_MUTATION_TYPE.get(mutation_type)
        if category in RESERVED_CATEGORIES:
            raise AppError(
                f"{category} 是预留攻击类，Phase 1 不执行，也不生成任何攻击载荷",
                code=CODE_SECURITY_MUTATION_NOT_ALLOWED,
            )
        operator = operators.get_operator(mutation_type)
        if operator is None:
            raise AppError(
                f"变异类型 {mutation_type} 的执行器尚未开放",
                code=CODE_SECURITY_MUTATION_NOT_ALLOWED,
            )
        if view.confirmation_required and not confirmed:
            raise ConfirmationRequiredError(
                "该规则标记为高风险，需要成员确认后才能执行",
                code=CODE_SECURITY_CONFIRMATION_REQUIRED,
            )

        if scope is None:
            resolved: ResolveScope = ResolveScope()
        elif isinstance(scope, ResolveScope):
            resolved = scope
        else:
            resolved = ResolveScope.from_mapping(scope)

        auth = auth_type or baseline.auth_type or "none"
        working = baseline.copy()
        context = MutationContext(
            rule=view,
            spec=_resolve_spec(fields, view),
            scope=resolved,
            auth_header=operators.resolve_auth_header(auth, baseline.headers),
            confirmed=confirmed,
        )

        traces = operator(working, context) or []
        changed = working != baseline
        if changed and not traces:
            # 算子改了请求却没写 trace 时兜底对比，保证「每次变异必须留下说明」。
            traces = trace.request_diff(baseline, working, mutation_type)

        return MutatedRequest(
            request=working,
            mutation_type=mutation_type,
            traces=traces,
            notes=list(context.notes),
            changed=changed,
        )
