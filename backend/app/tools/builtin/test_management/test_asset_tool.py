"""Agent Tool 层：测试资产读取 / 保存 + 去重（§32）。

读去重走 ORM：`PointService.list_points` / `CaseService.list_cases` 无 target 维度
过滤，而 ContextLoader 需要「同项目 + 同目标」的已有资产作为去重上下文，故在 Tool 层
直接查询（§32 允许 Tool 层 ORM）。

保存经 `PointService` / `CaseService`，携带 `source_type="AI"` + `agent_session_id` +
`generation_version`（§11 追溯）。**不**改动现有 service 的公共方法签名。

去重口径：`semantic_key` 归一化名称（小写 + 去空白与常见标点），仅用于「是否已存在
相似测试点 / 用例」的判断，不落库。
"""

from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.tools.builtin.test_management.contracts import TestCaseDraft, TestPointDraft
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_flow import BusinessFlow
from app.features.mocking.models import MockEndpoint, MockScenario
from app.features.mocking.schemas import TestCaseMockCreate, TestCaseMocksReplace
from app.features.mocking.services.test_case_mock_service import TestCaseMockService
from app.features.test_data.models.fixture import Fixture
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.schemas import (
    TestCaseCreate,
    TestCaseFixtureItem,
    TestCaseFixtureReplace,
    TestPointCreate,
)
from app.platform.projects.services.access_service import get_project_or_404
from app.features.test_management.services.case_service import CaseService
from app.features.test_management.services.point_service import PointService
from app.features.test_management.services.strategy_service import StrategyService
from app.core.models.identity import User
from app.core.http.errors import not_found


_STRATEGY = StrategyService()
_POINT = PointService()
_CASE = CaseService()
_MOCK_CASE = TestCaseMockService()

# 被测对象类型 → 对应 id 列名（TestPoint / TestCase 两模型列名一致）。
_TARGET_COLUMN_BY_TYPE = {
    "API": "api_id",
    "BUSINESS_FLOW": "business_flow_id",
    "BUSINESS_ACTION": "business_action_id",
}

# 归一化用：把分隔符 / 标点 / 空白压掉，比较「同一件事的不同写法」。
_NAME_NORMALIZE = re.compile(r"[\s_\-–—\[\]【】()（）{}<>《》:：,，.。/\\|\"'’‘!?？！;；]+")


def _validate_resource_ids(
    db: Session,
    project_id: int,
    api_id: int | None,
    business_flow_id: int | None,
    business_action_id: int | None,
) -> None:
    """校验 LLM 生成的资源 ID 属于本项目（§33 跨项目 404）。

    LLM 可能幻觉出其他项目的资源 ID，若不校验则测试资产会引用跨项目资源。
    跨项目统一 404（不暴露资源存在性）。
    """
    if api_id is not None:
        api = db.get(ApiInterface, api_id)
        if api is None or api.project_id != project_id:
            raise not_found("引用的 API 不存在")
    if business_flow_id is not None:
        flow = db.get(BusinessFlow, business_flow_id)
        if flow is None or flow.project_id != project_id:
            raise not_found("引用的业务流程不存在")
    if business_action_id is not None:
        action = db.get(BusinessAction, business_action_id)
        if action is None:
            raise not_found("引用的业务动作不存在")
        flow = db.get(BusinessFlow, action.flow_id)
        if flow is None or flow.project_id != project_id:
            raise not_found("引用的业务动作不存在")


def _validate_step_target_id(db: Session, project_id: int, target_id: int) -> None:
    """校验 TestStep.target_id 属于本项目（§33 跨项目 404）。

    target_id 可能是 API / BusinessFlow / BusinessAction 的 ID，逐一尝试匹配。
    跨项目统一 404。
    """
    # 尝试 API
    api = db.get(ApiInterface, target_id)
    if api is not None and api.project_id == project_id:
        return
    # 尝试 BusinessFlow
    flow = db.get(BusinessFlow, target_id)
    if flow is not None and flow.project_id == project_id:
        return
    # 尝试 BusinessAction（通过 flow 间接校验项目归属）
    action = db.get(BusinessAction, target_id)
    if action is not None:
        flow = db.get(BusinessFlow, action.flow_id)
        if flow is not None and flow.project_id == project_id:
            return
    raise not_found("测试步骤引用的目标不存在")


def semantic_key(name: str | None) -> str:
    """归一化名称用于去重比较（小写 + 去空白与常见标点）。仅用于判断，不落库。"""
    return _NAME_NORMALIZE.sub("", (name or "").strip().lower())


def get_strategies(db: Session, project_id: int, user: User) -> dict:
    """取项目内测试策略列表。

    返回的策略 ID 是 LLM 唯一可引用的 `strategy_id` 来源（prompt 明确禁止编造 ID）；
    生成后由 ValidatorNode 复核每个 strategy_id 是否在本列表内。
    """
    get_project_or_404(db, project_id, user)
    resp = _STRATEGY.list_strategies(db, project_id, user, page=1, page_size=9999)
    return resp.model_dump(mode="json")


