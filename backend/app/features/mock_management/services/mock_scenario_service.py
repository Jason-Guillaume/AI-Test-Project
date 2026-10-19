"""MockScenario 服务层：场景 + Matcher + 默认场景 + 试跑（§七-§九 / §三十三）。

- (mock_endpoint_id, scenario_key) 唯一（409）。
- behavior_type ∈ MOCK_BEHAVIOR_TYPES；delay_ms 上限 60s（MOCK_TIMEOUT_TOO_LARGE，§七）。
- is_default：同 Endpoint 只允许一个（部分唯一索引）；设为 true 时先清同 Endpoint 旧默认。
- Matcher 整体替换（``PUT /scenarios/{id}/matchers``，与 Fixture steps 同款重建语义）。
- ``set_default``：显式置默认；``duplicate``：复制场景（含 matchers，新 scenario_key）。
- ``test_scenario``：模拟一个请求，跑 Matcher + Response Builder，不真实调用被测系统（§三十三）。

service owns commit。
"""

from __future__ import annotations

import re
import time

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.mock_management.matchers import (
    RequestSnapshot,
    evaluate_matchers,
    match_path,
)
from app.features.mock_management.models import (
    MockEndpoint,
    MockMatcher,
    MockScenario,
)
from app.features.mock_management.runtime.response_builder import (
    MOCK_RUNTIME_MAX_TIMEOUT,
    build_response,
)
from app.features.mock_management.schemas import (
    MOCK_BEHAVIOR_TYPES,
    MOCK_MATCHER_OPERATORS,
    MOCK_MATCHER_SOURCES,
    SCENARIO_KEY_PATTERN,
    MockMatchersReplace,
    MockScenarioCreate,
    MockScenarioListResponse,
    MockScenarioResponse,
    MockScenarioUpdate,
    ScenarioTestRequest,
    ScenarioTestResponse,
)
from app.features.mock_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_endpoint_project_id,
    resolve_scenario_project_id,
)
from app.features.mock_management.services._response import (
    scenario_response,
    scenarios_response,
)
from app.features.test_data.runtime.variable_resolver import RequestContext
from app.models.identity import User
from app.shared.errors import (
    CODE_MOCK_MATCHER_INVALID,
    CODE_MOCK_TIMEOUT_TOO_LARGE,
    AppError,
    bad_request,
    conflict,
    not_found,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _raise_not_found(message: str = "Mock 场景不存在") -> None:
    raise not_found(message)


class MockScenarioService:
    """MockScenario CRUD + Matcher + 默认 + 试跑。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 列表 / 详情

    def list_scenarios(
        self, db: Session, endpoint_id: int, user: User, *,
        keyword: str | None = None, enabled: bool | None = None,
        is_default: bool | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MockScenarioListResponse:
        endpoint = self._get_endpoint_or_404(db, endpoint_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(MockScenario).filter(MockScenario.mock_endpoint_id == endpoint.id)
        if enabled is not None:
            q = q.filter(MockScenario.enabled.is_(enabled))
        if is_default is not None:
            q = q.filter(MockScenario.is_default.is_(is_default))
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(
                or_(
                    MockScenario.name.ilike(f"%{kw}%"),
                    MockScenario.scenario_key.ilike(f"%{kw}%"),
                )
            )
        total = int(q.count())
        items = (
            q.order_by(MockScenario.priority.desc(), MockScenario.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return MockScenarioListResponse(
            items=scenarios_response(db, items),
            total=total, page=page, page_size=page_size,
        )

    def get_scenario(self, db: Session, scenario_id: int, user: User) -> MockScenarioResponse:
        row = self._get_or_404(db, scenario_id, user)
        return scenario_response(db, row)

    # ---------------------------------------------------------------- 创建 / 删除

    def create_scenario(
        self, db: Session, endpoint_id: int, body: MockScenarioCreate, *, actor: User,
    ) -> MockScenarioResponse:
        endpoint = self._get_endpoint_writable(db, endpoint_id, actor)
        self._validate_body(body)
        key = (body.scenario_key or "").strip()
        if not re.fullmatch(SCENARIO_KEY_PATTERN, key):
            raise conflict(f"scenario_key 必须匹配 {SCENARIO_KEY_PATTERN}")
        if (
            db.query(MockScenario)
            .filter(
                MockScenario.mock_endpoint_id == endpoint.id,
                MockScenario.scenario_key == key,
            )
            .first()
            is not None
        ):
            raise conflict("同接口下 scenario_key 已存在")

        # is_default：部分唯一索引兜底；这里先清同 Endpoint 旧默认，避免 IntegrityError。
        if body.is_default:
            self._clear_other_defaults(db, endpoint.id, exclude_id=None)

        scenario = MockScenario(
            project_id=endpoint.project_id,
            mock_endpoint_id=endpoint.id,
            name=(body.name or "").strip(),
            scenario_key=key,
            description=(body.description or "").strip() or None,
            enabled=body.enabled,
            is_default=body.is_default,
            priority=body.priority,
            behavior_type=body.behavior_type,
            delay_ms=body.delay_ms,
            status_code=body.status_code,
            response_headers=body.response_headers,
            response_body=body.response_body,
            response_template=body.response_template,
            created_by=actor.id,
        )
        db.add(scenario)
        db.flush()
        for m in body.matchers:
            self._validate_matcher(m)
            db.add(self._matcher_row(scenario.id, endpoint.project_id, m))
        db.commit()
        db.refresh(scenario)
        return scenario_response(db, scenario)

    def delete_scenario(self, db: Session, scenario_id: int, *, actor: User) -> None:
        from app.features.mock_management.models import TestCaseMock

        scenario = self._get_writable_or_404(db, scenario_id, actor)
        ref_count = int(
            db.query(TestCaseMock.id).filter(TestCaseMock.mock_scenario_id == scenario.id).count()
        )
        if ref_count:
            raise conflict(f"该场景正被 {ref_count} 条用例 Mock 依赖引用，请先在用例上移除")
        db.delete(scenario)
        db.commit()

    # ---------------------------------------------------------------- 更新 + Matcher

    def update_scenario(
        self, db: Session, scenario_id: int, body: MockScenarioUpdate, *, actor: User,
    ) -> MockScenarioResponse:
        scenario = self._get_writable_or_404(db, scenario_id, actor)
        if body.revision != scenario.revision:
            raise conflict("该场景已被他人修改，请刷新后重试")
        data = body.model_dump(exclude_unset=True)
        if not data:
            return scenario_response(db, scenario)

        if (name := data.get("name")) is not None:
            name = name.strip()
            if not name:
                raise bad_request("场景名称不能为空")
            scenario.name = name
        if data.get("description") is not None:
            scenario.description = data["description"].strip() or None
        if data.get("enabled") is not None:
            scenario.enabled = bool(data["enabled"])
        if data.get("priority") is not None:
            scenario.priority = data["priority"]
        if (bt := data.get("behavior_type")) is not None:
            if bt not in MOCK_BEHAVIOR_TYPES:
                raise bad_request(f"行为类型取值非法：{bt}")
            scenario.behavior_type = bt
        if "delay_ms" in data:
            scenario.delay_ms = self._cap_delay(data["delay_ms"], scenario.behavior_type)
        if (sc := data.get("status_code")) is not None:
            scenario.status_code = sc
        if "response_headers" in data:
            scenario.response_headers = data["response_headers"]
        if "response_body" in data:
            scenario.response_body = data["response_body"]
        if "response_template" in data:
            scenario.response_template = data["response_template"]

        # is_default：true 时清同 Endpoint 旧默认（含自己以外的）。
        if "is_default" in data:
            new_default = bool(data["is_default"])
            if new_default and not scenario.is_default:
                self._clear_other_defaults(db, scenario.mock_endpoint_id, exclude_id=scenario.id)
            scenario.is_default = new_default

        scenario.revision = (scenario.revision or 0) + 1
        db.commit()
        db.refresh(scenario)
        return scenario_response(db, scenario)

    def replace_matchers(
        self, db: Session, scenario_id: int, body: MockMatchersReplace, *, actor: User,
    ) -> MockScenarioResponse:
        scenario = self._get_writable_or_404(db, scenario_id, actor)
        # 与 PATCH 同样的乐观锁：matcher 是整体重建，不加校验时两个会话会互相覆盖
        # （最后写入者静默丢掉对方刚保存的规则集）。不传 revision 保持向后兼容。
        if body.revision is not None and body.revision != scenario.revision:
            raise conflict("该场景已被他人修改，请刷新后重试")
        for m in body.matchers:
            self._validate_matcher(m)
        db.query(MockMatcher).filter(MockMatcher.scenario_id == scenario.id).delete(
            synchronize_session=False
        )
        db.flush()
        for m in body.matchers:
            db.add(self._matcher_row(scenario.id, scenario.project_id, m))
        scenario.revision = (scenario.revision or 0) + 1
        db.commit()
        db.refresh(scenario)
        return scenario_response(db, scenario)

    # ---------------------------------------------------------------- 默认 / 复制

    def set_default(self, db: Session, scenario_id: int, *, actor: User) -> MockScenarioResponse:
        scenario = self._get_writable_or_404(db, scenario_id, actor)
        if not scenario.is_default:
            self._clear_other_defaults(db, scenario.mock_endpoint_id, exclude_id=scenario.id)
            scenario.is_default = True
            scenario.revision = (scenario.revision or 0) + 1
            db.commit()
            db.refresh(scenario)
        return scenario_response(db, scenario)

    def duplicate(
        self, db: Session, scenario_id: int, new_key: str, *, actor: User,
    ) -> MockScenarioResponse:
        """复制场景（含 matchers）；新 scenario_key 必须同接口唯一。"""
        src = self._get_writable_or_404(db, scenario_id, actor)
        key = (new_key or "").strip()
        if not re.fullmatch(SCENARIO_KEY_PATTERN, key):
            raise conflict(f"scenario_key 必须匹配 {SCENARIO_KEY_PATTERN}")
        if (
            db.query(MockScenario)
            .filter(
                MockScenario.mock_endpoint_id == src.mock_endpoint_id,
                MockScenario.scenario_key == key,
            )
            .first()
            is not None
        ):
            raise conflict("同接口下 scenario_key 已存在")
        copy = MockScenario(
            project_id=src.project_id,
            mock_endpoint_id=src.mock_endpoint_id,
            name=f"{src.name}（副本）",
            scenario_key=key,
            description=src.description,
            enabled=src.enabled,
            is_default=False,  # 副本不当默认，避免破坏唯一默认。
            priority=src.priority,
            behavior_type=src.behavior_type,
            delay_ms=src.delay_ms,
            status_code=src.status_code,
            response_headers=src.response_headers,
            response_body=src.response_body,
            response_template=src.response_template,
            created_by=actor.id,
        )
        db.add(copy)
        db.flush()
        for m in db.query(MockMatcher).filter(MockMatcher.scenario_id == src.id).all():
            db.add(MockMatcher(
                project_id=src.project_id, scenario_id=copy.id,
                source=m.source, field=m.field, operator=m.operator,
                expected_value=m.expected_value, priority=m.priority, enabled=m.enabled,
            ))
        db.commit()
        db.refresh(copy)
        return scenario_response(db, copy)

    # ---------------------------------------------------------------- 试跑（§三十三）

    def test_scenario(
        self, db: Session, scenario_id: int, body: ScenarioTestRequest, user: User,
    ) -> ScenarioTestResponse:
        """模拟一个请求，评估该 Scenario 的 Matcher 并构造响应，不调用被测系统（§三十三）。

        试跑针对「已知场景」，所以不再做 Endpoint path 模式匹配，只把请求路径按
        所属 Endpoint 的 path 模式提取路径参数，供 PATH source 的 Matcher 评估。
        """
        scenario = self._get_or_404(db, scenario_id, user)
        endpoint = db.get(MockEndpoint, scenario.mock_endpoint_id)
        # 用 Endpoint 的 path 模式从 body.path 提取路径参数；不匹配则视为空。
        _, path_params = match_path(endpoint.path if endpoint is not None else "/", body.path)

        matchers = (
            db.query(MockMatcher)
            .filter(MockMatcher.scenario_id == scenario.id, MockMatcher.enabled.is_(True))
            .order_by(MockMatcher.priority.asc(), MockMatcher.id.asc())
            .all()
        )
        snapshot = RequestSnapshot(
            method=(body.method or "GET").upper(),
            path=body.path,
            path_params=path_params,
            query=body.query or {},
            headers=body.headers or {},
            body=body.body,
        )
        matched = evaluate_matchers(snapshot, matchers) if matchers else True

        if not matched or not scenario.enabled:
            return ScenarioTestResponse(matched=False, duration_ms=0, delay_ms=0)

        started = time.perf_counter()
        ctx = RequestContext(
            path_params=path_params, query=body.query or {},
            headers=body.headers or {}, body=body.body,
        )
        built = build_response(
            scenario, request=ctx, request_id="scenario-test",
            timestamp=int(time.time()),
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ScenarioTestResponse(
            matched=True,
            scenario_id=scenario.id,
            scenario_key=scenario.scenario_key,
            status_code=built.status_code,
            headers=built.headers,
            body=built.body,
            duration_ms=duration_ms,
            delay_ms=built.delay_ms,
        )

    # ---------------------------------------------------------------- 内部：校验

    def _validate_body(self, body: MockScenarioCreate) -> None:
        name = (body.name or "").strip()
        if not name:
            raise bad_request("场景名称不能为空")
        if body.behavior_type not in MOCK_BEHAVIOR_TYPES:
            raise bad_request(f"行为类型取值非法：{body.behavior_type}")
        body.delay_ms = self._cap_delay(body.delay_ms, body.behavior_type)

    def _cap_delay(self, delay_ms: int | None, behavior_type: str) -> int | None:
        """delay_ms 上限 60s；超限报 MOCK_TIMEOUT_TOO_LARGE（§七）。"""
        if delay_ms is None:
            return None
        if behavior_type not in ("DELAY_RESPONSE", "TIMEOUT"):
            return None  # 非延迟行为不存 delay。
        if delay_ms < 0:
            raise bad_request("delay_ms 不能为负")
        if delay_ms > MOCK_RUNTIME_MAX_TIMEOUT * 1000:
            raise AppError(
                f"delay_ms 超过上限 {MOCK_RUNTIME_MAX_TIMEOUT}s",
                status_code=400, code=CODE_MOCK_TIMEOUT_TOO_LARGE,
            )
        return delay_ms

    def _validate_matcher(self, m) -> None:
        if m.source not in MOCK_MATCHER_SOURCES:
            raise AppError(
                f"Matcher source 取值非法：{m.source}",
                status_code=400, code=CODE_MOCK_MATCHER_INVALID,
            )
        if m.operator not in MOCK_MATCHER_OPERATORS:
            raise AppError(
                f"Matcher operator 取值非法：{m.operator}",
                status_code=400, code=CODE_MOCK_MATCHER_INVALID,
            )
        if not (m.field or "").strip():
            raise AppError(
                "Matcher field 不能为空",
                status_code=400, code=CODE_MOCK_MATCHER_INVALID,
            )
        # JSON_PATH_* 操作符要求 field 以 $ 开头（BODY 源）。
        if m.operator.startswith("JSON_PATH_") and not m.field.startswith("$"):
            raise AppError(
                f"操作符 {m.operator} 要求 field 为 JSONPath（以 $ 开头）",
                status_code=400, code=CODE_MOCK_MATCHER_INVALID,
            )
        # EXISTS / NOT_EXISTS / JSON_PATH_EXISTS 是存在性判断，不读 expected_value；
        # 其余操作符必须有。JSON_PATH_EXISTS 漏在这里会导致前端（已按「无期望值」
        # 提交）保存 JSONPath 存在性规则时必然 400。
        if (
            m.operator not in ("EXISTS", "NOT_EXISTS", "JSON_PATH_EXISTS")
            and m.expected_value is None
        ):
            raise AppError(
                f"操作符 {m.operator} 需要 expected_value",
                status_code=400, code=CODE_MOCK_MATCHER_INVALID,
            )

    def _matcher_row(self, scenario_id: int, project_id: int, m) -> MockMatcher:
        return MockMatcher(
            project_id=project_id,
            scenario_id=scenario_id,
            source=m.source,
            field=m.field.strip(),
            operator=m.operator,
            expected_value=m.expected_value,
            priority=m.priority,
            enabled=m.enabled,
        )

    def _clear_other_defaults(
        self, db: Session, endpoint_id: int, *, exclude_id: int | None,
    ) -> None:
        """把同 Endpoint 其它 is_default=true 的场景置 false（部分唯一约束兜底）。"""
        q = db.query(MockScenario).filter(
            MockScenario.mock_endpoint_id == endpoint_id,
            MockScenario.is_default.is_(True),
        )
        if exclude_id is not None:
            q = q.filter(MockScenario.id != exclude_id)
        for other in q.all():
            other.is_default = False
        if q.count():
            db.flush()

    # ---------------------------------------------------------------- 内部：取实体

    def _get_endpoint_or_404(self, db: Session, endpoint_id: int, user: User) -> MockEndpoint:
        endpoint = db.get(MockEndpoint, endpoint_id)
        if endpoint is None:
            raise not_found("Mock 接口不存在")
        get_project_or_404(db, endpoint.project_id, user)
        return endpoint

    def _get_endpoint_writable(self, db: Session, endpoint_id: int, actor: User) -> MockEndpoint:
        endpoint = db.get(MockEndpoint, endpoint_id)
        if endpoint is None:
            raise not_found("Mock 接口不存在")
        require_writable_project(db, resolve_endpoint_project_id(db, endpoint_id), actor)
        return endpoint

    def _get_or_404(self, db: Session, scenario_id: int, user: User) -> MockScenario:
        row = db.get(MockScenario, scenario_id)
        if row is None:
            _raise_not_found()
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, scenario_id: int, actor: User) -> MockScenario:
        row = db.get(MockScenario, scenario_id)
        if row is None:
            _raise_not_found()
        require_writable_project(db, resolve_scenario_project_id(db, scenario_id), actor)
        return row


__all__ = ["MockScenarioService"]
