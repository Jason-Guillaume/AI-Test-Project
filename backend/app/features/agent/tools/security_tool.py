"""Agent Tool 层：安全测试（Phase F，§十三）。

与 `execution_tool` / `report_tool` 同范式的薄封装，只做两件事：把 security_testing
的 service 结果转成可进 prompt 的 dict，以及保证权限边界由 service 自己校验。

工具清单即 §13.4，不另加：
- `list_strategies`：本项目启用的安全策略与规则摘要。Agent 只能从中选 `strategy_key`，
  不能生成或改写规则体。
- `preview_plan`：只算一遍，不写 TestCase。
- `confirm_plan`：**仅当** action 来自人工按钮（`confirm_security_plan`）时调用；
  对话链路里 Agent 不能自己确认。
- `list_findings` / `get_execution`：只读结果。

刻意不提供：执行任意 URL、改项目成员、改出站白名单、生成脚本、调用未登记 host；
`confirm_risk` 也不封装——高风险确认是路由层的 `confirm_security_risk` action，
不进 LLM 工具参数（§13.2）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.security_testing.models import SecurityCase
from app.features.security_testing.schemas import (
    FINDING_OPEN_STATUSES,
    PlanConfirmRequest,
    PlanPreviewRequest,
    SecurityExecutionRead,
    SecurityFindingListResponse,
)
from app.features.security_testing.services._access import get_project_or_404
from app.features.security_testing.services.execution_query_service import ExecutionQueryService
from app.features.security_testing.services.finding_service import FindingService
from app.features.security_testing.services.plan_service import PlanService
from app.features.security_testing.services.strategy_service import SecurityStrategyService
from app.models.identity import User

__all__ = [
    "list_strategies",
    "preview_plan",
    "confirm_plan",
    "security_case_status",
    "list_findings",
    "open_findings_brief",
    "get_execution",
    "OPEN_FINDING_BRIEF_FIELDS",
]

# 规则摘要里保留的字段：足够 Agent 选策略，但不把 mutation_config 塞进 prompt。
_RULE_BRIEF_FIELDS = (
    "id", "name", "mutation_type", "target_location", "target_field", "operator",
    "expected_security_behavior", "expected_status_codes", "severity", "enabled",
    "confirmation_required",
)

# Finding 摘要字段：不含 evidence，避免把响应体/差异带进 prompt（§十四）。
OPEN_FINDING_BRIEF_FIELDS = (
    "id", "title", "severity", "status", "api_id", "mutation_type", "test_run_id",
)

_STRATEGIES = SecurityStrategyService()
_PLAN = PlanService()
_FINDING = FindingService()
_EXECUTION = ExecutionQueryService()


def _pick(obj: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """按字段白名单取值（service 增列不会漏出额外字段）。"""
    return {field: obj.get(field) for field in fields}


def _rules_brief(strategy: Any) -> list[dict[str, Any]]:
    data = strategy.model_dump(mode="json")
    return [_pick(rule, _RULE_BRIEF_FIELDS) for rule in (data.get("rules") or [])]


def list_strategies(db: Session, project_id: int, user: User) -> list[dict[str, Any]]:
    """本项目启用的安全策略（含规则摘要），供 LLM 选 `strategy_key`。"""
    response = _STRATEGIES.list_strategies(
        db, project_id, actor=user, enabled=True, page=1, page_size=200,
    )
    return [
        {
            **_pick(strategy.model_dump(mode="json"), ("id", "strategy_key", "name", "category", "risk_level")),
            "rules": _rules_brief(strategy),
        }
        for strategy in response.items
    ]


def preview_plan(
    db: Session, project_id: int, user: User, *,
    strategy_ids: list[int],
    api_id: int | None = None,
    business_action_id: int | None = None,
    baseline_case_id: int | None = None,
    environment_id: int | None = None,
) -> dict[str, Any]:
    """生成安全计划预览：只算一遍，不写 TestCase。"""
    body = PlanPreviewRequest(
        api_id=api_id,
        business_action_id=business_action_id,
        baseline_case_id=baseline_case_id,
        strategy_ids=strategy_ids,
        environment_id=environment_id,
    )
    return _PLAN.preview(db, project_id, body, actor=user).model_dump(mode="json")


def confirm_plan(
    db: Session, plan_id: int, user: User, *, accepted_item_indexes: list[int] | None = None
) -> dict[str, Any]:
    """确认安全计划，把选中预览项写成 `case_type='SECURITY'` 用例。

    只应由 `confirm_security_plan` action（人工按钮）调用。
    """
    body = PlanConfirmRequest(accepted_item_indexes=list(accepted_item_indexes or []))
    return _PLAN.confirm(db, plan_id, body, actor=user).model_dump(mode="json")


def security_case_status(
    db: Session, project_id: int, user: User, *, test_case_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """TestCase id → 安全用例确认状态（高风险确认前的映射与展示用）。

    `confirm_risk` 用 SecurityCase 主键寻址，而 Agent 会话里流转的是 TestCase id，
    因此这里给一个只读的映射；不含 mutation_config（那是变异细节，不必进提示词）。
    """
    get_project_or_404(db, project_id, user)
    ids = [int(i) for i in test_case_ids]
    if not ids:
        return {}
    rows = (
        db.query(SecurityCase)
        .filter(SecurityCase.project_id == project_id, SecurityCase.test_case_id.in_(ids))
        .all()
    )
    return {
        row.test_case_id: {
            "security_case_id": row.id,
            "confirmation_required": bool(row.confirmation_required),
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        }
        for row in rows
    }


def list_findings(
    db: Session, project_id: int, user: User, *,
    status: str | None = None,
    api_id: int | None = None,
    test_run_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SecurityFindingListResponse:
    """读 Finding。给 Agent 的链路走 `_findings_brief`，只取摘要字段。"""
    return _FINDING.list_findings(
        db, project_id, user=user, status=status, api_id=api_id,
        test_run_id=test_run_id, page=page, page_size=page_size,
    )


def _findings_brief(response: SecurityFindingListResponse) -> list[dict[str, Any]]:
    return [_pick(item.model_dump(mode="json"), OPEN_FINDING_BRIEF_FIELDS) for item in response.items]


def open_findings_brief(
    db: Session, project_id: int, user: User, *,
    api_id: int | None = None,
    test_run_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """未关闭 Finding（OPEN + CONFIRMED）摘要，脱敏且不含 evidence。"""
    response = _FINDING.list_findings(
        db, project_id, user=user, statuses=list(FINDING_OPEN_STATUSES),
        api_id=api_id, test_run_id=test_run_id, page=1, page_size=min(max(limit, 1), 200),
    )
    return _findings_brief(response)


def get_execution(db: Session, security_execution_id: int, user: User) -> SecurityExecutionRead:
    """读一条安全执行结果（不可见项目与不存在共用 404）。"""
    return _EXECUTION.get_execution(db, security_execution_id, user=user)
