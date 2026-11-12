"""安全计划：preview / confirm / discard。

preview 只做「算一遍」，不写 TestCase；生成的 ``security_plan`` 行是未落成用例的
快照。confirm 才把选中的预览项写成 ``case_type='SECURITY'`` 的用例 + ``security_case``
扩展行。blocked（缺 Fixture）的项照样可以保存，但落库时 ``enabled=False``，
避免在缺数据的状态下每轮 Run 都跑一条注定 SKIPPED 的用例。

本模块不执行任何请求：执行统一走 ``RunService`` + executor 的安全分支。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.business_rule import BusinessRule
from app.features.business.models.business_state import BusinessState
from app.features.security_testing.models import (
    SecurityCase,
    SecurityMutationRule,
    SecurityPlan,
    SecurityStrategy,
)
from app.features.security_testing.runtime import business_plan as bp
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.features.security_testing.schemas import (
    MAX_PREVIEW_ITEMS,
    MUTATION_TYPES,
    MutationConfig,
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanPreviewItem,
    PlanPreviewRequest,
    PlanPreviewResponse,
    SecurityPlanRead,
    validate_no_script_keys,
)
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.fixture import Fixture
from app.features.test_management.models.test_case import TestCase
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_SECURITY_BASELINE_NOT_FOUND,
    CODE_SECURITY_MUTATION_INVALID,
    CODE_SECURITY_MUTATION_NOT_ALLOWED,
    CODE_SECURITY_PLAN_STATE_INVALID,
    AppError,
    bad_request,
    not_found,
)

__all__ = ["PlanService"]


class PlanService:
    """安全计划服务。所有方法负责 commit。"""

    # ------------------------------------------------------------------ 预览

    @staticmethod
    def preview(
        db: Session, project_id: int, body: PlanPreviewRequest, *, actor: User
    ) -> PlanPreviewResponse:
        """按目标 + 策略展开成预览项，写一条 DRAFT 计划。"""
        get_project_or_404(db, project_id, actor)
        if body.environment_id is not None:
            resolve_project_environment(db, project_id, body.environment_id)

        target_type, api_id, baseline_case, business_action_id = _resolve_target(db, project_id, body)
        strategy_rows = _load_strategies(db, project_id, body.strategy_ids)
        if not strategy_rows:
            raise bad_request("所选策略不存在或已停用")

        available = _available_fixture_keys(db, baseline_case.id if baseline_case is not None else None)
        target_method = _method_of(db, api_id, baseline_case)
        baseline_name = baseline_case.name if baseline_case is not None else (
            str(getattr(_api_name(db, api_id), "name", "") or f"API {api_id}")
        )

        items: list[dict[str, Any]] = []
        for strategy in strategy_rows:
            rules = (
                db.query(SecurityMutationRule)
                .filter(
                    SecurityMutationRule.strategy_id == strategy.id,
                    SecurityMutationRule.enabled.is_(True),
                )
                .order_by(SecurityMutationRule.sort.asc(), SecurityMutationRule.id.asc())
                .all()
            )
            for rule in rules:
                # index 在 extend 之前取：预览项顺序就是 confirm 的寻址依据。
                items.extend(
                    _items_for_rule(
                        db,
                        rule=rule,
                        strategy=strategy,
                        project_id=project_id,
                        target_name=baseline_name,
                        method=target_method,
                        api_id=api_id,
                        baseline_case_id=baseline_case.id if baseline_case is not None else None,
                        business_action_id=business_action_id,
                        target_type=target_type,
                        available_fixtures=available,
                        index=len(items),
                    )
                )

        truncated = len(items) > MAX_PREVIEW_ITEMS
        preview_items = items[:MAX_PREVIEW_ITEMS]

        plan = SecurityPlan(
            project_id=project_id,
            name=str(body.name or f"安全测试计划-{target_type.lower()}").strip()[:200],
            target_type=target_type,
            api_id=api_id,
            baseline_case_id=baseline_case.id if baseline_case is not None else None,
            business_action_id=business_action_id,
            strategy_ids=[strategy.id for strategy in strategy_rows],
            status="DRAFT",
            preview_json={"items": preview_items, "truncated": truncated, "total": len(items)},
            estimated_count=len(items),
            environment_id=body.environment_id,
            created_by=actor.id,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return PlanPreviewResponse(
            plan_id=plan.id,
            status=plan.status,
            estimated_count=len(items),
            truncated=truncated,
            baseline_case_id=plan.baseline_case_id,
            baseline_case_name=baseline_case.name if baseline_case is not None else None,
            items=[PlanPreviewItem(**item) for item in preview_items],
        )

    # ------------------------------------------------------------------ 确认

    @staticmethod
    def confirm(
        db: Session, plan_id: int, body: PlanConfirmRequest, *, actor: User
    ) -> PlanConfirmResponse:
        """把选中的预览项写成安全用例。"""
        require_writable_project(db, _plan_project_id(db, plan_id), actor)
        plan = _get_plan_or_404(db, plan_id)
        if plan.status != "DRAFT":
            raise AppError(
                f"该计划已经是 {plan.status}，不能重复确认",
                status_code=400,
                code=CODE_SECURITY_PLAN_STATE_INVALID,
            )

        preview = plan.preview_json or {}
        items: list[dict[str, Any]] = list(preview.get("items") or [])
        accepted = [int(i) for i in body.accepted_item_indexes]
        created_ids: list[int] = []
        skipped = 0

        for index in accepted:
            if not any(int(item.get("index") or 0) == index for item in items):
                skipped += 1
                continue
            item = _item_at(items, index)
            blocked = bool(item.get("blocked_reason"))
            case, security_case = _write_case(
                db,
                plan=plan,
                item=item,
                actor=actor,
                enabled=not blocked,
            )
            created_ids.append(case.id)

        plan.status = "CONFIRMED"
        plan.confirmed_by = actor.id
        plan.confirmed_at = datetime.now()
        plan.updated_at = datetime.now()
        db.add(plan)
        db.commit()
        return PlanConfirmResponse(
            plan_id=plan.id,
            status=plan.status,
            created_case_ids=created_ids,
            created_count=len(created_ids),
            skipped_count=skipped,
        )

    # ------------------------------------------------------------------ 丢弃

    @staticmethod
    def discard(db: Session, plan_id: int, *, actor: User) -> SecurityPlanRead:
        """丢弃计划：只允许 DRAFT，确认过的计划不能回头改。"""
        require_writable_project(db, _plan_project_id(db, plan_id), actor)
        plan = _get_plan_or_404(db, plan_id)
        if plan.status != "DRAFT":
            raise AppError(
                f"该计划已经是 {plan.status}，不能丢弃",
                status_code=400,
                code=CODE_SECURITY_PLAN_STATE_INVALID,
            )
        plan.status = "DISCARDED"
        plan.updated_at = datetime.now()
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return SecurityPlanRead.model_validate(plan)


# --------------------------------------------------------------------------- 辅助


def _plan_project_id(db: Session, plan_id: int) -> int:
    """获取计划项目标识。"""
    plan = _get_plan_or_404(db, plan_id)
    return plan.project_id


def _get_plan_or_404(db: Session, plan_id: int) -> SecurityPlan:
    """获取计划或。"""
    plan = db.get(SecurityPlan, plan_id)
    if plan is None:
        raise not_found("安全计划不存在")
    return plan


def _item_at(items: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """按索引读取计划条目，索引越界时返回空值。"""
    for item in items:
        if int(item.get("index") or 0) == index:
            return item
    raise bad_request(f"预览里没有第 {index} 条计划项")


def _resolve_target(
    db: Session, project_id: int, body: PlanPreviewRequest
) -> tuple[str, int | None, TestCase | None, int | None]:
    """三个目标必须且只能给一个；都校验项目归属，避免跨项目引用。"""
    provided = [
        name
        for name, value in (
            ("baseline_case_id", body.baseline_case_id),
            ("api_id", body.api_id),
            ("business_action_id", body.business_action_id),
        )
        if value is not None
    ]
    if len(provided) != 1:
        raise bad_request("baseline_case_id、api_id、business_action_id 必须且只能提供一个")

    if body.baseline_case_id is not None:
        case = db.get(TestCase, body.baseline_case_id)
        if case is None or case.project_id != project_id:
            raise not_found("基线用例不存在")
        return "TEST_CASE", case.api_id, case, case.business_action_id

    if body.api_id is not None:
        iface = db.get(ApiInterface, body.api_id)
        if iface is None or iface.project_id != project_id:
            raise not_found("目标接口不存在")
        baseline_case = _baseline_for_api(db, project_id, iface.id)
        if baseline_case is None:
            raise AppError(
                f"接口 {iface.id} 下没有可作为基线的启用用例，"
                "请先创建或启用一条功能用例",
                status_code=404,
                code=CODE_SECURITY_BASELINE_NOT_FOUND,
            )
        return "API", iface.id, baseline_case, None

    action = db.get(BusinessAction, body.business_action_id)
    if action is None:
        raise not_found("业务动作不存在")
    flow = db.get(BusinessFlow, action.flow_id)
    if flow is None or flow.project_id != project_id:
        raise not_found("业务动作不存在")
    return "BUSINESS_ACTION", None, _baseline_for_action(db, project_id, action.id), action.id


def _baseline_for_api(db: Session, project_id: int, api_id: int) -> TestCase | None:
    """接口目标下的基线用例。

    排除安全用例（不能用变异用例当基线）与业务动作型用例，取最近更新的一条启用
    ACTIVE 用例。runner 的变异请求全靠基线 step / data / fixture 组装，没有基线的
    计划项只能得到 INCONCLUSIVE，因此在目标层就给出明确错误而不是生成空计划。
    """
    return (
        db.query(TestCase)
        .filter(
            TestCase.project_id == project_id,
            TestCase.api_id == api_id,
            TestCase.target_type == "API",
            TestCase.case_type != "SECURITY",
            TestCase.status == "ACTIVE",
            TestCase.enabled.is_(True),
        )
        .order_by(TestCase.updated_at.desc(), TestCase.id.desc())
        .first()
    )


def _baseline_for_action(db: Session, project_id: int, action_id: int) -> TestCase | None:
    """业务动作目标下的基线用例：先看挂在动作上的，再看绑定接口下的。

    业务动作型变异（BUSINESS_STATE / SEQUENCE_BYPASS）在 Phase 1 执行时按设计跳过，
    所以这里拿不到基线只返回 None，由 runner 在执行时说明原因，不在计划阶段阻断。
    """
    row = (
        db.query(TestCase)
        .filter(
            TestCase.project_id == project_id,
            TestCase.business_action_id == action_id,
            TestCase.case_type != "SECURITY",
            TestCase.status == "ACTIVE",
            TestCase.enabled.is_(True),
        )
        .order_by(TestCase.updated_at.desc(), TestCase.id.desc())
        .first()
    )
    if row is not None:
        return row
    binding = (
        db.query(BusinessBinding)
        .filter(BusinessBinding.business_action_id == action_id)
        .order_by(BusinessBinding.id.asc())
        .first()
    )
    api_id = getattr(binding, "api_id", None) if binding is not None else None
    return _baseline_for_api(db, project_id, api_id) if api_id is not None else None


def _load_strategies(
    db: Session, project_id: int, strategy_ids: list[int]
) -> list[SecurityStrategy]:
    """系统模板跨项目可见；项目自定义必须在同一个项目里。"""
    rows = (
        db.query(SecurityStrategy)
        .filter(
            SecurityStrategy.id.in_(strategy_ids),
            SecurityStrategy.enabled.is_(True),
            (SecurityStrategy.project_id == None) | (SecurityStrategy.project_id == project_id),  # noqa: E711
        )
        .all()
    )
    seen: set[int] = set()
    ordered: list[SecurityStrategy] = []
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        ordered.append(row)
    return ordered


def _available_fixture_keys(db: Session, case_id: int | None) -> set[str] | None:
    """基线用例声明的 Fixture key。没有基线用例时返回 None（未知，不阻断）。"""
    if case_id is None:
        return None
    rows = (
        db.query(Fixture.fixture_key)
        .join(TestCaseFixture, TestCaseFixture.fixture_id == Fixture.id)
        .filter(TestCaseFixture.test_case_id == case_id)
        .all()
    )
    return {row[0] for row in rows if row[0]}


def _api_name(db: Session, api_id: int | None) -> Any:
    """组合 API 名称、方法和路径用于展示。"""
    return db.get(ApiInterface, api_id) if api_id is not None else None


def _method_of(db: Session, api_id: int | None, case: TestCase | None) -> str | None:
    """目标方法：接口声明优先，其次用例 step 配置。"""
    if api_id is not None:
        iface = db.get(ApiInterface, api_id)
        if iface is not None and getattr(iface, "method", None):
            return str(iface.method).upper()
    return None


def _items_for_rule(
    db: Session,
    *,
    rule: SecurityMutationRule,
    strategy: SecurityStrategy,
    project_id: int,
    target_name: str,
    method: str | None,
    api_id: int | None,
    baseline_case_id: int | None,
    business_action_id: int | None,
    target_type: str,
    available_fixtures: set[str] | None,
    index: int,
) -> list[dict[str, Any]]:
    """一条规则展开成一条或多条预览项。"""
    validate_no_script_keys(rule.mutation_config, what="变异规则配置")
    mutation_type = str(rule.mutation_type or "")
    if mutation_type not in MUTATION_TYPES:
        raise AppError(
            f"规则 {rule.name} 的变异类型 {mutation_type} 不在白名单内",
            status_code=400,
            code=CODE_SECURITY_MUTATION_INVALID,
        )

    if mutation_type == "REPLAY_SAME_REQUEST":
        item = bp.replay_item(
            rule=rule,
            target=target_name,
            index=index,
            method=method,
            strategy=strategy,
            target_type=target_type,
            api_id=api_id,
            business_action_id=business_action_id,
            available_fixtures=available_fixtures,
        )
        return [item] if item else []

    if mutation_type == "DUPLICATE_SUBMIT":
        return _duplicate_items(
            db, rule=rule, strategy=strategy, index=index,
            method=method, available_fixtures=available_fixtures, project_id=project_id,
        )
    if mutation_type == "BUSINESS_STATE":
        return _business_state_items(
            db, rule=rule, strategy=strategy, index=index,
            available_fixtures=available_fixtures, project_id=project_id,
        )
    if mutation_type == "SEQUENCE_BYPASS":
        return _sequence_items(
            db, rule=rule, strategy=strategy, index=index,
            available_fixtures=available_fixtures, project_id=project_id,
        )

    return [
        bp.build_item(
            index=index,
            mutation_type=mutation_type,
            target=target_name,
            method=method,
            rule=rule,
            strategy=strategy,
            target_type=target_type,
            api_id=api_id,
            business_action_id=business_action_id,
            available_fixtures=available_fixtures,
        )
    ]


def _project_actions(db: Session, project_id: int) -> list[BusinessAction]:
    """读取项目内配置的业务动作。"""
    return (
        db.query(BusinessAction)
        .join(BusinessFlow, BusinessFlow.id == BusinessAction.flow_id)
        .filter(BusinessFlow.project_id == project_id)
        .order_by(BusinessFlow.id.asc(), BusinessAction.sort.asc(), BusinessAction.id.asc())
        .all()
    )


def _states_for_actions(
    db: Session, actions: list[BusinessAction]
) -> dict[int, BusinessState]:
    """计算业务动作执行后的状态集合。"""
    ids = [action.id for action in actions]
    if not ids:
        return {}
    rows = (
        db.query(BusinessState)
        .filter(BusinessState.action_id.in_(ids))
        .order_by(BusinessState.id.asc())
        .all()
    )
    return {row.action_id: row for row in rows if row.action_id in ids}


def _duplicate_items(
    db: Session,
    *,
    rule,
    strategy,
    index: int,
    method: str | None,
    available_fixtures,
    project_id: int,
) -> list[dict[str, Any]]:
    """DUPLICATE_SUBMIT 只挂到创建/提交/支付类动作或声明了幂等的动作。"""
    actions = _project_actions(db, project_id)
    rule_types = [
        row[0]
        for row in (
            db.query(BusinessRule.rule_type)
            .join(BusinessFlow, BusinessFlow.id == BusinessRule.flow_id)
            .filter(BusinessFlow.project_id == project_id, BusinessRule.enabled.is_(True))
            .all()
        )
    ]
    out: list[dict[str, Any]] = []
    for action in actions:
        item = bp.duplicate_submit_item(
            rule=rule,
            action=action,
            rule_types=rule_types,
            index=index + len(out),
            method=method,
            strategy=strategy,
            business_action_id=action.id,
            available_fixtures=available_fixtures,
        )
        if item is not None:
            out.append(item)
    return out


def _business_state_items(
    db: Session, *, rule, strategy, index: int, available_fixtures, project_id: int
) -> list[dict[str, Any]]:
    """构造业务状态检查项。"""
    actions = _project_actions(db, project_id)
    states = _states_for_actions(db, actions)
    out: list[dict[str, Any]] = []
    for action in actions:
        item = bp.business_state_item(
            rule=rule,
            action=action,
            state=states.get(action.id),
            index=index + len(out),
            strategy=strategy,
            business_action_id=action.id,
            available_fixtures=available_fixtures,
        )
        if item is not None:
            out.append(item)
    return out


def _sequence_items(
    db: Session, *, rule, strategy, index: int, available_fixtures, project_id: int
) -> list[dict[str, Any]]:
    """跳步项指向「被跳过步骤之后」的动作；不给 execute_flow 加 skip 参数。"""
    actions = _project_actions(db, project_id)
    states = _states_for_actions(db, actions)
    out: list[dict[str, Any]] = []
    for action in actions:
        item = bp.sequence_bypass_item(
            rule=rule,
            skipped_action=action,
            actions=actions,
            index=index + len(out),
            strategy=strategy,
            skipped_state=states.get(action.id),
            available_fixtures=available_fixtures,
        )
        if item is not None:
            out.append(item)
    return out


def _write_case(
    db: Session, *, plan: SecurityPlan, item: dict[str, Any], actor: User, enabled: bool
) -> tuple[TestCase, SecurityCase]:
    """写一条 case_type='SECURITY' 的用例与扩展行。

    不复制基线用例的 step 文本作为第二份事实来源：``baseline_case_id`` 指向原用例，
    runner 每次执行时重新读取基线配置。
    """
    config = dict(item.get("mutation_config") or {})
    validate_no_script_keys(config, what="变异配置")
    if config:
        MutationConfig.model_validate(config)

    target_type = "BUSINESS_ACTION" if item.get("business_action_id") else "API"
    case_name = str(item.get("name") or f"安全用例-{item.get('mutation_type')}")[:200]
    case = TestCase(
        project_id=plan.project_id,
        name=case_name,
        description=f"基线用例 {plan.baseline_case_id or '-'} 的安全变异：{item.get('mutation_type')}",
        case_type="SECURITY",
        target_type=target_type,
        api_id=item.get("api_id"),
        business_action_id=item.get("business_action_id"),
        status="ACTIVE",
        enabled=enabled,
        created_by=actor.id,
    )
    db.add(case)
    db.flush()

    security_case = SecurityCase(
        project_id=plan.project_id,
        test_case_id=case.id,
        plan_id=plan.id,
        baseline_case_id=plan.baseline_case_id,
        strategy_id=item.get("source_strategy_id"),
        rule_id=item.get("source_rule_id"),
        api_id=item.get("api_id"),
        business_action_id=item.get("business_action_id"),
        mutation_type=str(item.get("mutation_type") or ""),
        mutation_config=config,
        security_expectation=str(item.get("expectation") or "EXPECTED_DENY"),
        risk_level=str(item.get("risk_level") or ""),
        confirmation_required=bool(item.get("confirmation_required")),
    )
    db.add(security_case)
    db.flush()
    return case, security_case
