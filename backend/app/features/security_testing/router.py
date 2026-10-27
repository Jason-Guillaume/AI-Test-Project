"""Security Testing 管理面路由（开发计划 §16.1 / §16.2）。

单 APIRouter（无自身前缀），挂在 /api/v1 下。路径分两类：
- 项目资源：/projects/{project_id}/security-setting、/security-strategies、/security-cases、
  /security-runs、/security-findings
- 全局资源：/security-strategies/{id}(+/rules)、/security-rules/{id}、
  /security-plans/{id}、/security-cases/{id}、/security-findings/{id}、/security-executions/{id}

权限口径：读 viewer+；计划 / 用例 / 执行与高风险确认 member+；策略规则与 Finding
状态 editor+。系统内置策略/规则不可改（403）也不可删。
跨平台项目统一 404（隐藏存在性），项目可见但角色不足 403。
端点统一 sync def；service owns commit，本层不做 commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.security_testing.models import SecurityStrategy
from app.features.security_testing.schemas import (
    MutationRuleCreate,
    MutationRuleResponse,
    MutationRuleUpdate,
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanPreviewRequest,
    PlanPreviewResponse,
    RESERVED_CATEGORIES,
    SecurityCaseDetail,
    SecurityCaseListResponse,
    SecurityCaseRead,
    SecurityCaseUpdate,
    SecurityExecutionRead,
    SecurityFindingListResponse,
    SecurityFindingRead,
    SecurityFindingUpdate,
    SecurityPlanRead,
    SecurityRunRequest,
    SecuritySettingRead,
    SecuritySettingUpdate,
    SecurityStrategyCreate,
    SecurityStrategyListResponse,
    SecurityStrategyResponse,
    SecurityStrategyUpdate,
)
from app.features.security_testing.services.case_service import SecurityCaseService
from app.features.security_testing.services.execution_query_service import ExecutionQueryService
from app.features.security_testing.services.finding_service import FindingService
from app.features.security_testing.services.plan_service import PlanService
from app.features.security_testing.services.rule_service import (
    SecurityRuleService,
    get_manageable_rule,
)
from app.features.security_testing.services.setting_service import SecuritySettingService
from app.features.security_testing.services.strategy_service import (
    SecurityStrategyService,
)
from app.features.test_management.schemas import TestRunResponse
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["Security 管理"])

# 服务无状态，路由层复用单例。
_SETTING = SecuritySettingService()
_STRATEGY = SecurityStrategyService()
_RULE = SecurityRuleService()
_PLAN = PlanService()
_CASE = SecurityCaseService()
_FINDING = FindingService()
_EXECUTION = ExecutionQueryService()


# --------------------------------------------------------------------------- 项目设置


@router.get("/projects/{project_id}/security-setting", response_model=SecuritySettingRead)
def get_security_setting(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecuritySettingRead:
    """获取安全`setting`。"""
    return _SETTING.get_setting(db, project_id, user)


@router.put("/projects/{project_id}/security-setting", response_model=SecuritySettingRead)
def update_security_setting(
    project_id: int,
    body: SecuritySettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecuritySettingRead:
    """更新安全`setting`。"""
    return _SETTING.update_setting(db, project_id, body, actor=user)


# --------------------------------------------------------------------------- 策略


@router.get(
    "/projects/{project_id}/security-strategies", response_model=SecurityStrategyListResponse,
)
def list_security_strategies(
    project_id: int,
    category: str | None = Query(None),
    enabled: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyListResponse:
    """列出安全`strategies`。"""
    return _STRATEGY.list_strategies(
        db, project_id, actor=user, category=category, enabled=enabled,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/security-strategies",
    response_model=SecurityStrategyResponse, status_code=201,
)
def create_security_strategy(
    project_id: int,
    body: SecurityStrategyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    """创建安全策略。"""
    return _STRATEGY.create_strategy(db, project_id, body, actor=user)


@router.get("/security-strategies/{strategy_id}", response_model=SecurityStrategyResponse)
def get_security_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    """获取安全策略。"""
    return _STRATEGY.get_strategy(db, strategy_id, actor=user)


@router.patch("/security-strategies/{strategy_id}", response_model=SecurityStrategyResponse)
def update_security_strategy(
    strategy_id: int,
    body: SecurityStrategyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    """更新安全策略。"""
    return _STRATEGY.update_strategy(db, strategy_id, body, actor=user)


@router.delete("/security-strategies/{strategy_id}", status_code=204)
def delete_security_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除安全策略。"""
    _STRATEGY.delete_strategy(db, strategy_id, actor=user)


# --------------------------------------------------------------------------- 变异规则