def _target_filter(model, target_type: str, target_id: int | None):
    """按 target_type + target_id 构造过滤条件；类型未知或 target_id 为空返回 None。"""
    col_name = _TARGET_COLUMN_BY_TYPE.get(target_type)
    if col_name is None or target_id is None:
        return None
    return getattr(model, col_name) == target_id


def get_existing_points(
    db: Session,
    project_id: int,
    user: User,
    *,
    target_type: str,
    target_id: int | None,
    limit: int = 50,
) -> list[dict]:
    """取目标下已有测试点（去重上下文），每条附 `semantic_key` 供 generator 比对。

    排除 DEPRECATED：已废弃的测试点不应阻止重新生成同名点。
    """
    get_project_or_404(db, project_id, user)
    cond = _target_filter(TestPoint, target_type, target_id)
    q = db.query(TestPoint).filter(
        TestPoint.project_id == project_id,
        TestPoint.target_type == target_type,
        TestPoint.status != "DEPRECATED",
    )
    if cond is not None:
        q = q.filter(cond)
    rows = q.order_by(TestPoint.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "semantic_key": semantic_key(r.name),
            "priority": r.priority,
            "description": r.description,
            "status": r.status,
        }
        for r in rows
    ]


def get_existing_cases(
    db: Session,
    project_id: int,
    user: User,
    *,
    target_type: str,
    target_id: int | None,
    limit: int = 50,
) -> list[dict]:
    """取目标下已有测试用例（去重上下文），每条附 `semantic_key`。"""
    get_project_or_404(db, project_id, user)
    cond = _target_filter(TestCase, target_type, target_id)
    q = db.query(TestCase).filter(
        TestCase.project_id == project_id,
        TestCase.target_type == target_type,
        TestCase.status != "DEPRECATED",
    )
    if cond is not None:
        q = q.filter(cond)
    rows = q.order_by(TestCase.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "semantic_key": semantic_key(r.name),
            "priority": r.priority,
            "case_type": r.case_type,
            "status": r.status,
        }
        for r in rows
    ]


def save_points(
    db: Session,
    project_id: int,
    actor: User,
    drafts: list[TestPointDraft],
    *,
    agent_session_id: int,
    generation_version: int,
) -> list[dict]:
    """落库测试点，返回 `[{"id", "name"}]`（供节点写入 confirmed_point_ids）。

    逐条 `create_point`：重名会触发 `uq_test_point_project_name` → conflict（409），
    由节点层捕获并转成人类可读提示（而非静默丢弃）。
    """
    results: list[dict] = []
    for d in drafts:
        _validate_resource_ids(
            db, project_id, d.api_id, d.business_flow_id, d.business_action_id,
        )
        body = TestPointCreate(
            name=d.name,
            description=d.description,
            priority=d.priority,
            target_type=d.target_type,
            strategy_id=d.strategy_id,
            api_id=d.api_id,
            business_flow_id=d.business_flow_id,
            business_action_id=d.business_action_id,
            source_type="AI",
            agent_session_id=agent_session_id or None,
            generation_version=generation_version,
        )
        resp = _POINT.create_point(db, project_id, body, actor=actor)
        results.append({"id": resp.id, "name": resp.name})
    return results


def _rebase_assertion_steps(assertions, step_ids: list[int]):
    """把断言的 `step_id` 回填为真实 TestStep.id。

    LLM 无法预知自增主键，约定其 `step_id` 为「本用例 steps 列表的下标」（0 起）；
    越界 / 非整数 / 为 None 一律置空——断言不绑定具体步骤本身合法（§18 只要求
    有断言绑定到步骤时才校验 step 归属）。
    """
    rebased = []
    for a in assertions:
        ref = a.step_id
        step_id = step_ids[ref] if isinstance(ref, int) and 0 <= ref < len(step_ids) else None
        rebased.append(a.model_copy(update={"step_id": step_id}))
    return rebased


def _resolve_fixture_ids(db: Session, project_id: int, keys: list[str]) -> list[str]:
    """校验 required_fixtures 全部可见且 ACTIVE，返回去重后的 key 顺序。

    任一 key 缺失 → 404「当前缺少 XXX Fixture」，**整条用例不落库**（与现在子实体
    失败即 conflict 的粒度一致：已保存的前序用例保留，其他合法用例仍可保存）。
    这里只校验引用，绝不创建 Provider / Fixture，也不接触连接配置。
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in keys or []:
        key = (raw or "").strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    if not ordered:
        return []
    rows = (
        db.query(Fixture)
        .filter(
            Fixture.status == "ACTIVE",
            Fixture.fixture_key.in_(ordered),
            or_(Fixture.project_id == project_id, Fixture.scope == "GLOBAL"),
        )
        .all()
    )
    found = {r.fixture_key for r in rows}
    missing = [k for k in ordered if k not in found]
    if missing:
        raise not_found(f"当前缺少 {', '.join(missing)} Fixture")
    return ordered


def _resolve_mock_refs(
    db: Session, project_id: int, refs: list[Any],
) -> list[TestCaseMockCreate]:
    """校验 required_mocks 全部指向本项目已配置的 Scenario，返回可直接落库的声明。

    与 ``required_fixtures`` 同粒度：任一 scenario 缺失或跨项目 → 404「当前缺少
    Mock 场景 X」，**整条用例不落库**（已保存的前序用例保留，其他合法用例仍可保存）。
    这里只校验引用并补全 service/endpoint 归属，绝不创建 Service / Endpoint /
    Scenario，也不接触 Runtime Token。
    """
    ordered: list[int] = []
    seen: set[int] = set()
    scope_by_id: dict[int, str] = {}
    for ref in refs or []:
        sid = int(ref.mock_scenario_id)
        scope_by_id[sid] = str(getattr(ref, "scope", "EXECUTION") or "EXECUTION")
        if sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    if not ordered:
        return []

    rows = (
        db.query(MockScenario)
        .filter(MockScenario.id.in_(ordered), MockScenario.project_id == project_id)
        .all()
    )
    found = {r.id: r for r in rows}
    missing = [sid for sid in ordered if sid not in found]
    if missing:
        raise not_found(f"当前缺少 Mock 场景 {', '.join(str(s) for s in missing)}")

    out: list[TestCaseMockCreate] = []
    for i, sid in enumerate(ordered):
        scenario = found[sid]
        endpoint = db.get(MockEndpoint, scenario.mock_endpoint_id)
        # scenario 与 endpoint 同表族，仍显式校验 project 归属，防止孤立 / 错绑行。
        if endpoint is None or endpoint.project_id != project_id:
            raise not_found(f"Mock 场景 {sid} 关联的接口不存在")
        out.append(TestCaseMockCreate(
            mock_service_id=endpoint.mock_service_id,
            mock_endpoint_id=endpoint.id,
            mock_scenario_id=sid,
            scope=scope_by_id[sid],
            sort=i,
        ))
    return out


def save_cases(
    db: Session,
    project_id: int,
    actor: User,
    drafts: list[TestCaseDraft],
    *,
    agent_session_id: int,
    generation_version: int,
) -> list[dict]:
    """落库测试用例及其子实体，返回 `[{"id", "name", "test_point_id"}]`。

    顺序：case → preconditions → test_data → steps → assertions。断言的 step_id
    在步骤落库后按「步骤下标」回填（见 `_rebase_assertion_steps`）。
    子实体重名（如 test_data 同名）会触发唯一约束 → conflict，由节点层捕获。
    """
    results: list[dict] = []
    for d in drafts:
        _validate_resource_ids(
            db, project_id, d.api_id, d.business_flow_id, d.business_action_id,
        )
        # 先校验 Fixture / Mock 引用再建用例：引用缺失时整条不落库。
        fixture_keys = _resolve_fixture_ids(db, project_id, d.required_fixtures or [])
        mock_refs = _resolve_mock_refs(db, project_id, d.required_mocks or [])
        body = TestCaseCreate(
            name=d.name,
            description=d.description,
            priority=d.priority,
            case_type=d.case_type,
            target_type=d.target_type,
            test_point_id=d.test_point_id,
            api_id=d.api_id,
            business_flow_id=d.business_flow_id,
            business_action_id=d.business_action_id,
            source_type="AI",
            agent_session_id=agent_session_id or None,
            generation_version=generation_version,
        )
        case_resp = _CASE.create_case(db, project_id, body, actor=actor)
        case_id = case_resp.id
        if fixture_keys:
            _CASE.replace_fixtures(
                db, case_id,
                TestCaseFixtureReplace(
                    fixtures=[
                        TestCaseFixtureItem(fixture_key=k, sort=i)
                        for i, k in enumerate(fixture_keys)
                    ]
                ),
                actor=actor,
            )
        if mock_refs:
            _MOCK_CASE.replace_case_mocks(
                db, case_id, TestCaseMocksReplace(mocks=mock_refs), actor=actor,
            )
        for pre in d.preconditions:
            _CASE.create_precondition(db, case_id, pre, actor=actor)
        for data in d.test_data:
            _CASE.create_data(db, case_id, data, actor=actor)
        step_ids: list[int] = []
        for step in d.steps:
            if step.target_id is not None:
                _validate_step_target_id(db, project_id, step.target_id)
            step_resp = _CASE.create_step(db, case_id, step, actor=actor)
            step_ids.append(step_resp.id)
        for asn in _rebase_assertion_steps(d.assertions, step_ids):
            _CASE.create_assertion(db, case_id, asn, actor=actor)
        results.append({"id": case_id, "name": case_resp.name, "test_point_id": d.test_point_id})
    return results


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'get_strategies': ('runtime.test_asset.get_strategies', 'read'),
    'get_existing_points': ('runtime.test_asset.get_existing_points', 'read'),
    'get_existing_cases': ('test_asset.get_existing_cases', 'read'),
    'save_points': ('runtime.test_asset.save_points', 'write'),
    'save_cases': ('test_asset.save_cases', 'write'),
})