@router.post(
    "/security-strategies/{strategy_id}/rules",
    response_model=MutationRuleResponse, status_code=201,
)
def create_mutation_rule(
    strategy_id: int,
    body: MutationRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MutationRuleResponse:
    """在策略下新增规则。预留攻击类策略下强制停用。"""
    strategy = _STRATEGY.get_manageable_strategy(db, strategy_id, actor=user)
    return _RULE.create_rule(
        db, strategy, body, actor=user,
        force_disabled=strategy.category in RESERVED_CATEGORIES,
    )


@router.patch("/security-rules/{rule_id}", response_model=MutationRuleResponse)
def update_mutation_rule(
    rule_id: int,
    body: MutationRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MutationRuleResponse:
    """更新变异规则。"""
    rule = get_manageable_rule(db, rule_id, actor=user)
    # 规则已校验过 editor+；这里只取策略行判断预留类别。
    strategy = db.get(SecurityStrategy, rule.strategy_id)
    return _RULE.update_rule(db, rule_id, body, actor=user, strategy=strategy)


@router.delete("/security-rules/{rule_id}", status_code=204)
def delete_mutation_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除变异规则。"""
    _RULE.delete_rule(db, rule_id, actor=user)


# --------------------------------------------------------------------------- 计划（§16.2）


@router.post(
    "/projects/{project_id}/security-plans/preview",
    response_model=PlanPreviewResponse,
)
def preview_security_plan(
    project_id: int,
    body: PlanPreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanPreviewResponse:
    """只算一遍，不写 TestCase。落库的 security_plan 是未确认快照。"""
    return _PLAN.preview(db, project_id, body, actor=user)


@router.post(
    "/security-plans/{plan_id}/confirm",
    response_model=PlanConfirmResponse,
)
def confirm_security_plan(
    plan_id: int,
    body: PlanConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanConfirmResponse:
    """把选中的预览项写成 case_type='SECURITY' 的用例 + security_case 扩展行。"""
    return _PLAN.confirm(db, plan_id, body, actor=user)


@router.post("/security-plans/{plan_id}/discard", response_model=SecurityPlanRead)
def discard_security_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityPlanRead:
    """放弃安全计划。"""
    return _PLAN.discard(db, plan_id, actor=user)


# --------------------------------------------------------------------------- 用例（§16.2）


@router.get(
    "/projects/{project_id}/security-cases", response_model=SecurityCaseListResponse,
)
def list_security_cases(
    project_id: int,
    api_id: int | None = Query(None),
    strategy_id: int | None = Query(None),
    mutation_type: str | None = Query(None),
    enabled: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseListResponse:
    """列出安全`cases`。"""
    return _CASE.list_cases(
        db, project_id, user=user, api_id=api_id, strategy_id=strategy_id,
        mutation_type=mutation_type, enabled=enabled, page=page, page_size=page_size,
    )


@router.get("/security-cases/{security_case_id}", response_model=SecurityCaseDetail)
def get_security_case(
    security_case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseDetail:
    """获取安全用例。"""
    return _CASE.get_case(db, security_case_id, user=user)


@router.patch("/security-cases/{security_case_id}", response_model=SecurityCaseRead)
def update_security_case(
    security_case_id: int,
    body: SecurityCaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseRead:
    """只允许改启用状态；扩展行没有 enabled 列，事实来源是 test_case。"""
    return _CASE.update_case(db, security_case_id, body, actor=user)


@router.post(
    "/security-cases/{security_case_id}/confirm-risk", response_model=SecurityCaseRead,
)
def confirm_security_risk(
    security_case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseRead:
    """高风险确认只能人工走这个端点；Agent 工具不调用它。"""
    return _CASE.confirm_risk(db, security_case_id, actor=user)


@router.post("/projects/{project_id}/security-runs", response_model=TestRunResponse)
def run_security_cases(
    project_id: int,
    body: SecurityRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestRunResponse:
    """唯一的批量执行入口：内部临时 TestPlan + Suite，复用既有 RunService。"""
    return _CASE.run_security_cases(db, project_id, body, actor=user)


# --------------------------------------------------------------------------- 执行记录


@router.get(
    "/security-executions/{security_execution_id}", response_model=SecurityExecutionRead,
)
def get_security_execution(
    security_execution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityExecutionRead:
    """从 test-runs 的 case_execution.context_json.security_execution_id 反查。"""
    return _EXECUTION.get_execution(db, security_execution_id, user=user)


# --------------------------------------------------------------------------- 安全发现项（§16.2）Finding


@router.get(
    "/projects/{project_id}/security-findings", response_model=SecurityFindingListResponse,
)
def list_security_findings(
    project_id: int,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    api_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityFindingListResponse:
    """列出安全`findings`。"""
    return _FINDING.list_findings(
        db, project_id, user=user, severity=severity, status=status,
        api_id=api_id, page=page, page_size=page_size,
    )


@router.get("/security-findings/{finding_id}", response_model=SecurityFindingRead)
def get_security_finding(
    finding_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityFindingRead:
    """获取安全发现项。"""
    return _FINDING.get_finding(db, finding_id, user=user)


@router.patch("/security-findings/{finding_id}", response_model=SecurityFindingRead)
def update_security_finding(
    finding_id: int,
    body: SecurityFindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityFindingRead:
    """只允许改状态；非法迁移 400。改状态需要 editor+。"""
    return _FINDING.update_status(db, finding_id, body, actor=user)
